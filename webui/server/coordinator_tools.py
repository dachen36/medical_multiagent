"""P10 — Coordinator protocol tools.

The coordinator is the LLM driver of a multi-agent run. Instead of
doing specialist work itself, it has 7 internal tools to manage the
specialists:

    dispatch(agent_name, task, wait_for="plan"|"done")
        Send a task to a specialist.  In ``plan`` mode, returns when
        the specialist has emitted its TODO plan; in ``done`` mode,
        returns only when the specialist reaches ``agent_done``.
        Specialist events stream through a shared queue so the UI
        sees them live (Overview cards animate, step status updates
        happen in real time).

    observe(agent_name)
        Snapshot the agent's runtime state: plan_rev, todos,
        is_finished, finish_reason, paused, stop_requested. The
        coordinator calls this between dispatches and after
        proceed/revise to decide what to do next.

    proceed(agent_name, instructions=None)
        Resume a specialist that has paused after plan() (state has
        todos but no execution yet).  Adds the optional instructions
        as a user message and runs the agent to completion (or until
        stop_requested fires).

    revise(agent_name, instructions=None, new_todos=None)
        Mid-flight: if new_todos is given, directly apply it as the
        new plan (archives the old one), then resume the agent with
        the optional instructions as a user message.  If only
        instructions, sends a "your plan is fine, here's a tweak"
        message and lets the agent continue with its current plan.

    finish_agent(agent_name, reason)
        Set ``state.stop_requested = True``.  The specialist's
        run_agent_turn checks this at the start of every turn and
        exits with a one-line summary.  Async-cancel-safe: the
        check happens between LLM yields, never mid-stream.

    assert_goal_coverage(criteria, confident)
        Self-check tool — forces the LLM to explicitly confirm that
        the user's goal has been met.  The tool returns a structured
        confirmation prompt that the LLM should respond to with
        ``confident=true`` before proceeding to publish_final_report.
        The system prompt instructs the LLM not to publish without
        a prior ``confident=true`` assert.

    publish_final_report(text)
        TERMINAL.  Stores the final report in the runner context and
        returns a sentinel.  The runner emits ``coordinator.done``
        and ``scenario.done status="ok"`` with the text.

Why a separate file (not agent_tools.py):

- The coordinator tools live in the COORDINATOR's LLM loop, not the
  specialist's.  Three of them (dispatch/proceed/revise) need to
  synchronously drive a specialist's run_agent_turn from within the
  coordinator's LLM call — that's a different lifecycle from
  specialist tools.
- They take a different context: the shared ``histories`` dict, the
  cancel event, the WS queue, the agents-by-name lookup.  Pushing
  that into agent_tools.py would bloat the specialist's tool
  schema and create a circular import (specialist tools would need
  the coordinator's context too).
- Keeping the 7 schemas in their own file is greppable: any future
  coordinator change has one obvious place to look.

Sync vs async executors:

Pure state mutations (observe, finish_agent, assert_goal_coverage,
publish_final_report) are sync — same atomicity guarantee as
agent_tools.  The three that drive a specialist run (dispatch,
proceed, revise) are async, because they consume the
``run_agent_turn`` async generator.  The dispatch table is a single
dict; the runner detects async executors with
``asyncio.iscoroutinefunction`` and awaits them.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, ValidationError

from .team_types import TodoStep, get_agent_state, touch


# ---------------------------------------------------------------------------
# OpenAI-format tool schemas (7)
# ---------------------------------------------------------------------------
# Schemas are deliberately permissive: no ``required`` array beyond the
# truly mandatory fields, and enum values are spelled out so the LLM
# sees the legal options.  Pydantic models below do stricter validation
# and return a friendly error string when the LLM slips up.

DISPATCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "dispatch",
        "description": (
            "派发任务给一个 specialist。wait_for='plan'（默认）时，"
            "specialist 必须先调用 plan() 给出 TODO 列表后返回（不执行）；"
            "wait_for='done' 时，specialist 一直跑到 agent_done 才返回。"
            "返回 specialist 的 plan（含 todos）或最终文本。"
            "v1 串行模式：一次只 dispatch 一个 specialist，等其返回后再 dispatch 下一个。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "specialist 名称，必须是已注册的 specialist（medical/iot/nas/education 等）。",
                },
                "task": {
                    "type": "string",
                    "description": "给 specialist 的具体任务描述。要聚焦在该 specialist 的领域。",
                },
                "wait_for": {
                    "type": "string",
                    "enum": ["plan", "done"],
                    "description": "返回时机。默认 'plan'。",
                },
            },
            "required": ["agent_name", "task"],
        },
    },
}


OBSERVE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "observe",
        "description": (
            "查看一个 specialist 的当前运行状态：是否有 plan、plan_rev、"
            "todos 列表（id/content/status/result）、是否 paused、是否"
            "is_finished、finish_reason。在 dispatch 后、proceed 前、或"
            "decide 何时调 finish_agent 时使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
            },
            "required": ["agent_name"],
        },
    },
}


PROCEED_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "proceed",
        "description": (
            "让一个已经 plan() 但还未执行的 specialist 继续跑（恢复 paused 状态）。"
            "可选的 instructions 会作为 user message 追加到 specialist 的历史。"
            "默认 instructions 为 '请按 plan 继续执行'。返回 summary（含 todos 终态）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "instructions": {
                    "type": "string",
                    "description": "可选。继续执行的指示，会作为 user message 追加。",
                },
            },
            "required": ["agent_name"],
        },
    },
}


REVISE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "revise",
        "description": (
            "mid-flight 调整 specialist 的计划。如果给了 new_todos，"
            "会直接替换 state.todos（旧的进入 archived_todos），"
            "然后让 specialist 按新计划继续。可选的 instructions 作为 user message 追加。"
            "适用于：观察到 specialist 偏离目标、或需要新加步骤时。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "instructions": {
                    "type": "string",
                    "description": "可选。给 specialist 的额外说明。",
                },
                "new_todos": {
                    "type": "array",
                    "description": "可选。新计划，每个 todo 至少含 id+content。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "content": {"type": "string"},
                            "skill_hint": {"type": "string"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["id", "content"],
                    },
                },
            },
            "required": ["agent_name"],
        },
    },
}


FINISH_AGENT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "finish_agent",
        "description": (
            "通知 specialist 早停。设置 state.stop_requested=True，"
            "specialist 会在当前 step 完成后退出并输出最终一句话总结。"
            "调用后立即返回 ack（不等 specialist 真正结束）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "reason": {
                    "type": "string",
                    "description": "为何早停（会写入 finish_reason）。",
                },
            },
            "required": ["agent_name", "reason"],
        },
    },
}


ASSERT_GOAL_COVERAGE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "assert_goal_coverage",
        "description": (
            "自我检查：用户的目标是否已经达成。\n"
            "本工具会返回一个结构化的确认 prompt。\n"
            "你必须用 confident=true|false 显式回应：\n"
            "  - confident=true  → 下一步调 publish_final_report(text)\n"
            "  - confident=false → 继续 dispatch / observe / proceed / revise\n"
            "不要跳过本工具直接 publish_final_report——系统 prompt 明确禁止。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "criteria": {
                    "type": "string",
                    "description": "目标达成的判定标准（用中文描述具体要求）。",
                },
                "confident": {
                    "type": "boolean",
                    "description": "你是否确认目标已达成？",
                },
            },
            "required": ["criteria", "confident"],
        },
    },
}


PUBLISH_FINAL_REPORT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "publish_final_report",
        "description": (
            "【TERMINAL】发布最终用户报告。调用后场景立即结束。\n"
            "调用前必须先用 assert_goal_coverage(criteria, confident=true) 显式确认目标达成。\n"
            "text 应是用 markdown 写成的综合报告，800-1500 字。\n"
            "调用本工具后不要再调任何其他工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "最终用户报告（markdown）。",
                },
            },
            "required": ["text"],
        },
    },
}


COORDINATOR_TOOL_SCHEMAS: list[dict[str, Any]] = [
    DISPATCH_SCHEMA,
    OBSERVE_SCHEMA,
    PROCEED_SCHEMA,
    REVISE_SCHEMA,
    FINISH_AGENT_SCHEMA,
    ASSERT_GOAL_COVERAGE_SCHEMA,
    PUBLISH_FINAL_REPORT_SCHEMA,
]


# ---------------------------------------------------------------------------
# Pydantic input models (stricter than the OpenAI schema)
# ---------------------------------------------------------------------------
class _DispatchInput(BaseModel):
    agent_name: str = Field(min_length=1, max_length=64)
    task: str = Field(min_length=1, max_length=8000)
    wait_for: str = "plan"


class _ObserveInput(BaseModel):
    agent_name: str = Field(min_length=1, max_length=64)


class _ProceedInput(BaseModel):
    agent_name: str = Field(min_length=1, max_length=64)
    instructions: str | None = Field(default=None, max_length=8000)


class _ReviseInput(BaseModel):
    agent_name: str = Field(min_length=1, max_length=64)
    instructions: str | None = Field(default=None, max_length=8000)
    new_todos: list[dict[str, Any]] | None = None


class _FinishAgentInput(BaseModel):
    agent_name: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class _AssertGoalCoverageInput(BaseModel):
    criteria: str = Field(min_length=1, max_length=4000)
    confident: bool


class _PublishFinalReportInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


# ---------------------------------------------------------------------------
# Sentinel: returned by publish_final_report so the runner knows to terminate
# ---------------------------------------------------------------------------
# The tool executor returns this dict; the runner checks for it and
# breaks out of the coordinator loop, emitting coordinator.done +
# scenario.done status="ok" with the text.  Using a special key
# (``__terminate__``) keeps the dispatch table homogeneous with the
# other tools (still returns a dict).
TERMINATE_SENTINEL = "__terminate__"


# ---------------------------------------------------------------------------
# Sync executors
# ---------------------------------------------------------------------------
def execute_observe_tool(agent_name: str, raw_input: dict[str, Any]) -> dict[str, Any]:
    """Snapshot the agent's runtime state."""
    try:
        parsed = _ObserveInput.model_validate(raw_input)
    except ValidationError as e:
        return {"output": f"observe() validation error: {e}", "is_error": True}

    state = get_agent_state(parsed.agent_name)
    payload = {
        "name": state.name,
        "plan_returned": state.plan_returned,
        "plan_rev": state.plan_rev,
        "todos": [t.model_dump() for t in state.todos],
        "archived_revs": len(state.archived_todos),
        "is_finished": state.is_finished,
        "finish_reason": state.finish_reason,
        "paused": state.paused,
        "stop_requested": state.stop_requested,
    }
    import json
    return {"output": json.dumps(payload, ensure_ascii=False, default=str), "is_error": False}


