"""Smoke test for P9 — verify the plan-first protocol.

This is a UNIT test of ``scenario_runner.run_agent_turn`` with
``mode='plan_first'``. We patch ``stream_chat_with_tools`` so the
test is fully deterministic (no real LLM call, no flakiness).

Contract verified (3 tests):

  TEST 1 — plan-first happy path
    - First  LLM call: emit tool_call ``plan([t1, t2])``
    - Second LLM call: emit tool_call ``update_todo(t1, "running")``
      followed by text, then exit.
    - Runner yields: tool_call → tool_result → plan_return →
      tool_call → tool_result → step_status → text → turn_done(0)
      → agent_done.
    - State: state.plan_returned=True, state.todos has 2 steps with
      t1.status == "running".

  TEST 2 — no plan() on first turn → abort
    - First LLM call: emit plain text (no tool calls).
    - Runner yields: text → turn_done(0) → agent_error("plan_required: ...").
    - State: state.is_finished=True, state.finish_reason="plan_required".

  TEST 3 — illegal status transition rejected
    - First  LLM call: emit tool_call ``plan([t1])``.
    - Second LLM call: emit TWO tool_calls:
        1. update_todo(t1, "running")   — legal
        2. update_todo(t1, "done")      — legal
        3. update_todo(t1, "running")   — ILLEGAL (done → running)
    - The third tool_result must have ``is_error=True``.
    - The step's status must remain "done" (the rejected call did
      NOT mutate state).

Robustness:
  - All tests run in-process by patching scenario_runner's
    stream_chat_with_tools. (See smoke_p6_tool.py for the same pattern.)
  - ``team_types.reset_team_state()`` is called at the start of each
    test so agent names from a prior test don't leak.
  - We use any existing specialist (e.g. analysis-specialist) as the
    "host" agent — the smoke test only inspects the protocol, the
    agent's own skills are irrelevant.

Run from repo root, with venv active:
    python webui/scripts/smoke_p9_plan_first.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, AsyncIterator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webui.server import agents_io, scenario_runner  # noqa: E402
from webui.server.llm import stream_chat_with_tools   # noqa: E402
from webui.server.team_types import get_agent_state, reset_team_state  # noqa: E402


def banner(msg: str) -> None:
    print(f"\n=== {msg} ===")


def pick_specialist():
    """Find any user specialist on disk. The smoke test only needs a
    well-formed Agent object — its skill content doesn't matter."""
    specialists = [a for a in agents_io.list_agents() if a.role != "coordinator"]
    if not specialists:
        print("❌ no user specialists found in ~/.openharness/agents/")
        sys.exit(1)
    return specialists[0]


# ---------------------------------------------------------------------------
# Reusable harness: patch stream_chat_with_tools + run + collect
# ---------------------------------------------------------------------------
def patch_stream(sequence: list):
    """Replace scenario_runner.stream_chat_with_tools with a stub that
    pulls one stub factory from ``sequence`` per LLM call, in order.
    The last factory is reused for any further calls so the agent
    loop always exits cleanly. Each factory is called with
    ``(messages, tools=...)`` to produce a fresh async generator."""
    real = stream_chat_with_tools
    call_count = 0

    async def patched(messages, *, model=None, temperature=0.7,
                      max_tokens=None, tools=None):
        nonlocal call_count
        idx = min(call_count, len(sequence) - 1)
        call_count += 1
        async for ev in sequence[idx](messages, tools=tools):
            yield ev

    scenario_runner.stream_chat_with_tools = patched  # type: ignore
    return real, patched


def restore_stream(real) -> None:
    scenario_runner.stream_chat_with_tools = real  # type: ignore


# ---------------------------------------------------------------------------
# Stub builders: deterministic per-turn event streams
# ---------------------------------------------------------------------------
# Each stub is a *callable* that returns an async generator. The patched
# stream_chat_with_tools calls one stub per LLM call and iterates its
# events. We can't use ``async def gen()`` directly as a stub because
# the patched function expects to AWAIT something — we return a fresh
# async generator each time instead.

def stub_plan_first_turn(todos: list[dict]):
    """First-turn stub: emit a single tool_call for ``plan()`` then
    end the stream."""
    async def gen(messages, *, tools=None):
        yield {"kind": "text", "delta": "好的,先出计划。"}
        yield {"kind": "finish", "reason": "tool_calls"}
        yield {
            "kind": "tool_call",
            "id": "call_plan_1",
            "name": "plan",
            "input": {"todos": todos},
        }
    return gen


def stub_text_only_turn():
    """A turn that produces only text (no tool calls). Used by
    TEST 2 to verify plan-first rejects the case where the agent
    forgot to call plan()."""
    async def gen(messages, *, tools=None):
        yield {"kind": "text", "delta": "我没有计划,直接回答。"}
        yield {"kind": "finish", "reason": "stop"}
    return gen


