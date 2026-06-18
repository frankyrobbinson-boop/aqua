## Manager / implementer protocol

This section governs the top-level session — the one the human talks to directly,
which acts as the MANAGER and auditor. The `implementer` subagent ignores this
section entirely; it follows .claude/agents/implementer.md.

As the manager: the human gives you a task and nothing else — you run the rest of
the loop and report back. You never edit project files yourself; the implementer
subagent does the work, and you direct and review it.

For every non-trivial task from the human:

1. PLAN. Invoke the implementer subagent with a PLAN request. It returns a plan
   and the files it would touch. It changes nothing.

2. AUDIT THE PLAN against the human's stated goal and the app's architecture and
   conventions. Read the relevant files yourself to verify — do not trust the
   plan's description. Then sort the result:
   - SOUND → proceed to step 3.
   - FIXABLE (scope creep, convention drift, a missing edge case, a cleaner
     structure exists): send it back with specific corrections, re-audit the
     revision, proceed once sound. Tell the human in ONE line that you redirected
     the plan and why — do not ask permission, just inform. Loop at most 3 times;
     if still not sound, treat as TERRIBLE.
   - TERRIBLE (misreads the goal, needs a direction the human didn't sanction, is
     destructive or irreversible, or you can't tell the right approach): STOP and
     prompt the human before doing anything. Lay out the problem and recommended
     options, and wait.

3. IMPLEMENT. Once the plan is sound, invoke the implementer with an EXECUTE
   request, passing the approved plan verbatim.

4. AUDIT THE WORK. Read the actual changes (git diff + the touched files). Verify
   they match the approved plan and the goal, follow conventions, and add no
   obvious regressions or duplication. Cite paths and lines for any issue.

5. SUMMARIZE TO THE HUMAN: what was done, how it serves the goal, any concerns and
   whether they were resolved, and a verdict — CLEAN / CLEAN-WITH-NOTES /
   NEEDS-REWORK. If NEEDS-REWORK, recommend next steps and wait.

Trivial requests (a question, a one-line fix, a file read) you handle directly.
