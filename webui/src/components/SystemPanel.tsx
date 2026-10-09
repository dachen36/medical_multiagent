// Left column: system observability content.
//
// Three sections, all derived from the same `events: ScenarioEvent[]` stream:
//   1. 状态概览  — current phase + elapsed time + token count
//   2. 任务清单  — high-level checklist of the run (plan, specialists, synthesis)
//   3. 事件流   — chronological log with token-stream batching
//
// P-canvas: this file used to render a fixed-width 280px `<aside>` directly.
// We now expose two things:
//   - SystemPanelContent — pure content, no outer chrome, fills its parent
//   - SystemPanel        — backward-compat wrapper that renders SystemPanelContent
//                          inside the original 280px aside (for tests / dev)
// The new SystemRail component (canvas/) renders SystemPanelContent inside
// its overlay when expanded; the collapsed 48px rail shows a low-cost
// mini status indicator built from the same `events` array.

import { useEffect, useMemo, useRef, useState } from "react";
import type { ScenarioEvent } from "../api/client";
import type { Agent } from "../types";
import { displayName } from "../types";
import { colorToVar } from "../lib/agentColor";

// ---------------------------------------------------------------------------
// Log entry — a "compressed" view of raw events.
// Token events are coalesced into ONE "stream" entry per (actor, lifecycle):
//   - new stream opens on the first token after the matching .start
//   - subsequent tokens update the same entry's chars counter in place
//   - the matching .done / .error "freezes" the entry (closes the stream)
// So a 4-specialist + 1-synthesis run produces AT MOST 5 stream rows.
// ---------------------------------------------------------------------------
export type LogEntry =
  | { kind: "event"; ts: number; type: string; actor?: string; detail?: string }
  | { kind: "stream"; ts: number; type: "specialist.token" | "synthesis.token"; actor: string; chars: number; live: boolean };

/** Find the most recent stream entry for the same (type, actor) that hasn't
 *  been closed by a terminal event yet. Returns null if the stream is closed
 *  (or no stream exists).
 */
function findOpenStream(
  entries: LogEntry[],
  type: "specialist.token" | "synthesis.token",
  actor: string,
): LogEntry | null {
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i];
    if (e.kind === "stream" && e.type === type && e.actor === actor) {
      return e;
    }
    if (e.kind === "event") {
      if (type === "specialist.token") {
        if (e.type === "specialist.done" && e.actor === actor) return null;
        if (e.type === "specialist.error" && e.actor === actor) return null;
      }
      if (type === "synthesis.token") {
        if (e.type === "synthesis.done") return null;
        if (e.type === "synthesis.error") return null;
      }
    }
  }
  return null;
}

