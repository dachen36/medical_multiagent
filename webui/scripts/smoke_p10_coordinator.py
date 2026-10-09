"""Smoke test for P10 — verify the coordinator (supervisor) protocol.

This is a UNIT test of ``scenario_runner.run_coordinator_scenario``.
We patch ``stream_chat_with_tools`` (used by BOTH the coordinator's
LLM calls and the specialists' LLM calls — both flow through the
same module-level reference) so the test is fully deterministic
(no real LLM call, no flakiness).

Contract verified (4 tests):

  TEST 1 — dispatch(wait_for="plan") → proceed → publish_final_report
    - Coordinator turn 1: emit tool_call ``dispatch(medical, "x", wait_for="plan")``
    - Specialist (plan_first_pause mode): emit ``plan([t1, t2])``, end
    - Coordinator turn 2: emit tool_call ``proceed(medical)``
    - Specialist (classic mode): emit text, end
    - Coordinator turn 3: emit tool_call ``publish_final_report("hello world")``
    - Runner yields: scenario.start(mode=coordinator) → coordinator.start →
      coordinator.tool_call(dispatch) → coordinator.tool_result →
      coordinator.tool_call(proceed) → coordinator.tool_result →
      coordinator.tool_call(publish_final_report) → coordinator.tool_result →
      coordinator.done(text="hello world") → scenario.done(status="ok",
      final_report="hello world").
    - State: analysis-specialist.todos[0] is still in plan (its
      plan_first_pause was resumed by proceed).

  TEST 2 — revise with new_todos archives the old plan
    - Coordinator turn 1: emit tool_call ``dispatch(medical, "x", wait_for="plan")``
    - Specialist: emit ``plan([t1, t2])``
    - Coordinator turn 2: emit tool_call
      ``revise(medical, new_todos=[{id:t1,content:"x"},{id:t3,content:"y"}])``
    - Coordinator turn 3: emit tool_call ``publish_final_report("ok")``
    - Assert: state.archived_todos has the original [t1, t2];
      state.todos has the new [t1, t3].

  TEST 3 — publish_final_report is terminal
    - Coordinator turn 1: emit tool_call ``publish_final_report("done")``
    - Assert: scenario.done with status="ok" and final_report="done".
      No further coordinator turns happen.

  TEST 4 — finish_agent sets the stop_requested flag
    - Coordinator turn 1: emit tool_call ``finish_agent(medical, "stop")``
    - Assert: state.stop_requested is True (visible via observe tool).
    - Confirm observe() output includes "stop_requested": true.

Robustness:
  - All tests run in-process by patching scenario_runner's
    stream_chat_with_tools.
  - ``team_types.reset_team_state()`` is called at the start of each
    test so agent names from a prior test don't leak.
  - We use the first available user specialist as the dispatch target.
    Its real skill content doesn't matter; we only need a well-formed
    Agent object.
  - Histories dict is local per-test (P7.A pattern).

Run from repo root, with venv active:
    python webui/scripts/smoke_p10_coordinator.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, AsyncIterator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webui.server import agents_io, scenario_runner                          # noqa: E402
from webui.server.llm import stream_chat_with_tools                         # noqa: E402
from webui.server.team_types import get_agent_state, reset_team_state      # noqa: E402


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
# Reusable harness: patch stream_chat_with_tools
# ---------------------------------------------------------------------------
def patch_stream(sequence: list) -> tuple[Any, Any]:
    """Replace scenario_runner.stream_chat_with_tools with a stub that
    pulls one stub factory from ``sequence`` per LLM call, in order.
    The last factory is reused for any further calls so the agent
    loop always exits cleanly. Each factory returns a fresh async
    generator."""
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
# Stub builders
# ---------------------------------------------------------------------------
def stub_coordinator_tool_call(
    name: str, args: dict, tool_id: str | None = None,
) -> Any:
    """A coordinator LLM turn that emits a single tool call and ends."""
    tid = tool_id or f"call_{name}_1"

    async def gen(messages, *, tools=None):
        yield {"kind": "text", "delta": f"calling {name}..."}
        yield {"kind": "finish", "reason": "tool_calls"}
        yield {
            "kind": "tool_call",
            "id": tid,
            "name": name,
            "input": args,
        }
    return gen


def stub_specialist_plan_first_pause(todos: list[dict]) -> Any:
    """Specialist in plan_first_pause mode: emit plan([...]), then end
    (the runner sees `turn_done` after plan and returns)."""
    async def gen(messages, *, tools=None):
        yield {"kind": "text", "delta": "我先出计划。"}
        yield {"kind": "finish", "reason": "tool_calls"}
        yield {
            "kind": "tool_call",
            "id": "call_plan_1",
            "name": "plan",
            "input": {"todos": todos},
        }
    return gen


def stub_specialist_final_text(text: str) -> Any:
    """Specialist that emits final text and ends cleanly."""
    async def gen(messages, *, tools=None):
        yield {"kind": "text", "delta": text}
        yield {"kind": "finish", "reason": "stop"}
    return gen


def stub_specialist_empty() -> Any:
    """Specialist that emits nothing — used to test stop_requested early exit."""
    async def gen(messages, *, tools=None):
        yield {"kind": "text", "delta": "用户已请求早停,直接结束。"}
        yield {"kind": "finish", "reason": "stop"}
    return gen


# ---------------------------------------------------------------------------
# TEST 1 — dispatch(wait_for=plan) → proceed → publish_final_report
# ---------------------------------------------------------------------------
async def test_1_dispatch_plan_proceed_publish(agent) -> int:
    banner("TEST 1: dispatch(plan) → proceed → publish_final_report")
    reset_team_state()
    histories: dict[str, list[dict]] = {}
    sequence = [
        # Turn 1 — coordinator dispatches medical, wait_for=plan
        stub_coordinator_tool_call("dispatch", {
            "agent_name": agent.name, "task": "评估用户症状", "wait_for": "plan",
        }, tool_id="call_dispatch_1"),
        # Specialist in plan_first_pause mode
        stub_specialist_plan_first_pause([
            {"id": "t1", "content": "查体温"},
            {"id": "t2", "content": "给建议"},
        ]),
        # Turn 2 — coordinator proceeds with medical
        stub_coordinator_tool_call("proceed", {
            "agent_name": agent.name,
        }, tool_id="call_proceed_1"),
        # Specialist resumes in classic mode
        stub_specialist_final_text("评估完成:用户需要多喝水。"),
        # Turn 3 — coordinator publishes
        stub_coordinator_tool_call("publish_final_report", {
            "text": "综合建议:多喝水,继续观察。",
        }, tool_id="call_publish_1"),
    ]
    real, _ = patch_stream(sequence)
    try:
        events: list[dict] = []
        async for ev in scenario_runner.run_coordinator_scenario(
            "用户发烧 38.5°C,持续 6 小时", histories=histories,
        ):
            events.append(ev)
    finally:
        restore_stream(real)

    types = [e["type"] for e in events]
    print(f"  events: {types}")

    # 1a. scenario.start with mode=coordinator
    ss = next((e for e in events if e["type"] == "scenario.start"), None)
    if ss is None:
        print("❌ missing scenario.start")
        return 1
    if ss.get("mode") != "coordinator":
        print(f"❌ scenario.start.mode wrong: {ss.get('mode')!r}")
        return 1
    print(f"  ✓ scenario.start mode=coordinator")

    # 1b. exactly 3 coordinator.tool_call events (dispatch, proceed, publish)
    tool_calls = [e for e in events if e["type"] == "coordinator.tool_call"]
    names = [e["tool_name"] for e in tool_calls]
    if names != ["dispatch", "proceed", "publish_final_report"]:
        print(f"❌ coordinator.tool_call sequence wrong: {names}")
        return 1
    print(f"  ✓ coordinator.tool_call sequence: {names}")

    # 1c. coordinator.done with the publish text
    cd = next((e for e in events if e["type"] == "coordinator.done"), None)
    if cd is None or cd["text"] != "综合建议:多喝水,继续观察。":
        print(f"❌ coordinator.done wrong: {cd}")
        return 1
    print(f"  ✓ coordinator.done text=综合建议:多喝水,继续观察。")

    # 1d. terminal scenario.done status=ok + final_report attached
    sd = next((e for e in events if e["type"] == "scenario.done"), None)
    if sd is None:
        print("❌ missing scenario.done")
        return 1
    if sd.get("status") != "ok":
        print(f"❌ scenario.done.status wrong: {sd.get('status')!r}")
        return 1
    if sd.get("final_report") != "综合建议:多喝水,继续观察。":
        print(f"❌ scenario.done.final_report wrong: {sd.get('final_report')!r}")
        return 1
    print(f"  ✓ scenario.done status=ok, final_report attached")

    # 1e. specialist events were forwarded between tool_call and tool_result.
    # _run_specialist_to_event forwards text/tool_call/tool_result/plan_return
    # events through the queue. specialist.start and specialist.done are NOT
    # emitted by the coordinator-driven path (they're emitted by the classic
    # run_scenario path). The plan_return + text events are the proof of life.
    plan_returns = [e for e in events if e["type"] == "specialist.plan_return"]
    spec_tokens = [e for e in events if e["type"] == "specialist.token"]
    if len(plan_returns) != 1:
        print(f"❌ expected 1 specialist.plan_return, got {len(plan_returns)}")
        return 1
    if len(spec_tokens) < 1:
        print(f"❌ no specialist.token events forwarded; got {len(spec_tokens)}")
        return 1
    print(f"  ✓ specialist events forwarded (plan_return={len(plan_returns)}, token={len(spec_tokens)})")

    # 1f. coordinator.tool_call comes BEFORE coordinator.tool_result for each
    # (so the WS sees the dispatch/proceed/publish envelope correctly)
    for tc in tool_calls:
        after = events[events.index(tc) + 1:]
        tr = next((e for e in after if e["type"] == "coordinator.tool_result"
                   and e.get("tool_id") == tc.get("tool_id")), None)
        if tr is None:
            print(f"❌ no matching coordinator.tool_result for {tc.get('tool_id')}")
            return 1
    print(f"  ✓ each coordinator.tool_call has a matching coordinator.tool_result")

    print("  ✅ TEST 1 passed")
    return 0


# ---------------------------------------------------------------------------
# TEST 2 — revise with new_todos archives the old plan
# ---------------------------------------------------------------------------
async def test_2_revise_archives_old_plan(agent) -> int:
    banner("TEST 2: revise(new_todos) archives old plan, applies new one")
    reset_team_state()
    histories: dict[str, list[dict]] = {}
    sequence = [
        # Turn 1: dispatch + plan
        stub_coordinator_tool_call("dispatch", {
            "agent_name": agent.name, "task": "评估", "wait_for": "plan",
        }, tool_id="call_dispatch_1"),
        stub_specialist_plan_first_pause([
            {"id": "t1", "content": "原计划 1"},
            {"id": "t2", "content": "原计划 2"},
        ]),
        # Turn 2: revise with new_todos
        stub_coordinator_tool_call("revise", {
            "agent_name": agent.name,
            "new_todos": [
                {"id": "t1", "content": "新计划 1"},
                {"id": "t3", "content": "新计划 3"},
            ],
        }, tool_id="call_revise_1"),
        stub_specialist_final_text("已按新计划执行。"),
        # Turn 3: publish
        stub_coordinator_tool_call("publish_final_report", {
            "text": "ok",
        }, tool_id="call_publish_1"),
    ]
    real, _ = patch_stream(sequence)
    try:
        events: list[dict] = []
        async for ev in scenario_runner.run_coordinator_scenario(
            "test", histories=histories,
        ):
            events.append(ev)
    finally:
        restore_stream(real)

    types = [e["type"] for e in events]
    print(f"  events: {types}")

    sd = next((e for e in events if e["type"] == "scenario.done"), None)
    if sd is None or sd.get("status") != "ok":
        print(f"❌ scenario.done wrong: {sd}")
        return 1
    print(f"  ✓ scenario.done status=ok")

    # State: archived_todos has the OLD [t1, t2]; current todos is NEW [t1, t3]
    state = get_agent_state(agent.name)
    if len(state.archived_todos) != 1:
        print(f"❌ state.archived_todos length wrong: {len(state.archived_todos)}")
        return 1
    archived = state.archived_todos[0]
    if [t.id for t in archived] != ["t1", "t2"]:
        print(f"❌ archived plan wrong: {[t.id for t in archived]}")
        return 1
    print(f"  ✓ archived_todos[0] = [t1, t2]")

    if [t.id for t in state.todos] != ["t1", "t3"]:
        print(f"❌ current todos wrong: {[t.id for t in state.todos]}")
        return 1
    print(f"  ✓ state.todos = [t1, t3] (revise applied)")

    print("  ✅ TEST 2 passed")
    return 0


# ---------------------------------------------------------------------------
# TEST 3 — publish_final_report is terminal (no further coordinator turns)
# ---------------------------------------------------------------------------
async def test_3_publish_is_terminal(agent) -> int:
    banner("TEST 3: publish_final_report terminates the run")
    reset_team_state()
    histories: dict[str, list[dict]] = {}
    # The stub AFTER publish should NEVER be called as an LLM call. We
    # tag it with a "should never run" flag, and count actual LLM
    # invocations via a custom patch that exposes call_count.
    ran_after_publish = [False]

    def post_publish_stub():
        async def gen(messages, *, tools=None):
            ran_after_publish[0] = True
            yield {"kind": "text", "delta": "should not be called"}
            yield {"kind": "finish", "reason": "stop"}
        return gen

    sequence = [
        stub_coordinator_tool_call("publish_final_report", {
            "text": "hello world",
        }, tool_id="call_publish_1"),
        post_publish_stub(),  # never invoked as an LLM call
    ]
    # Inline custom patch so we can count calls precisely
    real = stream_chat_with_tools
    call_count = [0]
    async def patched(messages, *, model=None, temperature=0.7,
                      max_tokens=None, tools=None):
        call_count[0] += 1
        idx = min(call_count[0] - 1, len(sequence) - 1)
        async for ev in sequence[idx](messages, tools=tools):
            yield ev
    scenario_runner.stream_chat_with_tools = patched  # type: ignore
    try:
        events: list[dict] = []
        async for ev in scenario_runner.run_coordinator_scenario(
            "test", histories=histories,
        ):
            events.append(ev)
    finally:
        restore_stream(real)

    if ran_after_publish[0]:
        print("❌ post_publish_stub was used as an LLM call (expected never)")
        return 1
    if call_count[0] != 1:
        print(f"❌ coordinator called LLM {call_count[0]} time(s) (expected 1)")
        return 1
    print(f"  ✓ exactly 1 LLM call (publish stub), no further calls")

    sd = next((e for e in events if e["type"] == "scenario.done"), None)
    if sd is None or sd.get("status") != "ok":
        print(f"❌ scenario.done wrong: {sd}")
        return 1
    if sd.get("final_report") != "hello world":
        print(f"❌ final_report wrong: {sd.get('final_report')!r}")
        return 1
    print(f"  ✓ scenario.done status=ok, final_report='hello world'")

    cd = next((e for e in events if e["type"] == "coordinator.done"), None)
    if cd is None or cd.get("text") != "hello world":
        print(f"❌ coordinator.done wrong: {cd}")
        return 1
    print(f"  ✓ coordinator.done text='hello world'")

    print("  ✅ TEST 3 passed")
    return 0


# ---------------------------------------------------------------------------
# TEST 4 — finish_agent sets stop_requested flag (visible via observe)
# ---------------------------------------------------------------------------
async def test_4_finish_agent_sets_flag(agent) -> int:
    banner("TEST 4: finish_agent sets state.stop_requested=True")
    reset_team_state()
    histories: dict[str, list[dict]] = {}
    # We need the coordinator to:
    #   1. observe(medical)  ← see stop_requested: false
    #   2. finish_agent(medical, "stop")
    #   3. observe(medical)  ← see stop_requested: true (after finish_agent)
    #   4. publish_final_report
    # The observe tool returns a JSON payload — we can parse it and assert
    # the flag flipped between the two observes.
    sequence = [
        stub_coordinator_tool_call("observe", {
            "agent_name": agent.name,
        }, tool_id="call_observe_1"),
        stub_coordinator_tool_call("finish_agent", {
            "agent_name": agent.name, "reason": "test stop",
        }, tool_id="call_finish_1"),
        stub_coordinator_tool_call("observe", {
            "agent_name": agent.name,
        }, tool_id="call_observe_2"),
        stub_coordinator_tool_call("publish_final_report", {
            "text": "done",
        }, tool_id="call_publish_1"),
    ]
    real, _ = patch_stream(sequence)
    try:
        events: list[dict] = []
        async for ev in scenario_runner.run_coordinator_scenario(
            "test", histories=histories,
        ):
            events.append(ev)
    finally:
        restore_stream(real)

    tool_results = [e for e in events if e["type"] == "coordinator.tool_result"]
    # Find the tool_result for observe_1, finish_1, observe_2, publish
    by_id: dict[str, dict] = {tr["tool_id"]: tr for tr in tool_results}

    # 4a. observe_1 should report stop_requested: false
    import json
    obs1_output = by_id["call_observe_1"]["output"]
    obs1_payload = json.loads(obs1_output)
    if obs1_payload.get("stop_requested") is not False:
        print(f"❌ observe_1.stop_requested not False: {obs1_payload.get('stop_requested')!r}")
        return 1
    print(f"  ✓ observe_1 reports stop_requested=False")

    # 4b. finish_agent should succeed (no error)
    fr = by_id["call_finish_1"]
    if fr["is_error"]:
        print(f"❌ finish_agent returned is_error=True: {fr['output']!r}")
        return 1
    if "stop flag set" not in fr["output"]:
        print(f"❌ finish_agent output missing 'stop flag set': {fr['output']!r}")
        return 1
    print(f"  ✓ finish_agent ok: {fr['output']!r}")

    # 4c. observe_2 should report stop_requested: true
    obs2_output = by_id["call_observe_2"]["output"]
    obs2_payload = json.loads(obs2_output)
    if obs2_payload.get("stop_requested") is not True:
        print(f"❌ observe_2.stop_requested not True: {obs2_payload.get('stop_requested')!r}")
        return 1
    print(f"  ✓ observe_2 reports stop_requested=True (flag flipped)")

    # 4d. scenario.done
    sd = next((e for e in events if e["type"] == "scenario.done"), None)
    if sd is None or sd.get("status") != "ok":
        print(f"❌ scenario.done wrong: {sd}")
        return 1
    print(f"  ✓ scenario.done status=ok")

    print("  ✅ TEST 4 passed")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
async def main() -> int:
    print("P10 coordinator (supervisor) smoke test (in-process, no LLM call)")
    agent = pick_specialist()
    print(f"using specialist: {agent.name!r}")

    rc = 0
    rc |= await test_1_dispatch_plan_proceed_publish(agent)
    rc |= await test_2_revise_archives_old_plan(agent)
    rc |= await test_3_publish_is_terminal(agent)
    rc |= await test_4_finish_agent_sets_flag(agent)

    if rc:
        print(f"\n❌ {bin(rc).count('1')} test(s) failed")
    else:
        print("\n✅ P10 coordinator protocol verified — 4/4 tests passed")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
