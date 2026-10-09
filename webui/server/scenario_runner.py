"""P3.4 + P5 + P6 + P7.A scenario runner.

Real multi-agent fan-out with a coordinator synthesis pass:

  1. Load the user's 4 specialists.
  2. Fan out the user request to all 4 in parallel — each streams its
     own domain response.
  3. After all 4 finish, run a 5th LLM call as the coordinator. It
     receives the 4 outputs (labeled by display_name) plus the original
     request, and produces a unified cross-domain report.
  4. The synthesis is streamed token-by-token to the client.

Event protocol (streamed to the client):

    scenario.start
        request, team
    specialist.start       (one per specialist)
        name, color, label
    specialist.token       (many)
        name, delta
    specialist.tool_call   (P6, zero or more per specialist)
        name, tool_id, tool_name, tool_input
    specialist.tool_result (P6, zero or more per specialist)
        name, tool_id, tool_name, output, is_error
    specialist.done        (one per specialist)
        name, text
    specialist.error       (zero or one per specialist)
        name, detail
    synthesis.start
    synthesis.token        (the coordinator's streamed output)
    synthesis.done
        text
    synthesis.error        (on failure)
    scenario.done          (terminal)
        status="ok" | "empty" | "cancelled" | "synthesis_error"
    scenario.error         (terminal, on global failure before any run starts)
        detail

P5 additions:
  - Per-specialist timeout (sliding per-token gap) → specialist.error
  - Per-synthesis timeout (sliding per-token gap) → synthesis.error
  - Cooperative cancel via cancel: asyncio.Event:
      * If cancel.is_set() between tokens, raise CancelledError inside run_one
      * The main event-drain loop checks cancel and cancels remaining tasks
      * Always emits `scenario.done status="cancelled"` before returning
  - `synthesis.error` now always emits a terminal `scenario.done
    status="synthesis_error"` (previously: silent return, no terminal)

P6 additions:
  - Generic `run_agent_turn(agent, request, history, cancel)` async generator
    that wraps `stream_chat_with_tools` with a multi-turn agent loop (Pydantic
    input validation → tool execute → tool_result → next turn). Yielded kinds:
        text / tool_call / tool_result / turn_done / agent_done / agent_error.
  - Module-level tool registry (lazy) backed by `create_default_tool_registry()`.
  - `run_one` now consumes `run_agent_turn` so specialists can call tools
    (e.g. SkillTool) and the tool_call/tool_result events are forwarded to
    the client.

P7.A additions:
  - `run_scenario` now accepts an optional `histories: dict[str, list[dict]]`
    parameter. When provided, each specialist's history list is taken from
    (or created in) this dict and passed to `run_agent_turn`, so the
    multi-turn conversation state is shared between `/ws/specialist` and
    `/ws/scenario` calls. When `histories` is None (default, e.g. in unit
    tests / smokes), behavior is identical to P6 (no history written).
  - `_truncate_history(histories, name)` keeps each agent's history list
    bounded so memory does not grow unbounded across long sessions.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator

from . import agents_io
from .agent_tools import PROTOCOL_TOOL_EXECUTORS, PROTOCOL_TOOL_SCHEMAS
from .coordinator_tools import (
    COORDINATOR_TOOL_EXECUTORS,
    COORDINATOR_TOOL_SCHEMAS,
    TERMINATE_SENTINEL,
)
from .llm import stream_chat, stream_chat_with_tools
from .team_types import get_agent_state, reset_team_state


def _now() -> float:
    return time.time()


# ---- P5: timeout constants ------------------------------------------------
# Per-token gap (sliding window). If the LLM goes silent for this long we
# assume the stream has stalled and abort with a `timeout` error.
# Override at runtime with env vars (used by smoke_p5_timeout.py to make
# tests run quickly).
SPECIALIST_TIMEOUT_S: float = float(os.environ.get("WEBUI_SPECIALIST_TIMEOUT_S", "120"))
SYNTHESIS_TIMEOUT_S: float = float(os.environ.get("WEBUI_SYNTHESIS_TIMEOUT_S", "180"))


# ---- P7.A: history constants ----------------------------------------------
# Upper bound on messages kept per agent in the shared `_specialist_history`
# dict. A "turn" is roughly 2 messages (user + assistant) but tool calls add
# 2 more per tool. We cap on raw message count to keep the math simple.
# 120 messages ≈ 20 turns with average tool use; trim the oldest half when
# exceeded. This prevents the in-process dict from growing without bound
# across long sessions.
MAX_HISTORY_MESSAGES_PER_AGENT: int = 120
TRUNCATE_TO_MESSAGES: int = 60


def _truncate_history(histories: dict[str, list[dict]], name: str) -> None:
    """Bound the size of one agent's history list. Mutates `histories[name]`
    in place. Called after each user message is appended by `run_agent_turn`.
    A no-op if the list is already small.
    """
    msgs = histories.get(name)
    if msgs is None or len(msgs) <= MAX_HISTORY_MESSAGES_PER_AGENT:
        return
    histories[name] = msgs[-TRUNCATE_TO_MESSAGES:]


# Used as the system prompt for a specialist if its .md body is empty.
# Should be rare; agents created via the UI always have a body.
_FALLBACK_SYSTEM = "你是 {name}，请用简洁的中文回答用户的问题。"


# P9 — injected when `mode="plan_first"`. The agent's .md body is
# domain-specific and doesn't know about the plan-first protocol, so
# the backend appends this block at LLM-call time. The text is
# deliberately blunt: the LLM has to call ``plan()`` as its very
# first action, before any other tool, before any text. Violation
# aborts the run (see run_agent_turn's plan-first check).
_PLAN_FIRST_PREFIX = """\

## Plan-First protocol (active for this run)

你的第一个动作必须是调用 `plan` 工具，发布一份 TODO 列表，每个 todo
代表一个原子执行步骤。

要求：
- 在调用 `plan` 之前，不要输出任何文本，不要调用任何其他工具。
- `plan` 接受 `todos` 数组，每个 todo 至少包含 `id` 和 `content`。
- plan 被接收后，你进入 EXECUTING 阶段，按顺序执行每个 step。
- 每开始一个 step，调 `update_todo(step_id, "running")`。
- 每完成一个 step，调 `update_todo(step_id, "done", result="...")` 汇报结果。
- 失败的 step 调 `update_todo(step_id, "failed", error="...")`。
- 整个运行期间，遵守你自己的 `plan` 内容，不要跳步也不要加未声明的步骤。
- 所有 step 完成后，输出最终总结文本即可。