def execute_finish_agent_tool(agent_name: str, raw_input: dict[str, Any]) -> dict[str, Any]:
    """Set state.stop_requested=True.  The specialist wraps up on its
    next turn boundary (checked at the start of every turn)."""
    try:
        parsed = _FinishAgentInput.model_validate(raw_input)
    except ValidationError as e:
        return {"output": f"finish_agent() validation error: {e}", "is_error": True}

    state = get_agent_state(parsed.agent_name)
    if state.is_finished:
        return {
            "output": (
                f"finish_agent() noop: {parsed.agent_name} already finished "
                f"(reason={state.finish_reason!r})"
            ),
            "is_error": False,
        }
    state.stop_requested = True
    touch(state)
    return {
        "output": (
            f"finish_agent() ok: stop flag set for {parsed.agent_name} "
            f"(reason={parsed.reason!r}); specialist will exit at next turn boundary"
        ),
        "is_error": False,
    }


def execute_assert_goal_coverage_tool(
    agent_name: str, raw_input: dict[str, Any]
) -> dict[str, Any]:
    """Self-check tool.  Returns a confirmation prompt for the LLM.

    Note: ``agent_name`` here is the COORDINATOR's name, not a
    specialist — we don't need a specialist for this tool, the
    runner passes the coordinator's name through.  The function
    doesn't use it; it's kept in the signature for dispatch-table
    symmetry.
    """
    try:
        parsed = _AssertGoalCoverageInput.model_validate(raw_input)
    except ValidationError as e:
        return {"output": f"assert_goal_coverage() validation error: {e}", "is_error": True}

    if parsed.confident:
        msg = (
            f"assert_goal_coverage(ok): you confirmed confident=true for "
            f"criteria={parsed.criteria!r}. The system prompt instructs: "
            f"your next action must be publish_final_report(text). "
            f"Do not dispatch more work after this confirmation."
        )
    else:
        msg = (
            f"assert_goal_coverage(continue): confident=false for "
            f"criteria={parsed.criteria!r}. Continue with "
            f"dispatch/observe/proceed/revise as appropriate. "
            f"Re-assert when you believe the goal is met."
        )
    return {"output": msg, "is_error": False}


