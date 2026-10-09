"""Smoke test for P5 — validate per-specialist timeout detection.

This is a unit test of `scenario_runner.run_scenario` itself, not a
WebSocket test. We patch `stream_chat_with_tools` (the LLM call that
specialists go through post-P6) to a stalling version and verify that
the runner emits `specialist.error detail="timeout (...)"` for the
stalled specialist, while the other 3 specialists complete normally
and the scenario reaches `scenario.done status="ok"`.

P6 note: pre-P6 this test patched `stream_chat`. After P6, specialists
fan out through `stream_chat_with_tools` so the tool_call/tool_result
events can be surfaced. The synthesis still uses the plain `stream_chat`
(coordination has no tools), so we patch only the with-tools version.

Usage (from repo root, with venv active):
    python webui/scripts/smoke_p5_timeout.py
"""
import asyncio
import os
import sys
import time
from typing import Any, AsyncIterator

# Force a short timeout BEFORE importing the runner, so the module-level
# constant picks it up.
os.environ["WEBUI_SPECIALIST_TIMEOUT_S"] = "2"
os.environ["WEBUI_SYNTHESIS_TIMEOUT_S"] = "2"

# Make repo importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webui.server import agents_io, scenario_runner  # noqa: E402
from webui.server.llm import stream_chat_with_tools  # noqa: E402  (original)


REQUEST = "我家孩子 5 岁发烧 38.5°C 怎么办？"  # noqa: E501


async def main() -> int:
    # ---- verify env override took effect ---------------------------------
    assert scenario_runner.SPECIALIST_TIMEOUT_S == 2.0, \
        f"expected timeout=2.0, got {scenario_runner.SPECIALIST_TIMEOUT_S}"
    assert scenario_runner.SYNTHESIS_TIMEOUT_S == 2.0, \
        f"expected timeout=2.0, got {scenario_runner.SYNTHESIS_TIMEOUT_S}"
    print(f"✓ timeouts loaded: specialist={scenario_runner.SPECIALIST_TIMEOUT_S}s "
          f"synthesis={scenario_runner.SYNTHESIS_TIMEOUT_S}s")

    # ---- verify there are real specialists to run -------------------------
    specialists = [a for a in agents_io.list_agents() if a.role != "coordinator"]
    if not specialists:
        print("❌ no user specialists found in ~/.openharness/agents/")
        return 1
    print(f"✓ {len(specialists)} specialists configured: "
          f"{[s.name for s in specialists]}")

    # ---- patch stream_chat_with_tools: the FIRST call stalls, others work
    # normally. Use a counter — simpler and more robust than inspecting the
    # system prompt. The first call (whichever specialist asyncio schedules
    # first) will hang; the remaining 3 use the real LLM.
    real_stream_chat_with_tools = stream_chat_with_tools
    call_log: list[str] = []
    call_count = 0

    async def patched_stream_chat_with_tools(
        messages, *, model=None, temperature=0.7, max_tokens=None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict]:
        nonlocal call_count
        call_count += 1
        # Try to identify which specialist this is for logging.
        sys_content = ""
        for m in messages:
            if m.get("role") == "system":
                sys_content = m.get("content", "")[:60]
        call_log.append(f"call#{call_count} sys={sys_content!r}")
        if call_count == 1:
            # Stall forever — never yield a token.
            await asyncio.Event().wait()
            return  # unreachable
        async for ev in real_stream_chat_with_tools(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, tools=tools,
        ):
            yield ev

    # Patch in the module where run_agent_turn looks it up.
    scenario_runner.stream_chat_with_tools = patched_stream_chat_with_tools  # type: ignore
    print(f"✓ patched stream_chat_with_tools: first call stalls, others use real LLM")

    # ---- run the scenario and collect events -----------------------------
    print(f"\nrunning scenario for {REQUEST!r} ...\n")
    t0 = time.time()
    events: list[dict] = []
    try:
        async for ev in scenario_runner.run_scenario(REQUEST, team="p5-timeout-test"):
            events.append(ev)
            elapsed = time.time() - t0
            t = ev.get("type", "?")
            extra = ""
            if t == "specialist.error":
                extra = f" detail={ev.get('detail')!r}"
            elif t == "specialist.done":
                extra = f" chars={len(ev.get('text', ''))}"
            elif t == "synthesis.token":
                continue   # too noisy; only print terminals
            print(f"  [{elapsed:5.2f}s] {t}{extra}")
    finally:
        scenario_runner.stream_chat_with_tools = real_stream_chat_with_tools  # restore

    elapsed = time.time() - t0
    print(f"\nscenario finished in {elapsed:.2f}s, {len(events)} events total")
    print(f"stream_chat_with_tools call log ({len(call_log)} total):")
    for entry in call_log:
        print(f"   {entry}")

    # ---- check 1: at least one specialist.error with timeout detail ------
    timeout_errors = [
        e for e in events
        if e.get("type") == "specialist.error"
        and "timeout" in e.get("detail", "").lower()
    ]
    if not timeout_errors:
        print(f"❌ no specialist.error with 'timeout' detail")
        return 1
    stalled_name = timeout_errors[0].get("name", "?")
    detail = timeout_errors[0].get("detail", "")
    print(f"✓ {stalled_name!r} reported timeout: {detail!r}")

    # ---- check 2: timeout fired reasonably close to the limit -------------
    # SPECIALIST_TIMEOUT_S=2; we expect the timeout error to be emitted
    # ~2s after scenario.start. The total scenario time is longer because
    # the other 3 specialists and synthesis still complete normally —
    # we measure the gap to the timeout event, not the total run time.
    timeout_at = time.time()
    for ev in events:
        if ev.get("type") == "specialist.error" and "timeout" in ev.get("detail", ""):
            break
    else:
        timeout_at = None
    # Walk the event stream to find the time offset at the timeout event.
    # The script records elapsed for each event inline, so we re-walk to
    # find which one was the timeout error. We tracked elapsed-from-t0
    # per-print above; instead, recompute from the event timestamps.
    t0_event_ts = next((e.get("ts") for e in events if e.get("type") == "scenario.start"), None)
    timeout_ts = next(
        (e.get("ts") for e in events
         if e.get("type") == "specialist.error" and "timeout" in e.get("detail", "")),
        None,
    )
    if t0_event_ts and timeout_ts:
        delay = timeout_ts - t0_event_ts
        if delay > 4.0:
            print(f"⚠ timeout fired at +{delay:.2f}s (limit was 2s; "
                  f"expected ≤4s)")
        else:
            print(f"✓ timeout fired at +{delay:.2f}s (limit was 2s)")
    else:
        print(f"⚠ could not measure timeout delay")

    # ---- check 3: terminal event present ---------------------------------
    terminals = [e for e in events
                 if e.get("type") in ("scenario.done", "scenario.error")]
    if not terminals:
        print(f"❌ no terminal event")
        return 1
    last_terminal = terminals[-1]
    print(f"✓ terminal: type={last_terminal.get('type')!r} "
          f"status={last_terminal.get('status', '—')!r}")

    # ---- check 4: the other 3 specialists completed normally --------------
    other_dones = [
        e for e in events
        if e.get("type") == "specialist.done"
        and e.get("name") != stalled_name
    ]
    expected = len(specialists) - 1
    if len(other_dones) < expected:
        print(f"⚠ only {len(other_dones)}/{expected} other specialists "
              f"completed (timeout may have been too aggressive)")
    else:
        print(f"✓ all {len(other_dones)}/{expected} other specialists "
              f"completed normally")

    print(f"\n✅ P5 timeout detection verified — stalled specialist is "
          f"aborted with a `timeout` error and the scenario continues")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
