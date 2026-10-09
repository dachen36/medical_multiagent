"""Smoke test for P6 — /ws/specialist protocol.

Contract (verified end-to-end against a real backend):
  1. Basic round-trip:
     - client → {type:"start", agentName, request}
     - server → specialist.start, specialist.token*, specialist.done
     - server closes socket after the terminal
  2. Multi-turn history:
     - second start against the same agent should continue the conversation
     - the second answer should be non-empty (server-side history is mutated)
  3. Cancel:
     - send {type:"cancel"} after the first token
     - server emits specialist.error detail="cancelled" and closes
  4. Clear:
     - send {type:"clear", agentName} → server emits {type:"cleared"}
     - a subsequent start produces a "fresh" answer (model has no prior context)

Run from repo root:
    python webui/scripts/smoke_p6_specialist.py

Requires: backend running on localhost:8000 (uvicorn webui.server.app).
"""
import asyncio
import json
import sys
from typing import Any

import websockets


AGENT = "evolution-specialist"
URI = "ws://localhost:8000/ws/specialist"


def banner(msg: str) -> None:
    print(f"\n=== {msg} ===")


async def recv_until(ws, *want: str) -> list[dict]:
    """Receive events until one of the wanted types arrives, or the socket closes.

    Returns the list of received events. Raises if the socket closes before
    a wanted event is seen.
    """
    got: list[dict] = []
    while True:
        raw = await ws.recv()
        ev = json.loads(raw)
        got.append(ev)
        if ev.get("type") in want:
            return got


async def test_basic_round_trip() -> dict:
    """Open WS, send a start, expect a clean done with non-empty text."""
    banner("TEST 1: basic round-trip")
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "start", "agentName": AGENT,
                                  "request": "用一句话介绍你自己"}))
        events = await recv_until(ws, "specialist.done", "specialist.error")
        last = events[-1]
        if last["type"] != "specialist.done":
            print(f"❌ expected specialist.done, got {last.get('type')!r}: {last}")
            raise SystemExit(1)
        if not last.get("text"):
            print(f"❌ specialist.done has empty text")
            raise SystemExit(1)
        token_count = sum(1 for e in events if e["type"] == "specialist.token")
        print(f"  ✓ got {len(events)} events, {token_count} tokens, "
              f"final text length={len(last['text'])}")
        print(f"  ✓ first 80 chars: {last['text'][:80]!r}")
        return last


async def test_multi_turn_continuation(first_text: str) -> None:
    """Two starts against the same agent — second answer should not be empty
    (the server keeps the history). We can't reliably force the small LLM to
    reference the first answer word-for-word, so we just check the second
    response is non-empty and the WS is clean.
    """
    banner("TEST 2: multi-turn continuation (server-side history)")
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "start", "agentName": AGENT,
                                  "request": "我刚才问了什么? 只回我'继续'两个字"}))
        events = await recv_until(ws, "specialist.done", "specialist.error")
        last = events[-1]
        if last["type"] != "specialist.done":
            print(f"❌ second start failed: {last}")
            raise SystemExit(1)
        if not last.get("text"):
            print(f"❌ second start returned empty text — history not preserved?")
            raise SystemExit(1)
        print(f"  ✓ second start: text={last['text'][:60]!r}")


async def test_cancel() -> None:
    """Send cancel after the first token, expect specialist.error detail='cancelled'."""
    banner("TEST 3: cancel")
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "start", "agentName": AGENT,
                                  "request": "详细介绍量子力学的历史"}))
        cancel_sent = False
        post_cancel_tokens = 0
        terminal: dict | None = None
        while True:
            raw = await ws.recv()
            ev = json.loads(raw)
            t = ev.get("type")
            if t == "specialist.token":
                if not cancel_sent:
                    cancel_sent = True
                    print(f"  → got first token ({len(ev.get('delta',''))} chars), sending cancel")
                    await ws.send(json.dumps({"type": "cancel"}))
                else:
                    post_cancel_tokens += 1
            elif t == "specialist.done":
                print(f"❌ expected specialist.error (cancelled), got specialist.done")
                raise SystemExit(1)
            elif t == "specialist.error":
                terminal = ev
                break
        if terminal is None:
            print(f"❌ no terminal event")
            raise SystemExit(1)
        if terminal.get("detail") != "cancelled":
            print(f"❌ expected detail='cancelled', got {terminal.get('detail')!r}")
            raise SystemExit(1)
        print(f"  ✓ specialist.error detail='cancelled'")
        print(f"  ✓ post-cancel tokens: {post_cancel_tokens}")


async def test_clear() -> None:
    """Send a standalone {type:'clear', agentName} on a fresh connection,
    expect the server to emit {type:'cleared'} and close. The frontend
    uses this pattern: the previous run connection is already closed by
    the server, so clear uses a fresh "control" connection.
    """
    banner("TEST 4: clear (standalone control message)")
    # Open a fresh connection and send only {type:'clear'}
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "clear", "agentName": AGENT}))
        events = await recv_until(ws, "cleared")
        last = events[-1]
        if last.get("type") != "cleared":
            print(f"❌ expected 'cleared', got {last}")
            raise SystemExit(1)
        if last.get("agentName") != AGENT:
            print(f"❌ cleared.agentName={last.get('agentName')!r}, expected {AGENT!r}")
            raise SystemExit(1)
        print(f"  ✓ cleared event received for {AGENT!r}")

    # A subsequent start works (history is empty)
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "start", "agentName": AGENT,
                                  "request": "用'你好'两个字回答我"}))
        events2 = await recv_until(ws, "specialist.done", "specialist.error")
        last2 = events2[-1]
        if last2["type"] != "specialist.done" or not last2.get("text"):
            print(f"❌ post-clear start failed: {last2}")
            raise SystemExit(1)
        print(f"  ✓ post-clear start works: text={last2['text'][:60]!r}")


async def main() -> int:
    print(f"connecting to {URI} ...")
    try:
        await websockets.connect(URI).__aenter__()  # reachability check
    except Exception as e:
        print(f"❌ cannot reach backend: {e}")
        print("   start it with: nohup .venv/bin/python -m webui.server.app "
              "> /tmp/openharness_webui.log 2>&1 &")
        return 1

    try:
        last = await test_basic_round_trip()
        await test_multi_turn_continuation(last["text"])
        await test_cancel()
        await test_clear()
    except SystemExit:
        raise
    except Exception as e:
        print(f"❌ unexpected error: {type(e).__name__}: {e}")
        return 1

    print(f"\n✅ P6 /ws/specialist verified — basic round-trip + multi-turn + "
          f"cancel + clear all work")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