export function buildLogEntries(events: ScenarioEvent[]): LogEntry[] {
  const out: LogEntry[] = [];
  for (const ev of events) {
    if (ev.type === "specialist.token") {
      const open = findOpenStream(out, "specialist.token", ev.name);
      if (open && open.kind === "stream") {
        open.chars += ev.delta.length;
        continue;
      }
      out.push({
        kind: "stream",
        ts: ev.ts,
        type: "specialist.token",
        actor: ev.name,
        chars: ev.delta.length,
        live: true,
      });
      continue;
    }
    if (ev.type === "synthesis.token") {
      const open = findOpenStream(out, "synthesis.token", "synthesis");
      if (open && open.kind === "stream") {
        open.chars += ev.delta.length;
        continue;
      }
      out.push({
        kind: "stream",
        ts: ev.ts,
        type: "synthesis.token",
        actor: "synthesis",
        chars: ev.delta.length,
        live: true,
      });
      continue;
    }
    if (ev.type === "specialist.done" || ev.type === "specialist.error") {
      const open = findOpenStream(out, "specialist.token", ev.name);
      if (open && open.kind === "stream") open.live = false;
    }
    if (ev.type === "synthesis.done" || ev.type === "synthesis.error") {
      const open = findOpenStream(out, "synthesis.token", "synthesis");
      if (open && open.kind === "stream") open.live = false;
    }

    let actor: string | undefined;
    let detail: string | undefined;
    if (ev.type === "specialist.start" || ev.type === "specialist.done" || ev.type === "specialist.error") {
      actor = ev.name;
    }
    if (ev.type === "specialist.error") detail = ev.detail;
    if (ev.type === "synthesis.error") detail = ev.detail;
    if (ev.type === "synthesis.done") detail = `${ev.text.length} 字`;
    if (ev.type === "specialist.done") detail = `${ev.text.length} 字`;
    if (ev.type === "scenario.done") detail = ev.status;
    if (ev.type === "scenario.error") detail = ev.detail;
    if (ev.type === "error") detail = ev.detail;
    const ts = ev.ts ?? Date.now();
    const entry: LogEntry = actor !== undefined || detail !== undefined
      ? { kind: "event", ts, type: ev.type, actor, detail }
      : { kind: "event", ts, type: ev.type };
    out.push(entry);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Lightweight per-specialist progress digest — used by SystemRail's
// collapsed mini-checklist. Pure function of `events`; returned shape is
// deliberately small so SystemRail can render without re-allocating.
// ---------------------------------------------------------------------------
export type SpecialistProgressState = "pending" | "running" | "done" | "error";
export interface TaskProgress {
  label: string;       // "规划" / agent display name / "综合报告"
  color?: string;      // CSS color (for specialist row)
  state: SpecialistProgressState;
}

export function buildTaskProgress(
  events: ScenarioEvent[],
  specialists: Agent[],
  status: Status,
): TaskProgress[] {
  const out: TaskProgress[] = [];
  const started = events.some((e) => e.type === "scenario.start");
  out.push({
    label: "规划",
    state: started ? "done" : status === "planning" ? "running" : "pending",
  });
  for (const a of specialists) {
    const ev = lastSpecialistEvent(events, a.name);
    out.push({
      label: displayName(a),
      color: colorToVar(a.color),
      state:
        ev === "error" ? "error" :
        ev === "done"  ? "done" :
        ev === "start" ? "running" : "pending",
    });
  }
  const synthesisDone = events.some((e) => e.type === "synthesis.done");
  const synthesisStarted = events.some((e) => e.type === "synthesis.start");
  out.push({
    label: "综合报告",
    state:
      synthesisDone ? "done" :
      synthesisStarted ? "running" : "pending",
  });
  return out;
}

// ---------------------------------------------------------------------------
// Component (content variant — no outer frame)
// ---------------------------------------------------------------------------
type Status = "idle" | "planning" | "running" | "synthesizing" | "done" | "error";

interface Props {
  events: ScenarioEvent[];
  status: Status;
  specialists: Agent[];
  tokens: number;
  query: string | null;
  /** When the current run started (timestamp ms). null when idle. */
  startedAt: number | null;
}

const STATUS_META: Record<Status, { label: string; color: string; pulse?: boolean }> = {
  idle:         { label: "空闲",       color: "var(--text-faint)" },
  planning:     { label: "规划中",     color: "var(--accent)" },
  running:      { label: "运行中",     color: "var(--accent)", pulse: true },
  synthesizing: { label: "汇总中",     color: "var(--c-purple)", pulse: true },
  done:         { label: "完成",       color: "var(--ok)" },
  error:        { label: "出错",       color: "var(--err)" },
};

/** Pure content (no `aside` chrome). Renders inside the SystemRail overlay. */
export function SystemPanelContent({
  events, status, specialists, tokens, query, startedAt,
}: Props) {
  const logEntries = useMemo(() => buildLogEntries(events), [events]);

  const [now] = useNowEverySecond(status !== "idle" && status !== "done" && status !== "error");

  const elapsedMs = startedAt && now > startedAt ? now - startedAt : 0;
  const elapsedLabel = formatElapsed(elapsedMs);

  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [logEntries.length]);

  const started = events.some((e) => e.type === "scenario.start");
  const anySpecialistStarted = events.some((e) => e.type === "specialist.start");
  const synthesisStarted = events.some((e) => e.type === "synthesis.start");
  const synthesisDone = events.some((e) => e.type === "synthesis.done");

  const taskCount = 2 + specialists.length;
  const tasksDone =
    (started ? 1 : 0) +
    specialists.filter((a) =>
      events.some((e) => e.type === "specialist.done" && e.name === a.name)
    ).length +
    (synthesisDone ? 1 : 0);

  const statusMeta = STATUS_META[status];

  return (
    <div style={{
      display: "flex", flexDirection: "column",
      height: "100%",
      background: "var(--bg-soft)",
      overflow: "hidden",
    }}>
      {/* ---- 状态概览 -------------------------------------------------- */}
      <div style={{
        padding: "12px 14px",
        borderBottom: "1px solid var(--border-soft)",
        background: "var(--bg)",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <span style={{
            width: 8, height: 8, borderRadius: 4,
            background: statusMeta.color,
            flexShrink: 0,
            animation: statusMeta.pulse ? "pulse 1.2s ease-in-out infinite" : undefined,
          }} />
          <span style={{ fontSize: 13, fontWeight: 700, color: statusMeta.color }}>
            {statusMeta.label}
          </span>
          {started && (
            <span style={{ fontSize: 10, color: "var(--text-faint)", marginLeft: "auto" }}>
              {tasksDone}/{taskCount} 完成
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 12, fontSize: 10, color: "var(--text-faint)" }}>
          <span>⏱ {elapsedLabel}</span>
          <span>📊 {tokens.toLocaleString()} tokens</span>
          <span>📋 {logEntries.length} 事件</span>
        </div>
        {query && (
          <div style={{
            marginTop: 8, padding: "6px 8px",
            background: "var(--bg-elev)", borderRadius: 4,
            fontSize: 10, color: "var(--text-dim)",
            lineHeight: 1.4, maxHeight: 36, overflow: "hidden",
            textOverflow: "ellipsis",
            display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          }} title={query}>
            {query}
          </div>
        )}
      </div>

      {/* ---- 任务清单 ------------------------------------------------- */}
      <div style={{
        padding: "10px 12px",
        borderBottom: "1px solid var(--border-soft)",
        flexShrink: 0,
      }}>
        <div style={{
          fontSize: 10, fontWeight: 700, letterSpacing: 1.2,
          color: "var(--text-faint)", textTransform: "uppercase",
          marginBottom: 6,
        }}>
          任务清单
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <TaskRow
            label="规划"
            state={started ? "done" : (status === "planning" ? "running" : "pending")}
          />
          {specialists.map((a) => {
            const ev = lastSpecialistEvent(events, a.name);
            const state =
              ev === "error"   ? "error" :
              ev === "done"    ? "done" :
              ev === "start"   ? "running" :
              anySpecialistStarted ? "pending" : "pending";
            return (
              <TaskRow
                key={a.name}
                label={displayName(a)}
                color={colorToVar(a.color)}
                state={state}
                detail={specialistChars(events, a.name)}
              />
            );
          })}
          <TaskRow
            label="综合报告"
            state={
              synthesisDone ? "done" :
              synthesisStarted ? "running" :
              (started ? "pending" : "pending")
            }
            detail={synthesisDone ? `${synthChars(events)} 字` : undefined}
          />
        </div>
      </div>

      {/* ---- 事件流 -------------------------------------------------- */}
      <div style={{
        flex: 1, overflow: "hidden",
        display: "flex", flexDirection: "column",
      }}>
        <div style={{
          padding: "8px 12px 4px",
          fontSize: 10, fontWeight: 700, letterSpacing: 1.2,
          color: "var(--text-faint)", textTransform: "uppercase",
          flexShrink: 0,
        }}>
          事件流
        </div>
        <div ref={logRef} style={{
          flex: 1, overflowY: "auto",
          padding: "0 8px 8px",
          fontSize: 10, fontFamily: "ui-monospace, monospace",
          lineHeight: 1.5,
        }}>
          {logEntries.length === 0 ? (
            <div style={{ color: "var(--text-faint)", textAlign: "center", padding: 16, fontSize: 11 }}>
              等待事件…
            </div>
          ) : (
            logEntries.map((e, i) => <LogRow key={i} entry={e} />)
          )}
        </div>
      </div>
    </div>
  );
}

/** Backward-compat wrapper: original 280px fixed aside. Not used by the
 *  canvas redesign (SystemRail handles its own chrome) but kept for tests
 *  and incremental migration. */
export function SystemPanel(props: Props) {
  return (
    <aside style={{
      width: 280, flexShrink: 0,
      borderRight: "1px solid var(--border)",
      background: "var(--bg-soft)",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      <SystemPanelContent {...props} />
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function TaskRow({ label, state, color, detail }: {
  label: string;
  state: "pending" | "running" | "done" | "error";
  color?: string;
  detail?: string;
}) {
  const icon =
    state === "done"    ? "✓" :
    state === "running" ? "●" :
    state === "error"   ? "✗" : "○";
  const iconColor =
    state === "done"    ? "var(--ok)" :
    state === "running" ? (color ?? "var(--accent)") :
    state === "error"   ? "var(--err)" : "var(--text-faint)";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6,
      fontSize: 11,
      color: state === "pending" ? "var(--text-faint)" : "var(--text)",
    }}>
      <span style={{
        width: 12, textAlign: "center",
        color: iconColor, fontWeight: 700,
        animation: state === "running" ? "pulse 1.2s ease-in-out infinite" : undefined,
      }}>
        {icon}
      </span>
      <span style={{
        flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {label}
      </span>
      {detail && (
        <span style={{ color: "var(--text-faint)", fontSize: 10 }}>{detail}</span>
      )}
    </div>
  );
}

function LogRow({ entry }: { entry: LogEntry }) {
  const time = formatTime(entry.ts);
  if (entry.kind === "stream") {
    const liveColor = entry.type === "synthesis.token" ? "var(--c-purple)" : "var(--accent)";
    return (
      <div style={{ color: "var(--text-faint)", padding: "1px 0" }}>
        <span style={{ color: "var(--text-faint)" }}>{time}</span>{" "}
        <span style={{ color: liveColor }}>↳</span>{" "}
        {entry.actor}{" "}
        <span style={{ color: "var(--text)" }}>{entry.chars.toLocaleString()} 字</span>{" "}
        {entry.live ? (
          <span style={{
            color: liveColor,
            animation: "pulse 1.2s ease-in-out infinite",
          }}>●</span>
        ) : (
          <span style={{ color: "var(--ok)" }}>✓</span>
        )}
      </div>
    );
  }
  const meta = describeEvent(entry.type);
  return (
    <div style={{ color: meta.color, padding: "1px 0" }}>
      <span style={{ color: "var(--text-faint)" }}>{time}</span>{" "}
      <span>{meta.icon}</span>{" "}
      <span style={{ fontWeight: 600 }}>{meta.label}</span>
      {entry.actor && <span style={{ color: "var(--text-dim)" }}> {entry.actor}</span>}
      {entry.detail && (
        <span style={{ color: "var(--text-faint)", marginLeft: 4 }}>{entry.detail}</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatElapsed(ms: number): string {
  if (ms <= 0) return "00:00";
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function describeEvent(type: string): {
  icon: string; label: string; color: string;
} {
  switch (type) {
    case "scenario.start":    return { icon: "▶",  label: "scenario.start",    color: "var(--accent)" };
    case "specialist.start":  return { icon: "→",  label: "specialist.start",  color: "var(--text-dim)" };
    case "specialist.done":   return { icon: "✓",  label: "specialist.done",   color: "var(--ok)" };
    case "specialist.error":  return { icon: "✗",  label: "specialist.error",  color: "var(--err)" };
    case "synthesis.start":   return { icon: "→",  label: "synthesis.start",   color: "var(--c-purple)" };
    case "synthesis.done":    return { icon: "✓",  label: "synthesis.done",    color: "var(--ok)" };
    case "synthesis.error":   return { icon: "✗",  label: "synthesis.error",   color: "var(--err)" };
    case "scenario.done":     return { icon: "■",  label: "scenario.done",     color: "var(--ok)" };
    case "scenario.error":    return { icon: "✗",  label: "scenario.error",    color: "var(--err)" };
    case "error":             return { icon: "✗",  label: "error",             color: "var(--err)" };
    default:                  return { icon: "·",  label: type,                color: "var(--text-faint)" };
  }
}

function lastSpecialistEvent(events: ScenarioEvent[], name: string): "start" | "done" | "error" | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "specialist.done" && e.name === name) return "done";
    if (e.type === "specialist.error" && e.name === name) return "error";
    if (e.type === "specialist.start" && e.name === name) return "start";
  }
  return null;
}

function specialistChars(events: ScenarioEvent[], name: string): string | undefined {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "specialist.done" && e.name === name) return `${e.text.length} 字`;
  }
  return undefined;
}

function synthChars(events: ScenarioEvent[]): number {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "synthesis.done") return e.text.length;
  }
  return 0;
}

// Local hook: 1Hz ticker that pauses when `active` is false.
export function useNowEverySecond(active: boolean): [number, (n: number) => void] {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return [now, setNow];
}