违反此协议（不先 plan() 就直接调其他工具或出文本）会被立刻终止。
"""


# P10 — injected when `mode="coordinator"`. The coordinator is the LLM
# driver of a multi-agent run; the 7 internal tools in
# ``coordinator_tools.py`` are the only way it interacts with
# specialists. This block tells the LLM what each tool does and what
# the expected workflow is.
_COORDINATOR_PROTOCOL = """\

## Coordinator protocol (active for this run)

你是 MetaClaw 团队的协调者。你有 7 个内部工具来管理 specialists:

- `dispatch(agent_name, task, wait_for="plan"|"done")` 派发任务；返回 plan 或最终文本
- `observe(agent_name)` 查看 specialist 的状态和 todos
- `proceed(agent_name, instructions=...)` 让已 plan() 的 specialist 继续执行
- `revise(agent_name, instructions=..., new_todos=[...])` mid-flight 调整计划
- `finish_agent(agent_name, reason)` 让 specialist 早停
- `assert_goal_coverage(criteria, confident)` 自我检查目标是否达成
- `publish_final_report(text)` 终止，发布最终报告

工作流:
1. dispatch 至少一个 specialist（v1 串行：一次一个），等 plan() 返回
2. observe plan，必要时 revise
3. proceed，让 specialist 边执行边更新 todos
4. 重复 2-3 直到 specialist 结束或达到目标
5. assert_goal_coverage 显式确认（confident=true）
6. publish_final_report 结束

严格规则:
- 你的第一个动作必须是 dispatch 至少一个 specialist。直接调
  publish_final_report 不行。
- publish_final_report 之前必须先 assert_goal_coverage(criteria,
  confident=true)。系统会拒绝跳过 assert 就 publish。
- specialist 的 live 状态变更会通过 WS 推给 UI；你（LLM）只通过
  observe() 看 summary。proceed/revise 的返回里也带 todos 终态。
- 串行模式：一次 dispatch 一个 specialist，等它返回再 dispatch
  下一个。不要在同一次 dispatch 中假设并行。
"""


# P7.B + P9 + P10 — pure composition helper. Combines the agent's body with:
#   - optional `webui_qa_prompt` (set by the user via AgentEditor)
#   - optional plan-first prefix (set by the runner when mode=plan_first or
#     plan_first_pause)
#   - optional coordinator protocol prefix (set by the runner when the
#     coordinator agent runs in mode=coordinator)
#
# No hardcoded WebUI Q&A text lives here — that text is whatever the user
# saved in the agent's .md file. This function is pure string composition;
# it does NOT default-fill, it does NOT inject any "fallback" WebUI mode
# instructions. If `webui_qa_prompt` is empty, the agent gets only its
# body (or the framework fallback for an empty body).
def _effective_system_prompt(agent, mode: str = "classic") -> str:
    body = (agent.system_prompt_body or "").strip()
    base = body or _FALLBACK_SYSTEM.format(name=agent.name)
    qa = (getattr(agent, "webui_qa_prompt", "") or "").strip()
    if qa:
        base = base + "\n\n" + qa
    if mode in ("plan_first", "plan_first_pause"):
        base = base + _PLAN_FIRST_PREFIX
    elif mode == "coordinator":
        base = base + _COORDINATOR_PROTOCOL
    return base


# P3.4 — the coordinator's synthesis prompt. Receives the original user
# request plus the 4 specialist outputs (labeled by display_name) and
# produces a unified cross-domain report. The disclaimer is required
# because medical advice always goes through this path.
_SYNTHESIS_SYSTEM = """\
你是 MetaClaw 团队的协调者。你手下的 4 位领域专家刚完成了一次并发咨询，
现在需要你把他们的输出综合成一份统一的多域报告，供用户阅读。

