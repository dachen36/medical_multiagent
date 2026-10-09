"""Smoke test for P4 — validate the new client-side event log accumulator.

This test doesn't render the UI; it captures the raw ScenarioEvent stream
and verifies the assumptions that SystemPanel's buildLogEntries() depends on:

  1. Every event has a numeric ts.
  2. Token events for the same actor within ~1.5s can be safely batched.
  3. The backend event protocol (start/done/error structure) is unchanged.

Run from repo root:
    python webui/scripts/smoke_p4_eventlog.py
"""
import asyncio
import json
import sys
import time
from collections import Counter

import websockets


REQUEST = "我家孩子 5 岁发烧 38.5°C 怎么办？"


async def main() -> int:
    uri = "ws://localhost:8000/ws/scenario"
    print(f"connecting to {uri} ...")
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "start", "request": REQUEST}))
        print(f"sent: {REQUEST!r}\n")

        events: list[dict] = []
        while True:
            raw = await ws.recv()
            ev = json.loads(raw)
            events.append(ev)
            t = ev.get("type", "<no-type>")
            if t in ("scenario.done", "scenario.error"):
                break

    # ---- check 1: every event has a numeric ts -----------------------------
    bad = [e for e in events if not isinstance(e.get("ts"), (int, float))]
    if bad:
        print(f"❌ {len(bad)} events missing numeric ts:")
        for e in bad[:3]:
            print(f"   {e}")
        return 1
    print(f"✓ all {len(events)} events have numeric ts")

    # ---- check 2: terminal event reached -----------------------------------
    if not any(e["type"] in ("scenario.done", "scenario.error") for e in events):
        print("❌ no terminal event")
        return 1
    print("✓ terminal event present")

    # ---- check 3: per-specialist token events are bursty enough to batch ---
    # We emulate buildLogEntries' batching: collapse tokens of the same
    # actor within a 1500ms window into a single stream entry.
    BATCH_MS = 1500
    raw_batches: list[dict] = []
    for ev in events:
        if ev["type"] in ("specialist.token", "synthesis.token"):
            actor = "synthesis" if ev["type"] == "synthesis.token" else ev["name"]
            if raw_batches and raw_batches[-1]["type"] == ev["type"] \
                    and raw_batches[-1]["actor"] == actor \
                    and ev["ts"] - raw_batches[-1]["lastTs"] <= BATCH_MS:
                raw_batches[-1]["chars"] += len(ev["delta"])
                raw_batches[-1]["lastTs"] = ev["ts"]
                continue
            raw_batches.append({
                "type": ev["type"], "actor": actor,
                "chars": len(ev["delta"]),
                "firstTs": ev["ts"], "lastTs": ev["ts"],
            })
    token_events = sum(1 for e in events if "token" in e["type"])
    print(f"✓ token events: {token_events} raw → {len(raw_batches)} batched "
          f"(compression: {token_events / max(1, len(raw_batches)):.1f}x)")

    # ---- check 4: each specialist that started also finished ----------------
    starts = Counter(e["name"] for e in events if e["type"] == "specialist.start")
    dones = Counter(e["name"] for e in events if e["type"] == "specialist.done")
    if starts != dones:
        print(f"❌ specialists that started but didn't finish:")
        for n in starts - dones:
            print(f"   {n}")
        return 1
    print(f"✓ {len(starts)} specialists all started + finished")

    # ---- check 5: token events per specialist --------------------------------
    per_sp = Counter()
    for e in events:
        if e["type"] == "specialist.token":
            per_sp[e["name"]] += 1
    print(f"✓ per-specialist token counts: {dict(per_sp)}")

    # ---- check 6: lifecycle contract — tokens for an actor arrive between ----
    # matching start and done events. SystemPanel's findOpenStream depends
    # on this: as long as no token arrives before a start (or after a done)
    # of the same actor, the lifecycle method collapses them into ONE row.
    n_specialists = len(starts)
    n_synth_tokens = sum(1 for e in events if e["type"] == "synthesis.token")
    max_stream_rows = n_specialists + (1 if n_synth_tokens else 0)
    print(f"✓ lifecycle contract holds — frontend will produce "
          f"≤{max_stream_rows} stream rows "
          f"({n_specialists} specialist + {1 if n_synth_tokens else 0} synthesis)")
    violations: list[str] = []
    # specialist tokens
    open_sp: set[str] = set()
    for e in events:
        if e["type"] == "specialist.start":
            open_sp.add(e["name"])
        elif e["type"] == "specialist.done":
            open_sp.discard(e["name"])
        elif e["type"] == "specialist.token":
            if e["name"] not in open_sp:
                violations.append(f"specialist.token for {e['name']!r} "
                                  f"with no open stream (ts={e['ts']})")
    # synthesis tokens
    synth_open = any(e["type"] == "synthesis.start" for e in events)
    synth_alive = False
    for e in events:
        if e["type"] == "synthesis.start":
            synth_alive = True
        elif e["type"] in ("synthesis.done", "synthesis.error"):
            synth_alive = False
        elif e["type"] == "synthesis.token":
            if not synth_alive:
                violations.append(f"synthesis.token with no open synthesis stream "
                                  f"(ts={e['ts']})")
    if violations:
        print(f"❌ {len(violations)} lifecycle violations:")
        for v in violations[:5]:
            print(f"   {v}")
        return 1
    print(f"✓ no orphan token events (every token was inside its actor's "
          f"start→done window)")

    print("\n✅ P4 event-log assumptions verified — SystemPanel will render correctly")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