def execute_publish_final_report_tool(
    agent_name: str, raw_input: dict[str, Any]
) -> dict[str, Any]:
    """Store the final report and signal the runner to terminate.

    The runner checks for the TERMINATE_SENTINEL key in the returned
    dict and breaks the coordinator loop, emitting coordinator.done +
    scenario.done.  See run_coordinator_scenario in scenario_runner.
    """
    try:
        parsed = _PublishFinalReportInput.model_validate(raw_input)
    except ValidationError as e:
        return {"output": f"publish_final_report() validation error: {e}", "is_error": True}

    return {
        "output": "publish_final_report() accepted: scenario will end after this turn",
        "is_error": False,
        TERMINATE_SENTINEL: True,
        "final_report_text": parsed.text,
    }


# ---------------------------------------------------------------------------
# Async executors (drive a specialist)
# ---------------------------------------------------------------------------
# These three need a richer context than the sync ones: they consume
# the run_agent_turn async generator, forward its events to a queue
# (for the WS), and return a summary.  We pass the context as kwargs
# (rather than a dataclass) so callers don't need to construct an
# object — and so the smoke test can pass lightweight test doubles.
#
# Required kwargs (all async executors):
#   agent_obj       — the specialist Agent object (loaded from agents_io)
#   histories       — shared dict[str, list[dict]] of per-agent history
#   cancel          — asyncio.Event for cooperative cancellation
#   queue           — asyncio.Queue to forward specialist events to WS
#
# The async executors also have access to the runner's main
# ``run_agent_turn`` via the parameter ``runner_run_agent_turn`` —
# we pass it in (rather than importing scenario_runner at module
# load time) to avoid a circular import.

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from . import scenario_runner as _sr  # type: ignore
    from .agents_io import Agent  # type: ignore


