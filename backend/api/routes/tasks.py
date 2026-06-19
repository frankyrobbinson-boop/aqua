"""Task tracking: run pipeline scripts as subprocesses and stream their stdout
to the client via SSE. In-memory registry; restart wipes task history."""

import asyncio
import json
import os
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


class Task:
    def __init__(self, cmd: list[str], cwd: str, metadata: dict | None = None):
        self.id = uuid.uuid4().hex
        self.cmd = cmd
        self.cwd = cwd
        self.status = "pending"  # pending | running | completed | failed
        self.log_lines: list[str] = []
        self.exit_code: int | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.metadata = metadata or {}
        self._new_lines = asyncio.Event()
        # Strong reference to the asyncio.Task running this Task's run() coroutine.
        # Without this, the event loop holds only a weak reference and the task
        # can be garbage-collected mid-run, silently killing the subprocess.
        self._runner: asyncio.Task | None = None
        # Handle to the subprocess once spawned. Used by the cancel endpoint to
        # kill the OS process — cancelling the asyncio.Task alone doesn't tear
        # down the child.
        self._process: asyncio.subprocess.Process | None = None

    def summary(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log_count": len(self.log_lines),
            "metadata": self.metadata,
        }

    async def run(self):
        self.status = "running"
        self.started_at = time.time()
        try:
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
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
                self.log_lines.append(line)
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
            self.log_lines.append("[cancelled]")
            self.status = "failed"
            self.exit_code = -1
            raise
        except Exception as exc:
            self.log_lines.append(f"[task runner error] {exc!r}")
            self.status = "failed"
            self.exit_code = -1
        finally:
            self.finished_at = time.time()
            self._new_lines.set()

    async def stream_logs(self) -> AsyncIterator[str]:
        """Yield log lines as they arrive, returning when the task finishes.

        Uses a clear-then-re-check pattern around `_new_lines.wait()`: a producer
        that appends + sets between our inner-while exit and the clear() would
        otherwise have its signal lost, stalling the consumer until the NEXT
        line arrives. With multiple SSE consumers on the same task, the lost
        wakeup compounds. The re-check after clear catches the race."""
        index = 0
        while True:
            while index < len(self.log_lines):
                yield self.log_lines[index]
                index += 1
            if self.status in ("completed", "failed"):
                return
            self._new_lines.clear()
            # Re-check after clearing: if a line landed (or the task ended)
            # between exiting the inner while and clear(), don't go to sleep.
            if index < len(self.log_lines) or self.status in ("completed", "failed"):
                continue
            await self._new_lines.wait()


# In-memory registry. Single-process — fine for local dev. Restart wipes.
# OrderedDict so we can evict the oldest finished entry when we hit _MAX_TASKS.
_REGISTRY: "OrderedDict[str, Task]" = OrderedDict()


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


def start_task(cmd: list[str], cwd: str, metadata: dict | None = None) -> Task:
    """Create a task, schedule its run, register, and return it."""
    _evict_if_full()
    task = Task(cmd, cwd, metadata)
    _REGISTRY[task.id] = task
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
        # Replay any logs already accumulated, then stream new ones.
        async for line in task.stream_logs():
            yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"
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
