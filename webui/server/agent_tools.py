"""P9 — Plan-first protocol tools: ``plan`` and ``update_todo``.

These two tools are *protocol messages*, not real filesystem/network
actions. They mutate the per-agent ``AgentRuntimeState`` in
``team_types.py`` and that's it.

Why custom (not registered in the OpenHarness tool registry)?

  - The OpenHarness registry is for tools the agent uses against the
    world (Bash, Read, Skill, etc.). Plan/update_todo are internal —
    they never touch the user's filesystem or the network.
  - Keeping them in a dedicated module makes smoke tests easy: just
    call ``execute_plan_tool(agent_name, args)`` and inspect state.
  - They don't need the OpenHarness Tool base class, input_model
    validation pipeline, or execution context — which would all be
    dead weight here.

The schemas below are OpenAI-format dicts (the same shape
``_tools_for_agent`` already produces for OpenHarness tools). The
``scenario_runner._execute_tool`` function dispatches to
``execute_plan_tool`` / ``execute_update_todo_tool`` when the tool
name matches, before falling through to the registry.

Atomicity guarantee: ``execute_*_tool`` is a plain (non-async) function
that does *read state → validate → mutate state* in one Python frame.
This means a cooperative cancel (``asyncio.CancelledError``) cannot
land mid-mutation and leave a half-updated state. The smoke test
``smoke_p9_plan_first`` verifies this directly.
"""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .team_types import (
    AgentRuntimeState,
    TodoStep,
    can_transition,
    get_agent_state,
    touch,
)


# ---------------------------------------------------------------------------
# OpenAI-format tool schemas
# ---------------------------------------------------------------------------
# Both schemas are deliberately permissive (no ``required`` array except
# the truly mandatory fields) so the LLM has room to make small mistakes
# without the tool refusing to run. Validation is done in Python, not
# by the schema, so we can return a friendly error string the LLM can
# actually read and act on.

PLAN_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "plan",
        "description": (
            "【MUST be the first tool you call】Publish your execution plan. "
            "Each todo is an atomic step you will execute, in order. "
            "After calling this tool, you will be in EXECUTING mode and "
            "should run each step, marking it done via update_todo(). "
            "Do NOT call any other tool or output any text before plan()."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "1+ step objects, each with id/content/optional skill_hint/depends_on.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Step identifier, e.g. 't1'."},
                            "content": {"type": "string", "description": "What this step does."},
                            "skill_hint": {"type": "string", "description": "Suggested skill name (optional)."},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Other step ids this one depends on (metadata only).",
                            },
                        },
                        "required": ["id", "content"],
                    },
                },
            },
            "required": ["todos"],
        },
    },
}


UPDATE_TODO_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_todo",
        "description": (
            "Mark a step's status change. Use 'running' to start, 'done' "
            "with a result to finish, 'failed' to report an error, or "
            "'skipped' if a coordinator asks you to skip. The state machine "
            "enforces legal transitions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step_id": {"type": "string", "description": "The id of the step to update."},
                "status": {
                    "type": "string",
                    "enum": ["running", "done", "failed", "skipped", "pending"],
                    "description": "New status.",
                },
                "result": {"type": "string", "description": "Result text (recommended when status=done)."},
                "error": {"type": "string", "description": "Error detail (recommended when status=failed)."},
            },
            "required": ["step_id", "status"],
        },
    },
}


# ---------------------------------------------------------------------------
# Internal: Pydantic models for input validation
# ---------------------------------------------------------------------------
# These are stricter than the OpenAI schema. We use them to give the LLM
# a clear error message if it sends a malformed payload (e.g. a step
# without an id, or a status that isn't a known value).

class _PlanStepInput(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=2000)
    skill_hint: str | None = Field(default=None, max_length=64)
    depends_on: list[str] = Field(default_factory=list)


class _PlanInput(BaseModel):
    todos: list[_PlanStepInput] = Field(min_length=1, max_length=50)


class _UpdateTodoInput(BaseModel):
    step_id: str = Field(min_length=1, max_length=64)
    status: str
    result: str | None = Field(default=None, max_length=20000)
    error: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Executors (called by scenario_runner._execute_tool)