async def _run_specialist_to_event(
    *,
    agent,
    task: str,
    wait_for: str,
    histories: dict[str, list[dict]],
    cancel: asyncio.Event,
    queue: asyncio.Queue,
    runner_run_agent_turn: Callable[..., Any],
) -> dict[str, Any]:
    """Shared helper for dispatch / proceed / revise.

    Appends the task to the specialist's history, then runs the
    specialist loop in the appropriate mode, forwarding events to
    ``queue`` and accumulating a summary.

    Returns a dict shaped for the coordinator's LLM tool result:
        {
          "output":  "<human-readable summary>",
          "is_error": False,
          # extra structured fields (read by run_coordinator_scenario):
          "status":       "paused" | "done" | "error",
          "plan_rev":     int,
          "todos":        [TodoStep, ...],
          "final_text":   str,
          "step_count":   int,
          "error":        str | None,
        }
    """
    import json
    name = agent.name
    history = histories.setdefault(name, [])

    # Append the task as a user message
    history.append({"role": "user", "content": task})

    # Reset pause flag so the LLM doesn't think it's mid-execution
    state = get_agent_state(name)
    state.paused = False
    state.stop_requested = False
    touch(state)

    # Choose mode: dispatch + wait_for=plan uses pause; wait_for=done
    # lets the specialist run to completion.  proceed / revise use
    # classic (continue from current state).
    if wait_for == "plan":
        mode = "plan_first_pause"
    elif wait_for == "done":
        mode = "plan_first"
    else:
        mode = "classic"

    text_chunks: list[str] = []
    tool_call_count = 0
    plan_rev_seen = state.plan_rev
    final_status = "done"
    error_detail: str | None = None
    finished_normally = False

    try:
        async for ev in runner_run_agent_turn(
            agent,
            task,                         # request (also appended to history above)
            history=history,
            cancel=cancel,
            mode=mode,
        ):
            if ev["kind"] == "text":
                text_chunks.append(ev["delta"])
                await queue.put({
                    "type": "specialist.token",
                    "name": name,
                    "delta": ev["delta"],
                    "ts": time.time(),
                })
            elif ev["kind"] == "tool_call":
                tool_call_count += 1
                await queue.put({
                    "type": "specialist.tool_call",
                    "name": name,
                    "tool_id": ev["id"],
                    "tool_name": ev["name"],
                    "tool_input": ev["input"],
                    "ts": time.time(),
                })
            elif ev["kind"] == "tool_result":
                await queue.put({
                    "type": "specialist.tool_result",
                    "name": name,
                    "tool_id": ev["id"],
                    "tool_name": ev["name"],
                    "output": ev["output"],
                    "is_error": ev["is_error"],
                    "ts": time.time(),
                })
            elif ev["kind"] == "plan_return":
                plan_rev_seen = ev["rev"]
                await queue.put({
                    "type": "specialist.plan_return",
                    "name": name,
                    "rev": ev["rev"],
                    "todos": ev["todos"],
                    "ts": time.time(),
                })
            elif ev["kind"] == "step_status":
                await queue.put({
                    "type": "specialist.step_status",
                    "name": name,
                    "step_id": ev["step_id"],
                    "status": ev["status"],
                    "result": ev.get("result"),
                    "error": ev.get("error"),
                    "ts": time.time(),
                })
            elif ev["kind"] == "agent_done":
                finished_normally = True
                break
            elif ev["kind"] == "agent_error":
                error_detail = ev["detail"]
                final_status = "error"
                await queue.put({
                    "type": "specialist.error",
                    "name": name,
                    "detail": ev["detail"],
                    "ts": time.time(),
                })
                break
    except asyncio.CancelledError:
        error_detail = "cancelled"
        final_status = "error"
    except Exception as e:
        error_detail = f"{type(e).__name__}: {e}"
        final_status = "error"

    # Re-snapshot state to read the latest plan_rev + todos
    state = get_agent_state(name)
    final_text = "".join(text_chunks)
    todos_dump = [t.model_dump() for t in state.todos]
    summary = {
        "status": final_status,
        "plan_rev": state.plan_rev,
        "todos": todos_dump,
        "final_text": final_text,
        "step_count": tool_call_count,
        "error": error_detail,
    }
    if error_detail and not finished_normally:
        # Specialist errored out (timeout / cancelled / plan_required) — surface
        summary["status"] = "error"

    if final_status == "done" and wait_for == "plan":
        # specialist stopped at the pause boundary
        summary["status"] = "paused"

    human = (
        f"{name} status={summary['status']} plan_rev={summary['plan_rev']} "
        f"todos={len(summary['todos'])} tool_calls={summary['step_count']} "
        f"chars={len(final_text)}"
    )
    if error_detail:
        human += f" error={error_detail!r}"
    if final_text and wait_for == "done":
        # Show a preview so the coordinator's LLM sees the gist
        preview = final_text[:300].replace("\n", " ")
        human += f"\n\nfinal_text_preview:\n{preview}"
        if len(final_text) > 300:
            human += f"\n...(truncated, full text in summary)"
    return {
        "output": human,
        "is_error": final_status == "error",
        # structured fields the coordinator LLM can read:
        "summary": summary,
    }