def stub_execute_todo_turn(tool_calls: list[dict]):
    """A turn that produces 1+ tool_calls (e.g. update_todo)."""
    async def gen(messages, *, tools=None):
        for i, tc in enumerate(tool_calls):
            yield {
                "kind": "tool_call",
                "id": tc.get("id", f"call_{i+1}"),
                "name": tc["name"],
                "input": tc["input"],
            }
        yield {"kind": "finish", "reason": "tool_calls"}
    return gen


def stub_final_text_turn(text: str = "完成。"):
    """A turn that emits a final text answer and ends."""
    async def gen(messages, *, tools=None):
        yield {"kind": "text", "delta": text}
        yield {"kind": "finish", "reason": "stop"}
    return gen


# ---------------------------------------------------------------------------
# TEST 1 — plan-first happy path
# ---------------------------------------------------------------------------
async def test_1_plan_first_happy_path(agent) -> int:
    banner("TEST 1: plan-first happy path (plan → step running → done)")
    reset_team_state()
    sequence = [
        stub_plan_first_turn([
            {"id": "t1", "content": "查天气"},
            {"id": "t2", "content": "给建议", "depends_on": ["t1"]},
        ]),
        stub_execute_todo_turn([
            {"id": "call_ut1", "name": "update_todo",
             "input": {"step_id": "t1", "status": "running"}},
        ]),
        stub_final_text_turn("查完了。"),
    ]
    real, _ = patch_stream(sequence)
    try:
        events: list[dict] = []
        async for ev in scenario_runner.run_agent_turn(
            agent, "今天天气怎样", history=[], mode="plan_first",
        ):
            events.append(ev)
    finally:
        restore_stream(real)

    kinds = [e["kind"] for e in events]
    print(f"  events: {kinds}")

    # 1a. plan_return must appear
    plan_returns = [e for e in events if e["kind"] == "plan_return"]
    if len(plan_returns) != 1:
        print(f"❌ expected 1 plan_return, got {len(plan_returns)}")
        return 1
    pr = plan_returns[0]
    if pr["rev"] != 1 or len(pr["todos"]) != 2:
        print(f"❌ plan_return payload wrong: {pr}")
        return 1
    print(f"  ✓ plan_return rev=1, 2 todos")

    # 1b. step_status must appear
    step_statuses = [e for e in events if e["kind"] == "step_status"]
    if len(step_statuses) != 1:
        print(f"❌ expected 1 step_status, got {len(step_statuses)}")
        return 1
    ss = step_statuses[0]
    if ss["step_id"] != "t1" or ss["status"] != "running":
        print(f"❌ step_status payload wrong: {ss}")
        return 1
    print(f"  ✓ step_status t1=running")

    # 1c. terminal agent_done
    if events[-1]["kind"] != "agent_done":
        print(f"❌ terminal event is {events[-1]['kind']!r}, expected agent_done")
        return 1
    print(f"  ✓ terminal agent_done")

    # 1d. state correctly mutated
    state = get_agent_state(agent.name)
    if not state.plan_returned or state.plan_rev != 1:
        print(f"❌ state.plan_returned/rev wrong: {state.plan_returned} / {state.plan_rev}")
        return 1
    if len(state.todos) != 2 or state.todos[0].status != "running":
        print(f"❌ state.todos wrong: {[(t.id, t.status) for t in state.todos]}")
        return 1
    if not state.is_finished or state.finish_reason != "ok":
        print(f"❌ is_finished/finish_reason wrong: {state.is_finished} / {state.finish_reason}")
        return 1
    print(f"  ✓ state: plan_rev=1, t1.status=running, is_finished=ok")

    # 1e. ordering: tool_call → tool_result → plan_return
    # (for the plan() call)
    tc_idx = next(i for i, e in enumerate(events) if e["kind"] == "tool_call" and e["name"] == "plan")
    tr_idx = next(i for i, e in enumerate(events) if e["kind"] == "tool_result" and e["name"] == "plan")
    pr_idx = next(i for i, e in enumerate(events) if e["kind"] == "plan_return")
    if not (tc_idx < tr_idx < pr_idx):
        print(f"❌ wrong ordering: tool_call={tc_idx} tool_result={tr_idx} plan_return={pr_idx}")
        return 1
    print(f"  ✓ ordering: tool_call({tc_idx}) → tool_result({tr_idx}) → plan_return({pr_idx})")

    print("  ✅ TEST 1 passed")
    return 0


