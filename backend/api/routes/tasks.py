"""Task tracking: run pipeline scripts as subprocesses and stream their stdout
to the client via SSE. In-memory registry; restart wipes task history."""

import asyncio
import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse


router = APIRouter(prefix="/tasks", tags=["tasks"])

# Cap on retained tasks. The registry is in-memory only, but on a long-running
# dev server with many small re-runs it can grow without bound. When we hit the
# cap, evict the oldest already-finished task; if none have finished, leave
# the cap alone (active tasks must not be lost).
_MAX_TASKS = 200

# Structured stage-event marker. Subprocesses print
# ``[[STAGE:<name>:<status>]]`` on its own line; the task runner converts each
# match into a typed SSE event so the frontend can render per-stage progress
# without screen-scraping log lines. Non-matching lines flow through as plain
# log events. Status whitelist: started, completed.
_STAGE_EVENT_RE = re.compile(r"^\s*\[\[STAGE:([a-z_]+):([a-z_]+)\]\]\s*$")
_STAGE_STATUSES = {"started", "completed"}


class Task:
    def __init__(
        self,
        cmd: list[str],
        cwd: str,
        metadata: dict | None = None,
        env_overrides: dict[str, str] | None = None,
        kind: str | None = None,
        project_slug: str | None = None,
    ):
        self.id = uuid.uuid4().hex
        self.cmd = cmd
        self.cwd = cwd
        self.status = "pending"  # pending | running | completed | failed
        # Each entry is either {"type": "log", "line": str} or
        # {"type": "stage", "stage": str, "status": str}. Stored as a single
        # ordered list so SSE replay-on-reconnect preserves the original
        # interleaving of stage markers and log lines.
        self.events: list[dict[str, Any]] = []
        self.exit_code: int | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.metadata = metadata or {}
        # Lock-registry coordinates: kept on the instance so Task.run()'s
        # finally block can release the (slug, kind) reservation without
        # needing the caller to re-derive them.
        self.kind = kind
        self.project_slug = project_slug
        # Extra env vars layered on top of os.environ when the subprocess
        # spawns. Used by /render to pass per-render flags to run_render.py.
        self.env_overrides = env_overrides or {}
        self._new_lines = asyncio.Event()
        # Strong reference to the asyncio.Task running this Task's run() coroutine.
        # Without this, the event loop holds only a weak reference and the task
        # can be garbage-collected mid-run, silently killing the subprocess.
        self._runner: asyncio.Task | None = None
        # Handle to the subprocess once spawned. Used by the cancel endpoint to
        # kill the OS process — cancelling the asyncio.Task alone doesn't tear
        # down the child.
        self._process: asyncio.subprocess.Process | None = None

    @property
    def log_lines(self) -> list[str]:
        """Back-compat view: log lines only, excluding structured stage events.
        Kept for ``GET /tasks/{id}`` callers that just want the raw stdout."""
        return [e["line"] for e in self.events if e.get("type") == "log"]

    def summary(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log_count": sum(1 for e in self.events if e.get("type") == "log"),
            "metadata": self.metadata,
        }

    def _append_line(self, line: str) -> None:
        """Classify ``line`` as a structured stage event or a plain log line
        and append the corresponding event dict. Status outside the whitelist
        falls through as a log line so a typo'd marker doesn't get silently
        dropped."""
        m = _STAGE_EVENT_RE.match(line)
        if m and m.group(2) in _STAGE_STATUSES:
            self.events.append(
                {"type": "stage", "stage": m.group(1), "status": m.group(2)}
            )
        else:
            self.events.append({"type": "log", "line": line})

    async def run(self):
        self.status = "running"
        self.started_at = time.time()
        try:
            env = {**os.environ, "PYTHONUNBUFFERED": "1", **self.env_overrides}
            process = await asyncio.create_subprocess_exec(
                *self.cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.cwd,
                env=env,
            )
            self._process = process
            assert process.stdout is not None
            async for line_bytes in process.stdout:
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
                self._append_line(line)
                self._new_lines.set()
            self.exit_code = await process.wait()
            self.status = "completed" if self.exit_code == 0 else "failed"
        except asyncio.CancelledError:
            # Cancel endpoint asked us to stop. Kill the subprocess if still alive
            # so the user's run_*.py doesn't keep burning API credits.
            if self._process is not None and self._process.returncode is None:
                self._process.kill()
                try:
                    await self._process.wait()
                except Exception:
                    pass
            self._append_line("[cancelled]")
            self.status = "failed"
            self.exit_code = -1
            raise
        except Exception as exc:
            self._append_line(f"[task runner error] {exc!r}")
            self.status = "failed"
            self.exit_code = -1
        finally:
            self.finished_at = time.time()
            self._new_lines.set()
            # Release the per-(slug, kind) reservation so the next request can
            # start. Cleared in finally so cancelled / crashed tasks don't
            # leave their slot wedged.
            if self.kind is not None and self.project_slug is not None:
                with _ACTIVE_LOCK:
                    key = (self.project_slug, self.kind)
                    if _ACTIVE_BY_KEY.get(key) == self.id:
                        del _ACTIVE_BY_KEY[key]

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield event dicts as they arrive, returning when the task finishes.

        Uses a clear-then-re-check pattern around `_new_lines.wait()`: a producer
        that appends + sets between our inner-while exit and the clear() would
        otherwise have its signal lost, stalling the consumer until the NEXT
        line arrives. With multiple SSE consumers on the same task, the lost
        wakeup compounds. The re-check after clear catches the race."""
        index = 0
        while True:
            while index < len(self.events):
                yield self.events[index]
                index += 1
            if self.status in ("completed", "failed"):
                return
            self._new_lines.clear()
            # Re-check after clearing: if an event landed (or the task ended)
            # between exiting the inner while and clear(), don't go to sleep.
            if index < len(self.events) or self.status in ("completed", "failed"):
                continue
            await self._new_lines.wait()


# In-memory registry. Single-process — fine for local dev. Restart wipes.
# OrderedDict so we can evict the oldest finished entry when we hit _MAX_TASKS.
_REGISTRY: "OrderedDict[str, Task]" = OrderedDict()

# Per-(project_slug, kind) reservations: at most one active task per pair.
# Cleared from Task.run()'s finally block. Threading lock (not asyncio) so the
# guard works whether start_task is called from sync or async code paths.
_ACTIVE_BY_KEY: dict[tuple[str, str], str] = {}
_ACTIVE_LOCK = threading.Lock()


def _evict_if_full() -> None:
    """Drop the oldest finished task if the registry is at capacity. Never
    drops a running/pending task — better to let the dict grow temporarily
    than to lose live state."""
    if len(_REGISTRY) < _MAX_TASKS:
        return
    for tid, t in list(_REGISTRY.items()):
        if t.status in ("completed", "failed"):
            del _REGISTRY[tid]
            return


def start_task(
    cmd: list[str],
    cwd: str,
    metadata: dict | None = None,
    env_overrides: dict[str, str] | None = None,
    kind: str | None = None,
    project_slug: str | None = None,
) -> Task:
    """Create a task, schedule its run, register, and return it.

    When both ``kind`` and ``project_slug`` are supplied, enforces at most one
    active task per (slug, kind) pair: a conflicting start raises HTTP 409 with
    the existing task id surfaced in the detail message. Pass both fields from
    every route so concurrent button-mashes can't spawn duplicate pipelines."""
    if kind is not None and project_slug is not None:
        key = (project_slug, kind)
        with _ACTIVE_LOCK:
            existing_id = _ACTIVE_BY_KEY.get(key)
            if existing_id is not None:
                existing = _REGISTRY.get(existing_id)
                if existing is not None and existing.status in ("pending", "running"):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"project {project_slug!r} already has a {kind!r} "
                            f"task running (id={existing_id}). Wait for it to "
                            f"finish or cancel it before starting another."
                        ),
                    )
                # Stale reservation (task crashed without releasing) — drop it
                # and proceed.
                _ACTIVE_BY_KEY.pop(key, None)

    _evict_if_full()
    task = Task(
        cmd, cwd, metadata,
        env_overrides=env_overrides,
        kind=kind,
        project_slug=project_slug,
    )
    _REGISTRY[task.id] = task
    if kind is not None and project_slug is not None:
        with _ACTIVE_LOCK:
            _ACTIVE_BY_KEY[(project_slug, kind)] = task.id
    # Keep a strong reference on the Task instance — asyncio only weak-refs
    # background tasks via the loop, so dropping this return value can let GC
    # cull the coroutine mid-run.
    task._runner = asyncio.create_task(task.run())
    return task