async def execute_dispatch_tool(
    agent_name: str,
    raw_input: dict[str, Any],
    *,
    agent_obj,                       # specialist Agent
    histories: dict[str, list[dict]],
    cancel: asyncio.Event,
    queue: asyncio.Queue,
    runner_run_agent_turn,
) -> dict[str, Any]:
    """Send a task to a specialist and run to the requested boundary."""
    try:
        parsed = _DispatchInput.model_validate(raw_input)
    except ValidationError as e:
        return {"output": f"dispatch() validation error: {e}", "is_error": True}

    # Validate specialist exists
    if parsed.agent_name != agent_obj.name:
        return {
            "output": (
                f"dispatch() error: agent_name mismatch "
                f"(tool arg={parsed.agent_name!r} != specialist={agent_obj.name!r})"
            ),
            "is_error": True,
        }

    return await _run_specialist_to_event(
        agent=agent_obj,
        task=parsed.task,
        wait_for=parsed.wait_for,
        histories=histories,
        cancel=cancel,
        queue=queue,
        runner_run_agent_turn=runner_run_agent_turn,
    )


async def execute_proceed_tool(
    agent_name: str,
    raw_input: dict[str, Any],
    *,
    agent_obj,
    histories: dict[str, list[dict]],
    cancel: asyncio.Event,
    queue: asyncio.Queue,
    runner_run_agent_turn,
) -> dict[str, Any]:
    """Resume a paused specialist.  Runs to completion (or stop)."""
    try:
        parsed = _ProceedInput.model_validate(raw_input)
    except ValidationError as e:
        return {"output": f"proceed() validation error: {e}", "is_error": True}

    state = get_agent_state(parsed.agent_name)
    if not state.paused:
        return {
            "output": (
                f"proceed() note: {parsed.agent_name} is not in paused state "
                f"(plan_returned={state.plan_returned}); continuing anyway"
            ),
            "is_error": False,
        }

    task = (parsed.instructions or "").strip() or "请按 plan 继续执行。"
    return await _run_specialist_to_event(
        agent=agent_obj,
        task=task,
        wait_for="done",
        histories=histories,
        cancel=cancel,
        queue=queue,
        runner_run_agent_turn=runner_run_agent_turn,
    )