# ---------------------------------------------------------------------------
# TEST 2 — no plan() on first turn → abort
# ---------------------------------------------------------------------------
async def test_2_no_plan_aborts(agent) -> int:
    banner("TEST 2: no plan() on first turn → agent_error('plan_required')")
    reset_team_state()
    sequence = [stub_text_only_turn()]  # never calls plan
    real, _ = patch_stream(sequence)
    try:
        events: list[dict] = []
        async for ev in scenario_runner.run_agent_turn(
            agent, "查天气", history=[], mode="plan_first",
        ):
            events.append(ev)
    finally:
        restore_stream(real)

    kinds = [e["kind"] for e in events]
    print(f"  events: {kinds}")

    if not events or events[-1]["kind"] != "agent_error":
        print(f"❌ terminal event is {events[-1]['kind']!r}, expected agent_error")
        return 1
    detail = events[-1]["detail"]
    if "plan_required" not in detail:
        print(f"❌ agent_error detail missing 'plan_required': {detail!r}")
        return 1
    print(f"  ✓ agent_error: {detail!r}")

    state = get_agent_state(agent.name)
    if not state.is_finished or state.finish_reason != "plan_required":
        print(f"❌ state.finish_reason wrong: {state.finish_reason!r}")
        return 1
    if state.plan_returned:
        print(f"❌ state.plan_returned should be False")
        return 1
    print(f"  ✓ state: is_finished=True, finish_reason=plan_required, plan_returned=False")

    print("  ✅ TEST 2 passed")
    return 0


# ---------------------------------------------------------------------------
# TEST 3 — illegal status transition is rejected, state unchanged
# ---------------------------------------------------------------------------
async def test_3_state_machine_rejects(agent) -> int:
    banner("TEST 3: illegal update_todo transition rejected, state unchanged")
    reset_team_state()
    sequence = [
        stub_plan_first_turn([{"id": "t1", "content": "do thing"}]),
        stub_execute_todo_turn([
            {"id": "call_ut1", "name": "update_todo",
             "input": {"step_id": "t1", "status": "running"}},
            {"id": "call_ut2", "name": "update_todo",
             "input": {"step_id": "t1", "status": "done", "result": "ok"}},
            {"id": "call_ut3", "name": "update_todo",
             "input": {"step_id": "t1", "status": "running"}},  # illegal: done → running
        ]),
        stub_final_text_turn("完。"),
    ]
    real, _ = patch_stream(sequence)
    try:
        events: list[dict] = []
        async for ev in scenario_runner.run_agent_turn(
            agent, "test", history=[], mode="plan_first",
        ):
            events.append(ev)
    finally:
        restore_stream(real)

    # Find the three tool_results for update_todo (in order)
    ut_results = [e for e in events if e["kind"] == "tool_result" and e["name"] == "update_todo"]
    if len(ut_results) != 3:
        print(f"❌ expected 3 update_todo tool_results, got {len(ut_results)}")
        return 1
    is_errors = [r["is_error"] for r in ut_results]
    if is_errors != [False, False, True]:
        print(f"❌ is_error sequence wrong: expected [F,F,T], got {is_errors}")
        return 1
    print(f"  ✓ tool_result is_error: {is_errors} (third rejected)")

    # The third call's output must mention "illegal transition"
    rejected_output = ut_results[2]["output"]
    if "illegal transition" not in rejected_output:
        print(f"❌ rejected output missing 'illegal transition': {rejected_output!r}")
        return 1
    print(f"  ✓ rejected output: {rejected_output!r}")

    # State: t1 must still be "done" — the rejected call did NOT mutate it
    state = get_agent_state(agent.name)
    if state.todos[0].status != "done":
        print(f"❌ state mutated by rejected call: t1.status={state.todos[0].status!r}")
        return 1
    print(f"  ✓ state.todos[0].status still 'done' (rejected call didn't mutate)")

    # The first two step_status events must be "running" then "done"
    step_statuses = [e for e in events if e["kind"] == "step_status"]
    if [s["status"] for s in step_statuses] != ["running", "done"]:
        print(f"❌ step_status sequence wrong: {[s['status'] for s in step_statuses]}")
        return 1
    print(f"  ✓ step_status events: running, done (no third event for rejected call)")

    print("  ✅ TEST 3 passed")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
async def main() -> int:
    print("P9 plan-first smoke test (in-process, no LLM call)")
    agent = pick_specialist()
    print(f"using agent: {agent.name!r} (skills={list(agent.skills or [])})")
    print(f"max_turns={agent.max_turns} (using this directly)")

    rc = 0
    rc |= await test_1_plan_first_happy_path(agent)
    rc |= await test_2_no_plan_aborts(agent)
    rc |= await test_3_state_machine_rejects(agent)

    if rc:
        print(f"\n❌ {bin(rc).count('1')} test(s) failed")
    else:
        print("\n✅ P9 plan-first protocol verified — 3/3 tests passed")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
