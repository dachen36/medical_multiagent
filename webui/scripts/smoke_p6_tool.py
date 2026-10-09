"""Smoke test for P6 — verify specialist.tool_call / specialist.tool_result events.

This is a UNIT test of ``scenario_runner.run_agent_turn``, not a WebSocket
test. We patch ``stream_chat_with_tools`` so the test is fully deterministic
(no real LLM call, no flakiness from small models choosing not to use tools).

Contract verified:

  1. Multi-turn tool flow:
     - First  LLM call: emits a tool_call for ``skill`` (asking to read
       ``book-learning``).
     - Second LLM call: emits a normal text answer.
     - The runner yields: text (pre-tool) → tool_call → tool_result →
       text (post-tool) → turn_done → agent_done.
  2. The SkillTool is actually invoked (not stubbed). We assert the
     tool_result output contains real skill content (i.e. starts with the
     frontmatter markers ``---``) so we know the registry → tool → result
     chain is wired up.
  3. The conversation history is mutated in place — the runner appends
     user / assistant / tool messages, so a follow-up ``run_agent_turn``
     call against the same ``history`` would see them.
  4. The agent loop terminates cleanly with ``agent_done`` (no leak, no
     runaway, no error).

Run from repo root, with venv active:
    python webui/scripts/smoke_p6_tool.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, AsyncIterator

# Make repo importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webui.server import agents_io, scenario_runner  # noqa: E402
from webui.server.llm import stream_chat_with_tools   # noqa: E402


# A skill that the user's care-specialist actually has on disk.
TEST_SKILL = "book-learning"


async def main() -> int:
    # ---- verify a specialist + skill is available --------------------------
    specialists = [a for a in agents_io.list_agents() if a.role != "coordinator"]
    if not specialists:
        print("❌ no user specialists found in ~/.openharness/agents/")
        return 1
    print(f"✓ {len(specialists)} specialists configured: "
          f"{[s.name for s in specialists]}")

    # Pick a specialist that has skills frontmatter (so the SkillTool is
    # actually wired in). The agent's skills list also drives which tool
    # schemas the runner offers the LLM, so without skills frontmatter
    # the patched call would be a no-op for tool selection.
    agent = next(
        (a for a in specialists if getattr(a, "skills", None)),
        specialists[0],
    )
    print(f"✓ using agent: name={agent.name!r} skills={list(agent.skills or [])}")

    # Verify the tool registry can find SkillTool (so we can later assert
    # the runner's tool schema includes 'skill').
    registry = scenario_runner._get_tool_registry()
    if "skill" not in registry._tools:
        print("❌ skill tool not registered — registry missing SkillTool")
        return 1
    print(f"✓ registry has 'skill' tool")

    # Verify the runner would actually offer 'skill' to this agent.
    schemas = scenario_runner._tools_for_agent(agent)
    names_offered = [s["function"]["name"] for s in schemas]
    if "skill" not in names_offered:
        print(f"❌ skill not in tool schemas for {agent.name!r}: {names_offered}")
        return 1
    print(f"✓ tool schemas offered: {names_offered}")

    # ---- patch stream_chat_with_tools: deterministic two-turn sequence ----
    # First call → emit a tool_call (asking to read TEST_SKILL).
    # Second call → emit a short text answer (no further tool calls).
    real_stream = stream_chat_with_tools
    call_log: list[str] = []

    async def patched(messages, *, model=None, temperature=0.7,
                      max_tokens=None, tools=None) -> AsyncIterator[dict]:
        # Identify the call by the system prompt prefix.
        sys_content = ""
        for m in messages:
            if m.get("role") == "system":
                sys_content = m.get("content", "")[:40]
                break
        call_count = len(call_log) + 1
        call_log.append(f"call#{call_count} sys={sys_content!r} "
                        f"messages={len(messages)} tools_offered={bool(tools)}")

        if call_count == 1:
            # Synthesize the same shape stream_chat_with_tools would emit
            # for a single tool call: one text chunk, then a finish reason
            # of "tool_calls", then the tool_call event after stream end.
            yield {"kind": "text", "delta": "让我先查一下相关知识库。"}
            yield {"kind": "finish", "reason": "tool_calls"}
            yield {
                "kind": "tool_call",
                "id": "call_test_001",
                "name": "skill",
                "input": {"name": TEST_SKILL},
            }
            return

        # Second call: just a text response. No further tool calls.
        yield {"kind": "text", "delta": "根据知识库，"}
        yield {"kind": "text", "delta": "学习 Python 推荐先读入门书。"}
        yield {"kind": "finish", "reason": "stop"}
        return

    # Patch in the module where run_agent_turn looks it up.
    scenario_runner.stream_chat_with_tools = patched  # type: ignore
    print(f"✓ patched stream_chat_with_tools: deterministic 2-turn sequence")

    # ---- run run_agent_turn and collect events ----------------------------
    print(f"\nrunning run_agent_turn(agent={agent.name!r}) ...\n")
    history: list[dict] = []
    events: list[dict] = []
    try:
        async for ev in scenario_runner.run_agent_turn(
            agent,
            f"用 {TEST_SKILL} 推荐一本 Python 入门书",
            history=history,
        ):
            events.append(ev)
            kind = ev.get("kind", "?")
            extra = ""
            if kind == "text":
                extra = f" delta={ev.get('delta', '')!r}"
            elif kind == "tool_call":
                extra = f" name={ev.get('name')!r} input={ev.get('input')!r}"
            elif kind == "tool_result":
                out = ev.get("output", "")
                extra = f" name={ev.get('name')!r} is_error={ev.get('is_error')}"
                if len(out) > 80:
                    out = out[:80] + "…"
                extra += f" output={out!r}"
            elif kind == "turn_done":
                extra = f" tool_calls_made={ev.get('tool_calls_made')}"
            print(f"  [{kind:13}] {extra}")
    finally:
        scenario_runner.stream_chat_with_tools = real_stream  # restore

    print(f"\nrunner finished, {len(events)} events, "
          f"{len(call_log)} patched LLM calls, history has {len(history)} msgs")

    # ---- check 1: event sequence matches the protocol contract -----------
    # Actual yield order from run_agent_turn:
    #   text(pre) → tool_call → tool_result → turn_done(1)
    #     → text(post) → turn_done(0) → agent_done
    kinds = [e["kind"] for e in events]

    # 1a. tool_call must be followed (possibly with intervening events) by tool_result
    tool_call_idx = next(i for i, e in enumerate(events) if e["kind"] == "tool_call")
    tool_result_idx = next(i for i, e in enumerate(events) if e["kind"] == "tool_result")
    if tool_result_idx <= tool_call_idx:
        print(f"❌ tool_result must come after tool_call (got "
              f"tool_call={tool_call_idx}, tool_result={tool_result_idx})")
        return 1
    print(f"✓ tool_call (idx={tool_call_idx}) → tool_result (idx={tool_result_idx})")

    # 1b. The tool_call.id and tool_result.id must match (they refer to the same call)
    tc_id = events[tool_call_idx]["id"]
    tr_id = events[tool_result_idx]["id"]
    if tc_id != tr_id:
        print(f"❌ tool_result.id={tr_id!r} != tool_call.id={tc_id!r}")
        return 1
    print(f"✓ tool_call.id matches tool_result.id: {tc_id!r}")

    # 1c. After tool_result, must see a turn_done with tool_calls_made=1
    turn_done_1_idx = next(
        (i for i, e in enumerate(events)
         if i > tool_result_idx and e["kind"] == "turn_done"
         and e.get("tool_calls_made") == 1),
        None,
    )
    if turn_done_1_idx is None:
        print(f"❌ no turn_done(tool_calls_made=1) after tool_result; "
              f"events: {kinds}")
        return 1
    print(f"✓ turn_done(tool_calls_made=1) at idx={turn_done_1_idx} "
          f"follows tool_result")

    # 1d. After that turn_done, must see at least one more text (post-tool response)
    post_tool_texts = [
        e for i, e in enumerate(events)
        if i > turn_done_1_idx and e["kind"] == "text"
    ]
    if not post_tool_texts:
        print(f"❌ no post-tool text after turn_done(tool_calls_made=1); "
              f"events: {kinds}")
        return 1
    print(f"✓ {len(post_tool_texts)} post-tool text event(s)")

    # 1e. After the post-tool text, must see a final turn_done(tool_calls_made=0)
    #     and then agent_done as the terminal.
    final_turn_done_idx = next(
        (i for i, e in enumerate(events)
         if i > turn_done_1_idx and e["kind"] == "turn_done"
         and e.get("tool_calls_made") == 0),
        None,
    )
    if final_turn_done_idx is None:
        print(f"❌ no final turn_done(tool_calls_made=0); events: {kinds}")
        return 1
    print(f"✓ final turn_done(tool_calls_made=0) at idx={final_turn_done_idx}")

    # 1f. agent_done must be the very last event
    if events[-1]["kind"] != "agent_done":
        print(f"❌ last event is {events[-1]['kind']!r}, expected 'agent_done'")
        return 1
    if events[-2]["kind"] != "turn_done":
        print(f"❌ event before agent_done is {events[-2]['kind']!r}, "
              f"expected 'turn_done'")
        return 1
    print(f"✓ terminal: turn_done → agent_done")

    # No agent_error leaked.
    if "agent_error" in kinds:
        print(f"❌ agent_error leaked into events: {events}")
        return 1
    print(f"✓ no agent_error in stream")

    # ---- check 2: tool_result is real skill content, not a stub ----------
    tool_result_ev = next(e for e in events if e["kind"] == "tool_result")
    out = tool_result_ev.get("output", "")
    if tool_result_ev.get("is_error"):
        print(f"❌ tool_result is_error=True, output={out!r}")
        return 1
    if not out or len(out) < 50:
        print(f"❌ tool_result output too short ({len(out)} chars): {out!r}")
        return 1
    # Real skill files start with frontmatter '---' markers
    if not out.lstrip().startswith("---"):
        print(f"❌ tool_result output doesn't look like skill markdown "
              f"(no '---' frontmatter): {out[:80]!r}")
        return 1
    print(f"✓ tool_result is real skill content "
          f"({len(out)} chars, starts with frontmatter)")

    # ---- check 3: history was mutated correctly ----------------------------
    # We expect: user, assistant (with tool_calls), tool (with tool_call_id),
    #            assistant (final text). The system prompt is NOT in history
    # (it's re-derived each call from agent.system_prompt_body).
    if len(history) < 4:
        print(f"❌ history has only {len(history)} messages, expected ≥4")
        return 1
    if history[0]["role"] != "user":
        print(f"❌ history[0] role={history[0].get('role')!r}, expected 'user'")
        return 1
    if history[1]["role"] != "assistant" or "tool_calls" not in history[1]:
        print(f"❌ history[1] should be assistant w/ tool_calls, got "
              f"role={history[1].get('role')!r} keys={list(history[1].keys())}")
        return 1
    if history[2]["role"] != "tool":
        print(f"❌ history[2] role={history[2].get('role')!r}, expected 'tool'")
        return 1
    if history[2].get("tool_call_id") != "call_test_001":
        print(f"❌ history[2].tool_call_id={history[2].get('tool_call_id')!r}, "
              f"expected 'call_test_001'")
        return 1
    if history[-1]["role"] != "assistant":
        print(f"❌ history[-1] role={history[-1].get('role')!r}, expected 'assistant'")
        return 1
    print(f"✓ history mutated correctly: {len(history)} msgs, "
          f"tool_call_id matches")

    # ---- check 4: stream_chat_with_tools was called exactly twice ---------
    if len(call_log) != 2:
        print(f"❌ expected 2 LLM calls, got {len(call_log)}: {call_log}")
        return 1
    # First call: system + user = 2 messages (history was empty)
    if "messages=2" not in call_log[0]:
        print(f"❌ first LLM call should have 2 messages (system+user), "
              f"got log: {call_log[0]!r}")
        return 1
    # Second call: system + user + assistant + tool = 4 messages
    if "messages=4" not in call_log[1]:
        print(f"❌ second LLM call should have 4 messages "
              f"(system+user+assistant+tool), got log: {call_log[1]!r}")
        return 1
    print(f"✓ stream_chat_with_tools called exactly 2 times, "
          f"message counts grow with history")

    # ---- check 5: post-tool text actually came through --------------------
    post_tool_text = "".join(
        e["delta"] for e in post_tool_texts
    )
    if "Python" not in post_tool_text:
        print(f"❌ post-tool text missing 'Python': {post_tool_text!r}")
        return 1
    print(f"✓ post-tool text: {post_tool_text!r}")

    print(f"\n✅ P6 specialist.tool_call / specialist.tool_result verified — "
          f"agent loop: text → tool_call → tool_result → text → done, "
          f"SkillTool returns real content, history is well-formed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