要求:
- 用中文写一份统一的综合报告
- 每个领域用 ## 二级标题（标题用专家的中文显示名）
- 领域之间用 --- 分隔
- 不要简单堆砌专家原文 — 综合各方观点，删掉重复，给出统一的行动建议
- 在合适的地方引用专家的关键建议（用 **加粗** 强调）
- 末尾必须包含: > ⚠️ 医疗免责声明
- 总字数 800-1500 字
"""


# ---------------------------------------------------------------------------
# P5 helper: per-token-gap timeout wrapper
# ---------------------------------------------------------------------------
async def _stream_with_timeout(
    stream: AsyncIterator,
    timeout_s: float,
) -> AsyncIterator:
    """Yield items from `stream`, but raise asyncio.TimeoutError if the
    next item does not arrive within `timeout_s` seconds of the previous
    one (i.e., the LLM stream has stalled).

    Sliding window: each item has its own `timeout_s` deadline. A 2000-token
    response at 50ms/token is fine; an LLM that goes silent for `timeout_s`
    seconds triggers the timeout.

    Implementation: we wrap `stream.__anext__()` with `asyncio.wait_for`.
    `wait_for` cancels the inner coroutine on timeout, which is exactly
    what we want for an async generator — the next `__anext__` would have
    blocked forever anyway.
    """
    while True:
        try:
            item = await asyncio.wait_for(stream.__anext__(), timeout=timeout_s)
        except StopAsyncIteration:
            return
        yield item


# ---------------------------------------------------------------------------
# P6 helper: tool registry
# ---------------------------------------------------------------------------
# Lazy singleton. Created on first call. Survives across runs but resets on
# process restart (matches user expectation — server restart = clean slate).
_tool_registry = None


def _get_tool_registry():
    global _tool_registry
    if _tool_registry is None:
        from openharness.tools import create_default_tool_registry
        _tool_registry = create_default_tool_registry()
    return _tool_registry


def _find_tool(name: str):
    """Case-insensitive tool lookup against the registry, with aliases.

    Maps common frontmatter tool names ("Read", "Write", "Edit") to the
    actual registry names ("read_file", "write_file", "edit_file"). This
    matches the convention used by Anthropic-Claude's tool naming.
    """
    aliases = {
        "read": "read_file",
        "write": "write_file",
        "edit": "edit_file",
        "ls": "bash",
    }
    canonical = aliases.get(name.lower(), name.lower())
    registry = _get_tool_registry()
    if canonical in registry._tools:
        return registry._tools[canonical]
    # Fallback: scan
    for t in registry.list_tools():
        if t.name == canonical:
            return t
    return None


def _tools_for_agent(agent) -> list[dict[str, Any]]:
    """Build OpenAI-format tool schemas for an agent.

    Source: ``agent.tools`` frontmatter (e.g. ``["Bash", "Skill"]``) plus the
    ``skill`` tool if ``agent.skills`` is non-empty. Case-insensitive lookup
    against the OpenHarness tool registry. Tools not found are silently
    dropped (with a debug log) so a stale frontmatter reference does not
    break the whole agent.
    """
    names: set[str] = set()
    if agent.skills:
        names.add("skill")
    for n in (agent.tools or []):
        # Normalize to lowercase so "Skill" (from frontmatter) and
        # "skill" (auto-added from agent.skills) collapse into one entry.
        if isinstance(n, str):
            names.add(n.lower())

    schemas: list[dict[str, Any]] = []
    for name in sorted(names):
        tool = _find_tool(name)
        if tool is None:
            continue
        api = tool.to_api_schema()  # Anthropic format
        schemas.append({
            "type": "function",
            "function": {
                "name": api["name"],
                "description": api.get("description", ""),
                "parameters": api.get("input_schema", {}),
            },
        })

    # P9: append the plan-first protocol tools (plan + update_todo).
    # These are internal — they don't go through the OpenHarness registry.
    schemas.extend(PROTOCOL_TOOL_SCHEMAS)
    return schemas


async def _execute_tool(agent, name: str, tool_input: dict) -> dict:
    """Validate + execute a single tool call. Mirrors engine/query.py:_execute_tool_call.

    Returns ``{"output": str, "is_error": bool}``. Never raises — errors
    become ``is_error=True`` tool results so the agent loop can continue.
    """
    # P9: protocol tools (plan, update_todo) are internal — dispatch to
    # their dedicated executors BEFORE consulting the OpenHarness registry.
    # These executors are synchronous and mutate AgentRuntimeState.
    proto = PROTOCOL_TOOL_EXECUTORS.get(name)
    if proto is not None:
        return proto(agent.name, tool_input)

    from openharness.tools.base import ToolExecutionContext

    tool = _find_tool(name)
    if tool is None:
        return {"output": f"tool not found: {name}", "is_error": True}
    try:
        parsed = tool.input_model.model_validate(tool_input)
    except Exception as e:
        return {"output": f"invalid input for {name}: {e}", "is_error": True}
    ctx = ToolExecutionContext(cwd=Path.cwd(), metadata={"agent_name": agent.name})
    try:
        result = await tool.execute(parsed, ctx)
        return {"output": result.output, "is_error": result.is_error}
    except Exception as e:
        return {"output": f"tool {name} raised: {type(e).__name__}: {e}", "is_error": True}


# ---------------------------------------------------------------------------
# P6: generic agent loop
# ---------------------------------------------------------------------------
async def run_agent_turn(
    agent,
    request: str,
    *,
    history: list[dict] | None = None,
    cancel: asyncio.Event | None = None,
    mode: str = "classic",
) -> AsyncIterator[dict]:
    """One multi-turn agent loop for a single specialist.

    Wraps ``stream_chat_with_tools`` with:
      - system prompt prepend
      - max_turns loop (default = ``agent.max_turns`` or 10)
      - Pydantic-validated tool execution via ``_execute_tool``
      - cooperative cancel + sliding per-token timeout

    ``history`` is mutated in place — new user/assistant/tool messages are
    appended so the caller (e.g. the per-specialist endpoint) can reuse the
    same list across requests to build a multi-turn conversation.

    ``mode`` (P9 + P10):
      - "classic"           — default; specialist may or may not call plan().
      - "plan_first"        — the first LLM turn MUST call the ``plan`` tool.
                             If the first turn finishes without ``plan()`` being
                             called (either no tool calls at all, or only other
                             tools), the loop yields ``agent_error("plan_required: ...")``
                             and returns. After plan() succeeds the loop
                             continues — the LLM is expected to call
                             update_todo and execute.
      - "plan_first_pause"  — P10: same plan-first enforcement, but after
                             plan() returns the loop yields ``agent_done``
                             and stops, with ``state.paused=True``. The
                             coordinator's ``proceed``/``revise`` tools
                             re-invoke run_agent_turn with mode="classic"
                             to continue execution.

    Yields (in order, mixed):
        {"kind": "text",         "delta": str}                 (zero or more per turn)
        {"kind": "tool_call",    "id", "name", "input"}        (one per tool call, after tool execution)
        {"kind": "tool_result",  "id", "name", "output", "is_error"}  (one per tool call)
        {"kind": "plan_return",  "todos", "rev"}               (P9; after a successful plan() call)
        {"kind": "step_status",  "step_id", "status", "result", "error"}  (P9; after update_todo())
        {"kind": "turn_done",    "assistant_text", "tool_calls_made"}  (one per turn)
        {"kind": "agent_done"}                                  (terminal)
        {"kind": "agent_error",  "detail"}                      (terminal)

    Yield order per turn:
        1. text deltas (text streamed in real time)
        2. turn_done (after streaming completes; reports tool_calls_made)
        3. tool_call + tool_result (if the turn had tool calls, executed
           sequentially after the stream ends)
        4. plan_return / step_status (P9 protocol side-events, fire
           AFTER the corresponding tool_result, before the next turn)
        5. turn_done (signals end of post-tool turn, before next LLM call)

    Either ``agent_done`` or ``agent_error`` is the terminal event. The
    function then returns.
    """
    sys_prompt = _effective_system_prompt(agent, mode=mode)

    # Build the LLM call messages: system first, then any prior history,
    # then the new user request. This keeps the system prompt at index 0
    # even when the conversation has prior turns.
    user_msg: dict[str, Any] = {"role": "user", "content": request}
    messages: list[dict] = [{"role": "system", "content": sys_prompt}]
    if history:
        messages.extend(history)
    messages.append(user_msg)

    # Mutate history in place so the caller (e.g. /ws/specialist) sees the
    # new turn on subsequent calls. We do NOT add the system prompt to
    # history — it's re-derived on every call from agent.system_prompt_body.
    if history is not None:
        history.append(user_msg)

    tools_schema = _tools_for_agent(agent)
    max_turns = max(1, agent.max_turns or 10)

    for _turn_idx in range(max_turns):
        # P10: cooperative stop check.  The coordinator's `finish_agent`
        # tool sets ``state.stop_requested=True``; we check at the start
        # of every turn (between LLM yields) and exit with a one-line
        # ack.  We do NOT cancel an in-flight LLM stream — the next turn
        # boundary will see the flag and exit cleanly.  This keeps the
        # state machine atomic (no half-mutation).
        _state = get_agent_state(agent.name)
        if _state.stop_requested:
            _state.is_finished = True
            _state.finish_reason = _state.finish_reason or "stop_requested"
            yield {"kind": "text", "delta": f"[已收到 finish_agent 指令，停止执行]"}
            yield {"kind": "agent_done"}
            return

        text_chunks: list[str] = []
        tool_calls: dict[str, dict] = {}  # keyed by tool_call id
        try:
            token_stream = stream_chat_with_tools(
                messages,
                tools=tools_schema or None,
            )
            async for ev in _stream_with_timeout(token_stream, SPECIALIST_TIMEOUT_S):
                if cancel and cancel.is_set():
                    raise asyncio.CancelledError
                if ev["kind"] == "text":
                    text_chunks.append(ev["delta"])
                    yield {"kind": "text", "delta": ev["delta"]}
                elif ev["kind"] == "tool_call":
                    tool_calls[ev["id"]] = ev
                # finish / usage are intentionally ignored
        except asyncio.CancelledError:
            get_agent_state(agent.name).is_finished = True
            get_agent_state(agent.name).finish_reason = "cancelled"
            yield {"kind": "agent_error", "detail": "cancelled"}
            return
        except asyncio.TimeoutError:
            get_agent_state(agent.name).is_finished = True
            get_agent_state(agent.name).finish_reason = "timeout"
            yield {"kind": "agent_error", "detail": f"timeout ({SPECIALIST_TIMEOUT_S}s, no token)"}
            return
        except Exception as e:
            get_agent_state(agent.name).is_finished = True
            get_agent_state(agent.name).finish_reason = f"error: {type(e).__name__}"
            yield {"kind": "agent_error", "detail": f"{type(e).__name__}: {e}"}
            return

        assistant_text = "".join(text_chunks)

        # Append the assistant message (with tool_calls if any) to the
        # running conversation. OpenAI requires tool_calls to be ordered
        # by id, so we iterate in insertion order from our dict.
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_text or None,
        }
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["input"]),
                    },
                }
                for tc in tool_calls.values()
            ]
        messages.append(assistant_msg)
        if history is not None:
            history.append(assistant_msg)

        # No tool calls → model is done, return
        if not tool_calls:
            # P9 + P10: in plan_first / plan_first_pause mode, a first
            # turn with no tool calls at all means the agent never
            # called plan() — abort with a clear error.
            if mode in ("plan_first", "plan_first_pause") and _turn_idx == 0 \
                    and not get_agent_state(agent.name).plan_returned:
                yield {
                    "kind": "agent_error",
                    "detail": "plan_required: first turn had no tool calls; plan() must be the first action",
                }
                get_agent_state(agent.name).is_finished = True
                get_agent_state(agent.name).finish_reason = "plan_required"
                return
            yield {"kind": "turn_done", "assistant_text": assistant_text, "tool_calls_made": 0}
            yield {"kind": "agent_done"}
            get_agent_state(agent.name).is_finished = True
            get_agent_state(agent.name).finish_reason = "ok"
            return

        # Execute each tool call sequentially. The SkillTool and most
        # built-in tools are read-only and fast, so concurrency is not
        # needed. Errors are returned as tool_result is_error=True so the
        # LLM can see them in the next turn.
        for tc in tool_calls.values():
            yield {"kind": "tool_call", "id": tc["id"], "name": tc["name"], "input": tc["input"]}
            result = await _execute_tool(agent, tc["name"], tc["input"])
            yield {
                "kind": "tool_result",
                "id": tc["id"],
                "name": tc["name"],
                "output": result["output"],
                "is_error": result["is_error"],
            }
            tool_msg = {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result["output"],
            }
            messages.append(tool_msg)
            if history is not None:
                history.append(tool_msg)

            # P9: emit protocol side-events AFTER the tool_result so the
            # UI sees a stable ordering: tool_call → tool_result →
            # plan_return / step_status. The state is already mutated by
            # the executor (atomic), so we just snapshot and yield.
            # We only emit when the call SUCCEEDED — a rejected
            # update_todo (illegal transition) didn't change state, so
            # there's no new status to report.
            if tc["name"] == "plan" and not result["is_error"]:
                state = get_agent_state(agent.name)
                yield {
                    "kind": "plan_return",
                    "rev": state.plan_rev,
                    "todos": [t.model_dump() for t in state.todos],
                }
            elif tc["name"] == "update_todo" and not result["is_error"]:
                step_id = (tc["input"] or {}).get("step_id", "")
                state = get_agent_state(agent.name)
                step = next((s for s in state.todos if s.id == step_id), None)
                if step is not None:
                    yield {
                        "kind": "step_status",
                        "step_id": step.id,
                        "status": step.status,
                        "result": step.result,
                        "error": step.error,
                    }

        # P10: in plan_first_pause mode, after plan() has succeeded we
        # stop here and wait for the coordinator to call proceed/revise.
        # ``state.paused`` is the flag the coordinator reads via
        # observe(); clearing it is the runner's job when re-invoked.
        _state = get_agent_state(agent.name)
        if mode == "plan_first_pause" and _state.plan_returned:
            _state.paused = True
            _state.is_finished = False  # not done — the coordinator may still proceed
            yield {"kind": "turn_done", "assistant_text": assistant_text, "tool_calls_made": len(tool_calls)}
            yield {"kind": "agent_done"}
            return

        # P9 + P10: after the first turn's tools have been executed, in
        # plan_first / plan_first_pause mode the agent must have called
        # plan() by now. If it called *other* tools but not plan(),
        # reject with a clear error so the caller can show "agent did
        # not follow plan-first protocol".
        if mode in ("plan_first", "plan_first_pause") and _turn_idx == 0 \
                and not get_agent_state(agent.name).plan_returned:
            yield {
                "kind": "agent_error",
                "detail": "plan_required: first turn did not call plan()",
            }
            get_agent_state(agent.name).is_finished = True
            get_agent_state(agent.name).finish_reason = "plan_required"
            return

        yield {"kind": "turn_done", "assistant_text": assistant_text, "tool_calls_made": len(tool_calls)}
        # Loop → LLM sees tool_results, decides whether to call more tools or answer

    # Out of turns — yield error and return
    get_agent_state(agent.name).is_finished = True
    get_agent_state(agent.name).finish_reason = f"max_turns={max_turns} reached"
    yield {"kind": "agent_error", "detail": f"max_turns={max_turns} reached"}
    return


async def run_scenario(
    user_request: str,
    *,
    team: str = "webui-scenario",
    model: str | None = None,
    cancel: asyncio.Event | None = None,
    histories: dict[str, list[dict]] | None = None,
    mode: str = "classic",
) -> AsyncIterator[dict]:
    """Stream events as 4 specialists process the request in parallel.

    Args:
        user_request: the user's natural-language request
        team: identifier used in scenario.start event (for logging)
        model: optional LLM model override
        cancel: if provided, the runner cooperates with this event:
            - yields are aborted when `cancel.is_set()`
            - in-flight LLM tasks are cancelled
            - a final `scenario.done status="cancelled"` is emitted
        histories: P7.A — optional shared per-agent conversation history.
            When provided, each specialist's list (keyed by ``agent.name``)
            is passed to ``run_agent_turn`` as the in-place history buffer,
            so the same list is read AND mutated during the call. The
            caller (typically ``app.py::scenario_ws``) owns this dict and
            keeps it as the single source of truth across modes. When
            ``histories`` is None (default, e.g. in unit tests / smoke
            tests), behavior is identical to P6 — no history is written.
        mode: P9 — "classic" (default, P5/P6/P7 compatible) or
            "plan_first" (specialists must call plan() before executing;
            see ``run_agent_turn``). The P9 protocol side-events
            ``plan_return`` and ``step_status`` are forwarded as
            ``specialist.plan_return`` and ``specialist.step_status``
            WS events so the UI can render TODO boards.

    Yields dicts with a `type` field. Each event also has a `ts` timestamp.
    """
    if cancel is None:
        cancel = asyncio.Event()
    if histories is None:
        # P7.A: default to an ephemeral dict so run_one can call
        # `histories.setdefault(...)` unconditionally. The dict is
        # dropped when the runner returns, so its contents never leak
        # anywhere when the caller doesn't want shared state.
        histories = {}

    def _is_cancelled() -> bool:
        return cancel.is_set()

    # ---- Load the 4 user specialists ---------------------------------------
    all_agents = agents_io.list_agents()
    specialists = [a for a in all_agents if a.role != "coordinator"]

    yield {
        "type": "scenario.start",
        "request": user_request,
        "team": team,
        "ts": _now(),
        "specialist_count": len(specialists),
    }

    if _is_cancelled():
        yield {"type": "scenario.done", "status": "cancelled", "ts": _now()}
        return

    if not specialists:
        # No specialists configured — emit a graceful scenario.error
        yield {
            "type": "scenario.error",
            "detail": "no user-defined specialists found in ~/.openharness/agents/",
            "ts": _now(),
        }
        return

    # ---- Run all specialists in parallel ------------------------------------
    # Each task puts its events into a shared queue. We yield them out
    # both *during* the run (so the UI sees live progress) and after
    # gather (to catch any events that arrived between the last drain
    # and the gather return).
    queue: asyncio.Queue = asyncio.Queue()
    results: dict[str, str] = {}

    async def run_one(agent) -> None:
        # Reset & announce start
        await queue.put({
            "type": "specialist.start",
            "name": agent.name,
            "color": agent.color,
            "label": agent.description or agent.name,
            "ts": _now(),
        })
        chunks: list[str] = []
        # P7.A: pull (or create) this agent's history list from the shared
        # `histories` dict. `run_agent_turn` mutates this list in place —
        # subsequent /ws/specialist OR /ws/scenario calls against the same
        # agent will see the conversation continue. The default ephemeral
        # dict created in `run_scenario` still satisfies this when the
        # caller didn't pass anything (P6-compatible behavior).
        history = histories.setdefault(agent.name, [])
        # P6: consume the generic agent loop instead of stream_chat directly.
        # This routes tool_call / tool_result events from the agent into the
        # specialist.tool_call / specialist.tool_result WS events so the UI
        # can show the "思考过程" region in the specialist tab.
        try:
            async for ev in run_agent_turn(
                agent,
                user_request,
                history=history,
                cancel=cancel,
                mode=mode,
            ):
                if ev["kind"] == "text":
                    chunks.append(ev["delta"])
                    await queue.put({
                        "type": "specialist.token",
                        "name": agent.name,
                        "delta": ev["delta"],
                        "ts": _now(),
                    })
                elif ev["kind"] == "tool_call":
                    await queue.put({
                        "type": "specialist.tool_call",
                        "name": agent.name,
                        "tool_id": ev["id"],
                        "tool_name": ev["name"],
                        "tool_input": ev["input"],
                        "ts": _now(),
                    })
                elif ev["kind"] == "tool_result":
                    await queue.put({
                        "type": "specialist.tool_result",
                        "name": agent.name,
                        "tool_id": ev["id"],
                        "tool_name": ev["name"],
                        "output": ev["output"],
                        "is_error": ev["is_error"],
                        "ts": _now(),
                    })
                elif ev["kind"] == "turn_done":
                    pass
                # P9: forward the plan-first protocol side-events to the UI
                elif ev["kind"] == "plan_return":
                    await queue.put({
                        "type": "specialist.plan_return",
                        "name": agent.name,
                        "rev": ev["rev"],
                        "todos": ev["todos"],
                        "ts": _now(),
                    })
                elif ev["kind"] == "step_status":
                    await queue.put({
                        "type": "specialist.step_status",
                        "name": agent.name,
                        "step_id": ev["step_id"],
                        "status": ev["status"],
                        "result": ev.get("result"),
                        "error": ev.get("error"),
                        "ts": _now(),
                    })
                elif ev["kind"] == "agent_done":
                    break
                elif ev["kind"] == "agent_error":
                    raise RuntimeError(ev["detail"])
        except asyncio.CancelledError:
            await queue.put({
                "type": "specialist.error",
                "name": agent.name,
                "detail": "cancelled",
                "ts": _now(),
            })
            return
        except asyncio.TimeoutError:
            # P5: per-token-gap timeout from the inner stream_chat_with_tools
            await queue.put({
                "type": "specialist.error",
                "name": agent.name,
                "detail": f"timeout ({SPECIALIST_TIMEOUT_S}s, no token)",
                "ts": _now(),
            })
            return
        except Exception as e:
            await queue.put({
                "type": "specialist.error",
                "name": agent.name,
                "detail": f"{type(e).__name__}: {e}",
                "ts": _now(),
            })
            return

        full = "".join(chunks)
        results[agent.name] = full
        # P7.A: bound the per-agent history so a long session doesn't
        # blow up memory. Safe to call after the agent loop has fully
        # completed (no race with concurrent appends — each agent has
        # exactly one task running at a time).
        _truncate_history(histories, agent.name)
        await queue.put({
            "type": "specialist.done",
            "name": agent.name,
            "text": full,
            "ts": _now(),
        })

    tasks = [asyncio.create_task(run_one(a)) for a in specialists]

    # Stream events from the queue as they arrive, until every task is done.
    pending = set(tasks)
    while pending:
        # Bail early if cancelled: cancel all in-flight tasks, drain queue,
        # emit terminal.
        if _is_cancelled():
            for t in pending:
                t.cancel()
            # Wait for cancellations to settle (with a small grace).
            await asyncio.gather(*pending, return_exceptions=True)
            # Drain any remaining queue items (the run_one CancelledError
            # handlers will have queued specialist.error events).
            while True:
                try:
                    yield queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            yield {"type": "scenario.done", "status": "cancelled", "ts": _now()}
            return

        # Wait for either: a queue event, or any task finishing.
        get_task = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait(
            pending | {get_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if get_task in done:
            yield get_task.result()
            continue
        # A specialist finished (or errored). Drain whatever it queued.
        get_task.cancel()
        while True:
            try:
                yield queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        # Re-evaluate the pending set.
        pending = {t for t in pending if not t.done()}

    # ---- Synthesis (P3.4: real coordinator LLM call) -----------------------
    # After all 4 specialists return, the coordinator (a 5th LLM call) reads
    # their outputs and produces a unified, deduplicated, cross-referenced
    # final report that references each domain. This is a true streaming
    # call — every token is forwarded as a synthesis.token event so the UI
    # can render the report live.

    if _is_cancelled():
        yield {"type": "scenario.done", "status": "cancelled", "ts": _now()}
        return

    yield {"type": "synthesis.start", "ts": _now()}

    # Skip synthesis if no specialist produced any output.
    if not any(results.get(a.name, "").strip() for a in specialists):
        yield {
            "type": "synthesis.error",
            "detail": "all 4 specialists returned empty",
            "ts": _now(),
        }
        # P5: always emit a terminal scenario.done, even on synthesis error.
        yield {"type": "scenario.done", "status": "synthesis_error", "ts": _now()}
        return

    # Build the synthesis user message: the original request + each
    # specialist's output, labeled by display_name so the coordinator can
    # reference them naturally.
    parts: list[str] = [f"用户请求: {user_request}", "", "---", ""]
    for agent in specialists:
        text = results.get(agent.name, "").strip()
        if not text:
            continue
        label = (agent.display_name or agent.name).strip()
        parts.append(f"## {label}")
        parts.append("")
        parts.append(text)
        parts.append("")
        parts.append("---")
        parts.append("")
    synth_user = "\n".join(parts)

    chunks: list[str] = []
    synthesis_failed: str | None = None
    try:
        token_stream = stream_chat(
            messages=[
                {"role": "system", "content": _SYNTHESIS_SYSTEM},
                {"role": "user",   "content": synth_user},
            ],
            model=model,
        )
        async for token in _stream_with_timeout(token_stream, SYNTHESIS_TIMEOUT_S):
            if _is_cancelled():
                raise asyncio.CancelledError
            chunks.append(token)
            yield {
                "type": "synthesis.token",
                "delta": token,
                "ts": _now(),
            }
    except asyncio.CancelledError:
        synthesis_failed = "cancelled"
    except asyncio.TimeoutError:
        synthesis_failed = f"timeout ({SYNTHESIS_TIMEOUT_S}s, no token)"
    except Exception as e:
        synthesis_failed = f"{type(e).__name__}: {e}"

    if synthesis_failed is not None:
        yield {
            "type": "synthesis.error",
            "detail": synthesis_failed,
            "ts": _now(),
        }
        # P5: terminal event after synthesis error.
        yield {"type": "scenario.done", "status": "synthesis_error", "ts": _now()}
        return

    final_text = "".join(chunks)
    yield {
        "type": "synthesis.done",
        "text": final_text,
        "ts": _now(),
    }

    yield {"type": "scenario.done", "status": "ok", "ts": _now()}


# ---------------------------------------------------------------------------
# P10 — coordinator-driven scenario
# ---------------------------------------------------------------------------
# The coordinator (the agent with role="coordinator" in
# ~/.openharness/agents/) is the LLM driver.  It has 7 internal
# tools (see coordinator_tools.py) to dispatch/observe/proceed/revise
# specialists and ultimately call ``publish_final_report(text)`` to
# terminate the run.
#
# The coordinator's LLM loop is structurally similar to
# ``run_agent_turn`` (multi-turn streaming, max_turns, cancel) but the
# tool executor is different: specialist tools vs coordinator tools.
# We don't share code with ``run_agent_turn`` because:
#   - the coordinator's tools drive SYNCHRONOUSLY the specialist's
#     run_agent_turn (which is itself an async generator) — that's a
#     nested-generators pattern that doesn't fit run_agent_turn's
#     "one specialist per call" model.
#   - the coordinator's max_turns is much higher (60 by default — the
#     coordinator may do many dispatch+observe cycles).
#
# Event protocol (P10):
#     scenario.start
#         mode: "coordinator"        (distinguishes from P3.4 synthesis mode)
#     coordinator.start
#         name: <coordinator-agent-name>
#     coordinator.token           (LLM streaming)
#     coordinator.tool_call       (one per coordinator tool call)
#     coordinator.tool_result     (one per coordinator tool call)
#         — for dispatch/proceed/revise, specialist events are forwarded
#           via the queue between these two events, so the UI sees the
#           specialist's full run in between.
#     specialist.start, .token, .tool_call, .tool_result, .plan_return,
#     .step_status, .done, .error   (forwarded from inside the tool
#                                    executor; live from the LLM's POV)
#     coordinator.done             (after publish_final_report)
#         text: <final report>
#     coordinator.error            (on coordinator LLM failure)
#     scenario.done                (terminal; status="ok"|"cancelled"|"error"|"max_turns")

async def run_coordinator_scenario(
    user_request: str,
    *,
    team: str = "coordinator-scenario",
    model: str | None = None,
    cancel: asyncio.Event | None = None,
    histories: dict[str, list[dict]] | None = None,
) -> AsyncIterator[dict]:
    """Stream events as the coordinator drives the multi-agent run.

    Args:
        user_request: the user's natural-language request
        team: identifier used in scenario.start event
        model: optional LLM model override for the coordinator
        cancel: cooperative cancel event
        histories: P7.A — shared per-agent conversation history dict
            (same convention as run_scenario).  When the coordinator
            dispatches a specialist, the specialist's history list is
            taken from (or created in) this dict and mutated in place
            by run_agent_turn.

    Yields dicts with ``type`` and ``ts`` fields.
    """
    if cancel is None:
        cancel = asyncio.Event()
    if histories is None:
        histories = {}

    # ---- Load agents ---------------------------------------------------------
    all_agents = agents_io.list_agents()
    coordinator = next((a for a in all_agents if a.role == "coordinator"), None)
    if coordinator is None:
        yield {
            "type": "scenario.error",
            "detail": (
                "no coordinator agent found (role='coordinator' in "
                "~/.openharness/agents/)"
            ),
            "ts": _now(),
        }
        return
    specialists = [a for a in all_agents if a.role != "coordinator"]
    specialists_by_name = {a.name: a for a in specialists}

    yield {
        "type": "scenario.start",
        "request": user_request,
        "team": team,
        "ts": _now(),
        "mode": "coordinator",
        "specialist_count": len(specialists),
        "coordinator": coordinator.name,
    }

    if cancel.is_set():
        yield {"type": "scenario.done", "status": "cancelled", "ts": _now()}
        return

    # ---- Build the coordinator's LLM message stream -------------------------
    sys_prompt = _effective_system_prompt(coordinator, mode="coordinator")
    user_msg: dict[str, Any] = {"role": "user", "content": user_request}
    messages: list[dict] = [
        {"role": "system", "content": sys_prompt},
        user_msg,
    ]

    max_turns = max(1, coordinator.max_turns or 30)

    # Queue for specialist events forwarded from the coordinator's tool
    # executors.  We drain it after each tool call to surface the
    # specialist's events in correct order (between the coordinator's
    # tool_call and tool_result events).
    queue: asyncio.Queue = asyncio.Queue()

    for _turn_idx in range(max_turns):
        if cancel.is_set():
            yield {"type": "scenario.done", "status": "cancelled", "ts": _now()}
            return

        # ---- Stream one coordinator LLM turn --------------------------------
        yield {"type": "coordinator.start", "name": coordinator.name, "ts": _now()}

        text_chunks: list[str] = []
        tool_calls: dict[str, dict] = {}
        try:
            token_stream = stream_chat_with_tools(
                messages,
                tools=COORDINATOR_TOOL_SCHEMAS,
                model=model,
            )
            async for ev in _stream_with_timeout(token_stream, SYNTHESIS_TIMEOUT_S):
                if cancel.is_set():
                    raise asyncio.CancelledError
                if ev["kind"] == "text":
                    text_chunks.append(ev["delta"])
                    yield {
                        "type": "coordinator.token",
                        "delta": ev["delta"],
                        "ts": _now(),
                    }
                elif ev["kind"] == "tool_call":
                    tool_calls[ev["id"]] = ev
        except asyncio.CancelledError:
            yield {
                "type": "coordinator.error",
                "detail": "cancelled",
                "ts": _now(),
            }
            yield {"type": "scenario.done", "status": "cancelled", "ts": _now()}
            return
        except asyncio.TimeoutError:
            yield {
                "type": "coordinator.error",
                "detail": f"timeout ({SYNTHESIS_TIMEOUT_S}s, no token)",
                "ts": _now(),
            }
            yield {"type": "scenario.done", "status": "error", "ts": _now()}
            return
        except Exception as e:
            yield {
                "type": "coordinator.error",
                "detail": f"{type(e).__name__}: {e}",
                "ts": _now(),
            }
            yield {"type": "scenario.done", "status": "error", "ts": _now()}
            return

        assistant_text = "".join(text_chunks)
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_text or None,
        }
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["input"]),
                    },
                }
                for tc in tool_calls.values()
            ]
        messages.append(assistant_msg)

        # ---- No tool calls → coordinator finished without publishing --------
        if not tool_calls:
            yield {
                "type": "coordinator.error",
                "detail": (
                    "coordinator ended turn without calling any tool "
                    "(should call publish_final_report to terminate)"
                ),
                "ts": _now(),
            }
            yield {"type": "scenario.done", "status": "error", "ts": _now()}
            return

        # ---- Execute coordinator tool calls ---------------------------------
        terminate: tuple[bool, str] | None = None  # (True, final_text)

        for tc in tool_calls.values():
            name = tc["name"]
            input_data = tc["input"]
            tool_id = tc["id"]

            yield {
                "type": "coordinator.tool_call",
                "tool_id": tool_id,
                "tool_name": name,
                "tool_input": input_data,
                "ts": _now(),
            }

            # Look up executor
            executor = COORDINATOR_TOOL_EXECUTORS.get(name)
            if executor is None:
                result: dict = {
                    "output": f"unknown coordinator tool: {name!r}",
                    "is_error": True,
                }
            else:
                # Sync vs async dispatch.  Three tools (dispatch,
                # proceed, revise) need agent_obj + run_agent_turn
                # context; the rest are stateless.
                try:
                    if name in ("dispatch", "proceed", "revise"):
                        agent_name_in = (input_data or {}).get("agent_name", "")
                        if not isinstance(agent_name_in, str) or not agent_name_in:
                            result = {
                                "output": f"{name}() error: agent_name required",
                                "is_error": True,
                            }
                        elif agent_name_in not in specialists_by_name:
                            result = {
                                "output": (
                                    f"{name}() error: unknown specialist "
                                    f"{agent_name_in!r}; available: "
                                    f"{list(specialists_by_name.keys())}"
                                ),
                                "is_error": True,
                            }
                        else:
                            agent_obj = specialists_by_name[agent_name_in]
                            if asyncio.iscoroutinefunction(executor):
                                result = await executor(
                                    agent_name_in,
                                    input_data,
                                    agent_obj=agent_obj,
                                    histories=histories,
                                    cancel=cancel,
                                    queue=queue,
                                    runner_run_agent_turn=run_agent_turn,
                                )
                            else:
                                result = executor(
                                    agent_name_in,
                                    input_data,
                                    agent_obj=agent_obj,
                                    histories=histories,
                                    cancel=cancel,
                                    queue=queue,
                                    runner_run_agent_turn=run_agent_turn,
                                )
                    else:
                        # observe / finish_agent / assert_goal_coverage /
                        # publish_final_report — sync or async, no extra kwargs
                        if asyncio.iscoroutinefunction(executor):
                            result = await executor(coordinator.name, input_data)
                        else:
                            result = executor(coordinator.name, input_data)
                except Exception as e:
                    result = {
                        "output": f"{name}() raised: {type(e).__name__}: {e}",
                        "is_error": True,
                    }

            # ---- Drain queue: surface specialist events between tool_call
            # and tool_result.  v1 ordering (acceptable for the live UI):
            #   coordinator.tool_call
            #   <all specialist events from this dispatch>
            #   coordinator.tool_result
            while True:
                try:
                    yield queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            yield {
                "type": "coordinator.tool_result",
                "tool_id": tool_id,
                "tool_name": name,
                "output": result.get("output", ""),
                "is_error": result.get("is_error", False),
                "ts": _now(),
            }

            # Append tool result to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": result.get("output", ""),
            })

            # Check for the publish_final_report sentinel
            if result.get(TERMINATE_SENTINEL):
                terminate = (True, result.get("final_report_text", ""))

        if terminate is not None:
            final_text = terminate[1]
            yield {
                "type": "coordinator.done",
                "text": final_text,
                "ts": _now(),
            }
            yield {
                "type": "scenario.done",
                "status": "ok",
                "ts": _now(),
                "final_report": final_text,
            }
            return

        # Loop → next coordinator LLM turn

    # Out of turns
    yield {
        "type": "coordinator.error",
        "detail": f"max_turns={max_turns} reached without publish_final_report",
        "ts": _now(),
    }
    yield {"type": "scenario.done", "status": "max_turns", "ts": _now()}


# ---------------------------------------------------------------------------
# 整改方案 §B3 — Workflow 模式 (mode="workflow")
# ---------------------------------------------------------------------------
# 第 4 种 scenario runner。区别于：
#   - classic     : 4 个 specialist 并发 + 1 个 synthesis LLM
#   - coordinator : supervisor LLM 自主调 7 个 coordinator 工具
#   - workflow    : WorkflowScheduler 按 stage 契约编排，可串/并混合
#
# 入口 /ws/scenario mode="workflow" 使用本函数。
# 事件流（新增）：
#   scenario.start       { round, stages, mode="workflow" }
#   stage.start          { stage, label, mode, agents }
#   stage.done           { stage, outputs }
#   stage.error          { stage, detail }
#   agent.start/.token/.tool_call/.tool_result/.done/.error
#   scenario.done        { status: ok|cancelled|error|red_flag }
from . import workflows as wf
# 注意：stage_executors 在函数内延迟 import（避免循环依赖）
# from .stage_executors import default_executors, knowledge_analysis_executor


async def run_workflow_scenario(
    user_request: str,
    *,
    team: str = "webui-workflow",
    model: str | None = None,
    cancel: asyncio.Event | None = None,
    histories: dict[str, list[dict]] | None = None,
    session_id: str | None = None,
    stages: list[str] | None = None,
    intent: str | None = None,
    incremental: bool = False,    # S5-E — 增量更新模式（仅跑 report stage，prompt 加增量提示）
) -> AsyncIterator[dict]:
    """S2: workflow-mode scenario runner.

    Args:
        user_request: user text
        session_id: 会话 ID（None=新会话）
        stages: 直接指定要跑的 stage 列表（None=用 intent 自动选）
        intent: 意图分类（None=用 classify_intent 推断）
        其他: 同 run_scenario

    Yields workflow events (scenario.start, stage.*, agent.*, scenario.done).
    """
    # 延迟 import 避免循环依赖（stage_executors 也 import scenario_runner）
    from .stage_executors import default_executors, knowledge_analysis_executor

    if cancel is None:
        cancel = asyncio.Event()
    if histories is None:
        histories = {}

    # §B7: 拿到/创建会话
    session = wf.get_or_create_session(session_id)
    session.round_no += 1
    session.completed_stages = []  # 新一轮清空（支持多轮）

    # §B6: 决定 stage 列表
    if stages is None:
        if intent is None:
            intent_obj = wf.classify_intent(
                user_request,
                has_patient_record=bool(session.ctx.get("patient_record")),
                round_no=session.round_no,
            )
        else:
            try:
                intent_obj = wf.Intent(intent)
            except ValueError:
                intent_obj = wf.Intent.UNKNOWN
        session.last_intent = intent_obj
        stages = wf.stages_for_intent(intent_obj)
    session.last_stages = list(stages)

    # 注入到 ctx
    session.ctx["user_request"] = user_request
    session.ctx.setdefault("round", session.round_no)
    session.ctx["session_id"] = session.session_id
    # S5-E — 增量模式标记（report prompt 据此调整）
    if incremental:
        session.ctx["incremental_mode"] = True

    # §B3: 构造 scheduler + executors
    executors = default_executors()
    executors["knowledge_analysis"] = (
        lambda ctx, c, s, q: knowledge_analysis_executor(ctx, c, s, q, histories=histories)
    )
    # 把 histories 注入到单 agent executors（通过闭包）
    from functools import partial
    executors["intake"] = partial(_wrap_with_histories, "intake", histories)
    executors["knowledge"] = partial(_wrap_with_histories, "knowledge", histories)
    executors["analysis"] = partial(_wrap_with_histories, "analysis", histories)
    executors["evolution"] = partial(_wrap_with_histories, "evolution", histories)
    executors["report"] = partial(_wrap_with_histories, "report", histories)

    sched = wf.WorkflowScheduler(executors)

    # S5-E — 捕获 report stage 的 final_text，写回 ctx（供下一轮 incremental 用）
    _last_report_text: list[str] = []

    async for ev in sched.run(stages, session.ctx, session, cancel,
                               bypass_dep_check=incremental):
        # 抓取 report.done 事件的 text
        if ev.get("type") == "agent.done" and ev.get("stage") == "report" and ev.get("text"):
            _last_report_text.append(ev["text"])

        # 翻译 / 补全事件格式
        if ev["type"] == "scenario.start":
            yield {
                "type": "scenario.start",
                "mode": "workflow",
                "intent": session.last_intent.value if session.last_intent else None,
                "stages": stages,
                "round": session.round_no,
                "session_id": session.session_id,
                "ts": ev["ts"],
            }
            continue
        if ev["type"] == "scenario.done":
            yield {
                "type": "scenario.done",
                "status": ev.get("status", "ok"),
                "detail": ev.get("detail"),
                "session_id": session.session_id,
                "ts": ev["ts"],
            }
            continue
        # stage.* / agent.* / 其他原样转发
        yield ev

    # workflow 结束后把最终报告写回 ctx（供下一轮 incremental 模式的 report prompt 用）
    if _last_report_text:
        session.ctx["final_report"] = _last_report_text[-1]


def _wrap_with_histories(
    stage_name: str,
    histories: dict[str, list[dict]],
    ctx: dict,
    cancel: asyncio.Event,
    session,
    queue: asyncio.Queue,
):
    """闭包：把 histories 注入到 executor 调用。"""
    from .stage_executors import (
        intake_executor, knowledge_executor, analysis_executor,
        evolution_executor, report_executor,
    )
    dispatch = {
        "intake": intake_executor,
        "knowledge": knowledge_executor,
        "analysis": analysis_executor,
        "evolution": evolution_executor,
        "report": report_executor,
    }
    fn = dispatch[stage_name]
    return fn(ctx, cancel, session, queue, histories=histories)
