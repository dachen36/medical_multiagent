// SystemRail — the new left column that replaces the always-on SystemPanel.
//
// Two states, controlled by the parent:
//   • collapsed (48px) — minimal vertical sidebar with status dot (pulse),
//     elapsed time, token count, event count, and 5 mini task dots showing
//     plan / 4 specialist / synthesis progress at a glance. Always rendered.
//   • expanded (280px overlay) — full SystemPanelContent. Positioned absolute
//     over the canvas so it doesn't shift the layout. Click outside / Esc
//     collapses it back.
//
// While collapsed we DO NOT instantiate SystemPanelContent so the 1Hz
// `useNowEverySecond` ticker doesn't fire — only the mini status indicator
// (also re-rendering every second) runs.

import { useEffect, useRef } from "react";
import type { ScenarioEvent } from "../../api/client";
import type { Agent } from "../../types";
import {
  SystemPanelContent,
  buildTaskProgress,
  useNowEverySecond,
  type TaskProgress,
} from "../SystemPanel";
import { useOutsideClick } from "../../hooks/useOutsideClick";

type Status = "idle" | "planning" | "running" | "synthesizing" | "done" | "error";

interface Props {
  events: ScenarioEvent[];
  status: Status;
  specialists: Agent[];
  tokens: number;
  query: string | null;
  startedAt: number | null;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}

const STATUS_COLOR: Record<Status, { color: string; pulse: boolean }> = {
  idle:         { color: "var(--text-faint)", pulse: false },
  planning:     { color: "var(--accent)",     pulse: true },
  running:      { color: "var(--accent)",     pulse: true },
  synthesizing: { color: "var(--c-purple)",   pulse: true },
  done:         { color: "var(--ok)",         pulse: false },
  error:        { color: "var(--err)",        pulse: false },
};

export function SystemRail({
  events, status, specialists, tokens, query, startedAt,
  open, onOpen, onClose,
}: Props) {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  useOutsideClick(overlayRef, onClose, open);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  return (
    <>
      <CollapsedRail
        events={events}
        status={status}
        specialists={specialists}
        tokens={tokens}
        startedAt={startedAt}
        onOpen={onOpen}
      />
      {open && (
        <div
          ref={overlayRef}
          style={{
            position: "absolute",
            top: 0, bottom: 0, left: 48,
            width: 280,
            zIndex: 100,
            boxShadow: "4px 0 12px rgba(15, 23, 42, 0.08)",
            borderRight: "1px solid var(--border)",
            animation: "slideUp 0.2s ease-out both",
          }}
        >
          <SystemPanelContent
            events={events}
            status={status}
            specialists={specialists}
            tokens={tokens}
            query={query}
            startedAt={startedAt}
          />
        </div>
      )}
    </>
  );
}


/** Collapsed 48px sidebar. Renders status dot + tokens + event count +
 *  mini task dots in a vertical column. Always visible. */
function CollapsedRail({
  events, status, specialists, tokens, startedAt, onOpen,
}: {
  events: ScenarioEvent[];
  status: Status;
  specialists: Agent[];
  tokens: number;
  startedAt: number | null;
  onOpen: () => void;
}) {
  const meta = STATUS_COLOR[status];
  const progress: TaskProgress[] = buildTaskProgress(events, specialists, status);
  const isActive = status !== "idle" && status !== "done" && status !== "error";

  const [now] = useNowEverySecond(isActive);
  const elapsedSec = startedAt && now > startedAt
    ? Math.floor((now - startedAt) / 1000)
    : 0;

  return (
    <aside
      onClick={onOpen}
      title="点击展开观测面板（事件流 / 任务清单）"
      style={{
        width: 48, flexShrink: 0,
        background: "var(--bg-soft)",
        borderRight: "1px solid var(--border)",
        display: "flex", flexDirection: "column",
        alignItems: "center",
        padding: "10px 0",
        gap: 14,
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      {/* status dot */}
      <span style={{
        width: 12, height: 12, borderRadius: "50%",
        background: meta.color,
        animation: meta.pulse ? "pulse 1.2s ease-in-out infinite" : undefined,
        boxShadow: meta.pulse ? `0 0 6px ${meta.color}` : "none",
      }} />

      {/* tokens count (small) */}
      <div style={{
        fontSize: 9, fontWeight: 600,
        color: "var(--text-dim)",
        fontFamily: "ui-monospace, monospace",
        writingMode: "vertical-rl",
        transform: "rotate(180deg)",
        letterSpacing: 1,
      }}>
        {tokens > 999 ? `${(tokens / 1000).toFixed(1)}k` : tokens || "—"} tok
      </div>

      {/* elapsed (only while active) */}
      {isActive && elapsedSec > 0 && (
        <div style={{
          fontSize: 9, color: "var(--text-faint)",
          fontFamily: "ui-monospace, monospace",
        }} title={`已用 ${elapsedSec}s`}>
          {formatElapsedShort(elapsedSec)}
        </div>
      )}

      {/* mini task dots — 5+ dots, one per task (plan + N specialists + synthesis) */}
      <div style={{
        display: "flex", flexDirection: "column",
        gap: 5, marginTop: 4,
      }}>
        {progress.map((t, i) => (
          <span
            key={i}
            title={`${t.label} · ${stateLabel(t.state)}`}
            style={{
              width: 8, height: 8, borderRadius: "50%",
              background: dotColor(t),
              animation: t.state === "running"
                ? "pulse 1.2s ease-in-out infinite"
                : undefined,
              boxShadow: t.state === "running" ? `0 0 4px ${dotColor(t)}` : "none",
            }}
          />
        ))}
      </div>

      {/* event count (small badge at bottom) */}
      <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
        {events.length > 0 && (
          <span style={{
            fontSize: 9, color: "var(--text-faint)",
            fontFamily: "ui-monospace, monospace",
          }} title={`${events.length} 个事件`}>
            {events.length}
          </span>
        )}
        <span style={{
          color: "var(--text-faint)", fontSize: 14, lineHeight: 1,
        }} title="展开">
          ›
        </span>
      </div>
    </aside>
  );
}


function dotColor(t: TaskProgress): string {
  if (t.state === "error") return "var(--err)";
  if (t.state === "done") return "var(--ok)";
  if (t.state === "running") return t.color ?? "var(--accent)";
  return "var(--border)";
}

function stateLabel(s: TaskProgress["state"]): string {
  return s === "done" ? "完成" : s === "running" ? "运行中" : s === "error" ? "出错" : "等待";
}

function formatElapsedShort(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const r = sec % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}