async def execute_revise_tool(
    agent_name: str,
    raw_input: dict[str, Any],
    *,
    agent_obj,
    histories: dict[str, list[dict]],
    cancel: asyncio.Event,
    queue: asyncio.Queue,
    runner_run_agent_turn,
) -> dict[str, Any]:
    """Mid-flight: apply new_todos (if any) and continue.  Or just send
    a tweak instruction if only instructions are given."""
    try:
        parsed = _ReviseInput.model_validate(raw_input)
    except ValidationError as e:
        return {"output": f"revise() validation error: {e}", "is_error": True}

    if parsed.new_todos:
        # Directly apply the new plan: archive old, set new.
        # This is the same path execute_plan_tool uses, so the
        # state machine and Pydantic validation are consistent.
        from .agent_tools import execute_plan_tool
        result = execute_plan_tool(parsed.agent_name, {"todos": parsed.new_todos})
        if result["is_error"]:
            return {
                "output": f"revise() plan-apply failed: {result['output']}",
                "is_error": True,
            }
    task = (parsed.instructions or "").strip() or (
        "你的计划已更新，请按新 plan 继续执行。" if parsed.new_todos
        else "请在原 plan 基础上调整，并继续执行。"
    )
    return await _run_specialist_to_event(
        agent=agent_obj,
        task=task,
        wait_for="done",
        histories=histories,
        cancel=cancel,
        queue=queue,
        runner_run_agent_turn=runner_run_agent_turn,
    )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------
# The runner imports this and dispatches by tool name.  Async executors
# (dispatch, proceed, revise) are awaited; sync ones are called directly.
COORDINATOR_TOOL_EXECUTORS: dict[str, Callable[..., Awaitable[dict] | dict]] = {
    "dispatch":              execute_dispatch_tool,
    "observe":               execute_observe_tool,
    "proceed":               execute_proceed_tool,
    "revise":                execute_revise_tool,
    "finish_agent":          execute_finish_agent_tool,
    "assert_goal_coverage":  execute_assert_goal_coverage_tool,
    "publish_final_report":  execute_publish_final_report_tool,
}
