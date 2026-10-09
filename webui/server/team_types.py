"""P9 — Team runtime state: per-agent TODO plan + step status.

This is the foundation of the "plan-first" multi-agent protocol:

  1. Each specialist MUST call the `plan` tool before any other action.
     The first-turn `plan` call publishes a list of `TodoStep` into
     `AgentRuntimeState.todos`. (Future revisions move the old list
     to `archived_todos` so we never lose history.)

  2. While executing, the specialist calls `update_todo(id, status,
     result=...)` to mark steps done/failed/skipped. The tool enforces
     a strict state machine so the UI can trust the status transitions.

  3. The in-process `_TEAM_STATE` dict is the single source of truth
     for per-agent runtime state during a scenario. It's intentionally
     not persisted: a backend restart resets to a clean slate. (Phase 2+
     may add a persistence layer.)

Layering note: this module is intentionally tiny (Pydantic models +
helpers, no business logic). The actual tool execution lives in
``agent_tools.py``; the event-yielding lives in ``scenario_runner.py``.
Keeping them separate makes the smoke tests easy to write.
"""
from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field


TodoStatus = Literal["pending", "running", "done", "skipped", "failed"]


class TodoStep(BaseModel):
    """One atomic step in a specialist's plan.

    Lifecycle: pending → running → (done | failed | skipped).
    `failed` can return to `pending` (retry). `done` and `skipped` are
    terminal — enforced by the state machine in ``update_todo``.

    `depends_on` is metadata for the agent's own ordering; the
    scenario_runner does NOT enforce dependency order (P9.1 decision:
    "let the LLM own sequencing"). It's recorded here so the UI can
    draw dependency arrows if it wants.
    """

    id: str
    content: str
    skill_hint: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    status: TodoStatus = "pending"
    result: str | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None


class AgentRuntimeState(BaseModel):
    """Process-wide runtime state for one specialist across a session.

    One row per agent.name. Lives in the in-process `_TEAM_STATE` dict.
    The `is_finished` flag is set when the agent loop returns
    successfully (or aborts) — the UI uses it to show a final badge.

    `archived_todos` holds prior plan versions (populated when the
    coordinator pushes a revise() in a later phase). For Phase 0+1
    the only writer is "initial plan", so archived_todos stays empty.
    """

    name: str
    display_name: str = ""
    color: str = "gray"
    initial_prompt: str = ""
    plan_returned: bool = False
    plan_rev: int = 0
    todos: list[TodoStep] = Field(default_factory=list)
    archived_todos: list[list[TodoStep]] = Field(default_factory=list)
    last_event_ts: float = 0.0
    is_finished: bool = False
    finish_reason: str | None = None
    # P10 — coordinator protocol state.
    #   paused:           True after a `plan_first_pause` run returns (plan
    #                     emitted, no execution). Cleared by the runner when
    #                     the specialist is re-invoked via `proceed`/`revise`.
    #   stop_requested:   Set by the coordinator's `finish_agent` tool. The
    #                     specialist's `run_agent_turn` checks this at the
    #                     start of every turn and exits with a one-line
    #                     summary if set. Async-cancel-safe: the check
    #                     happens between LLM yields, never mid-stream.
    paused: bool = False
    stop_requested: bool = False


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------
# All accessors go through get_agent_state(); never touch _TEAM_STATE
# directly from outside this module. This makes it easy to swap the
# backend (e.g. SQLite) later without rewriting call sites.
_TEAM_STATE: dict[str, AgentRuntimeState] = {}


def get_agent_state(name: str, **init: Any) -> AgentRuntimeState:
    """Return the runtime state for `name`, creating it on first access.

    `init` keywords are forwarded to ``AgentRuntimeState`` (only used
    for the lazy-init path so callers can seed display_name/color/
    initial_prompt without a separate set_state call).
    """
    state = _TEAM_STATE.get(name)
    if state is None:
        state = AgentRuntimeState(name=name, **init)
        _TEAM_STATE[name] = state
    return state


def reset_team_state() -> None:
    """Wipe all runtime state. Smoke tests call this between cases."""
    _TEAM_STATE.clear()


def list_agent_states() -> list[AgentRuntimeState]:
    """Snapshot of all current agent states. Order is insertion order."""
    return list(_TEAM_STATE.values())


# ---------------------------------------------------------------------------
# State-machine table for TodoStep.status transitions
# ---------------------------------------------------------------------------
# This table is the single source of truth for which transitions are
# allowed. ``agent_tools.update_todo`` consults it before mutating.
# Keep the table tiny — 5 statuses, ~10 transitions — and document each.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending":  {"running", "skipped"},
    "running":  {"done", "failed", "skipped", "pending"},  # pending=abort back to queue
    "done":     set(),                                       # terminal
    "failed":   {"pending"},                                 # retry path
    "skipped":  set(),                                       # terminal
}


def can_transition(from_status: TodoStatus, to_status: TodoStatus) -> bool:
    """True iff `from_status` → `to_status` is in the state machine."""
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def touch(state: AgentRuntimeState) -> None:
    """Update last_event_ts — call after any mutation to keep the UI's
    "last activity" indicator fresh."""
    state.last_event_ts = time.time()