# ---------------------------------------------------------------------------
# Return shape mirrors _execute_tool: ``{"output": str, "is_error": bool}``.
# On error, the LLM sees the message as a tool_result and can retry.

def execute_plan_tool(agent_name: str, raw_input: dict[str, Any]) -> dict[str, Any]:
    """Validate + apply a `plan()` call for `agent_name`.

    Side effect: replaces ``state.todos`` and bumps ``state.plan_rev``,
    moving the prior list (if any) to ``state.archived_todos``.

    Note: the LLM may call plan() multiple times (e.g. after a revise
    instruction in a later phase). The archived_todos history is the
    audit trail — we never silently drop a plan.
    """
    try:
        parsed = _PlanInput.model_validate(raw_input)
    except ValidationError as e:
        return {"output": f"plan() validation error: {e}", "is_error": True}

    # Cross-field checks: id uniqueness + depends_on references.
    ids = [s.id for s in parsed.todos]
    if len(set(ids)) != len(ids):
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        return {"output": f"plan() error: duplicate step ids: {dupes}", "is_error": True}
    for step in parsed.todos:
        for dep in step.depends_on:
            if dep not in ids:
                return {
                    "output": f"plan() error: step {step.id!r} depends on unknown step {dep!r}",
                    "is_error": True,
                }

    state = get_agent_state(agent_name)
    # Archive the previous plan (if any) before replacing.
    if state.todos:
        state.archived_todos.append(state.todos)
    state.todos = [TodoStep(**s.model_dump()) for s in parsed.todos]
    state.plan_returned = True
    state.plan_rev += 1
    state.is_finished = False  # a fresh plan means we're back in flight
    state.finish_reason = None
    touch(state)
    return {
        "output": f"plan() accepted: {len(state.todos)} steps, rev={state.plan_rev}",
        "is_error": False,
    }


def execute_update_todo_tool(agent_name: str, raw_input: dict[str, Any]) -> dict[str, Any]:
    """Validate + apply a single `update_todo()` call."""
    try:
        parsed = _UpdateTodoInput.model_validate(raw_input)
    except ValidationError as e:
        return {"output": f"update_todo() validation error: {e}", "is_error": True}

    if parsed.status not in ("pending", "running", "done", "failed", "skipped"):
        return {
            "output": f"update_todo() error: invalid status {parsed.status!r}",
            "is_error": True,
        }

    state = get_agent_state(agent_name)
    if not state.plan_returned:
        return {
            "output": "update_todo() error: no plan() has been called yet",
            "is_error": True,
        }
    step = next((s for s in state.todos if s.id == parsed.step_id), None)
    if step is None:
        return {
            "output": f"update_todo() error: step {parsed.step_id!r} not in current plan",
            "is_error": True,
        }

    if not can_transition(step.status, parsed.status):  # type: ignore[arg-type]
        return {
            "output": (
                f"update_todo() error: illegal transition "
                f"{step.status!r} -> {parsed.status!r} for step {parsed.step_id!r}"
            ),
            "is_error": True,
        }

    step.status = parsed.status  # type: ignore[assignment]
    now = time.time()
    if parsed.result is not None:
        step.result = parsed.result
    if parsed.error is not None:
        step.error = parsed.error
    if parsed.status == "running" and step.started_at is None:
        step.started_at = now
    if parsed.status in ("done", "failed", "skipped"):
        step.finished_at = now
    touch(state)
    return {
        "output": f"update_todo() ok: {parsed.step_id} -> {parsed.status}",
        "is_error": False,
    }


# ---------------------------------------------------------------------------
# Public dispatch table
# ---------------------------------------------------------------------------
# scenario_runner._execute_tool consults this to route plan/update_todo
# before falling through to the OpenHarness registry. Keeping it as a
# module-level mapping (rather than hardcoding ``if name == "plan":``)
# makes it easy to extend with more internal tools later.
PROTOCOL_TOOL_EXECUTORS: dict[str, Any] = {
    "plan": execute_plan_tool,
    "update_todo": execute_update_todo_tool,
}

PROTOCOL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    PLAN_TOOL_SCHEMA,
    UPDATE_TODO_TOOL_SCHEMA,
]