def get_task(task_id: str) -> Task:
    task = _REGISTRY.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task


@router.get("")
def list_tasks(
    project_slug: Optional[str] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List tasks, optionally filtered by project_slug, kind, or status.

    Filtered listing is how the frontend recovers in-flight runs after a page
    reload: RunPanel queries (project_slug=X, kind=Y, status=running) to find
    its own task and re-attach the SSE stream.

    Sort order: most-recently-started first, with pending tasks (started_at
    still None) ahead of any started task so a fresh start beats a stale run."""
    results = list(_REGISTRY.values())
    if project_slug is not None:
        results = [t for t in results if t.metadata.get("project_slug") == project_slug]
    if kind is not None:
        results = [t for t in results if t.metadata.get("kind") == kind]
    if status is not None:
        results = [t for t in results if t.status == status]
    # started_at=None (pending) sorts highest. Otherwise newest first.
    results.sort(
        key=lambda t: (t.started_at is None, t.started_at or 0.0),
        reverse=True,
    )
    return [t.summary() for t in results]


@router.get("/{task_id}")
def get_task_status(task_id: str) -> dict:
    task = get_task(task_id)
    return {**task.summary(), "logs": task.log_lines}


@router.get("/{task_id}/stream")
async def stream_task(task_id: str):
    task = get_task(task_id)

    async def event_gen():
        # Replay any events already accumulated, then stream new ones. Both
        # log lines and structured stage events flow through this single
        # iterator so reconnecting clients see the original interleaving.
        async for event in task.stream_events():
            yield f"data: {json.dumps(event)}\n\n"
        yield (
            f"data: {json.dumps({'type': 'done', 'status': task.status, 'exit_code': task.exit_code})}\n\n"
        )

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.delete("/{task_id}")
async def cancel_task(task_id: str) -> dict:
    """Cancel a running task. No-op if already finished."""
    task = get_task(task_id)
    if task.status in ("completed", "failed"):
        return {"ok": True, "already_done": True, "status": task.status}
    if task._runner is not None and not task._runner.done():
        task._runner.cancel()
    return {"ok": True, "cancelled": True}
