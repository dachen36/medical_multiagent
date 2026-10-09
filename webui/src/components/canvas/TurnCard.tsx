// One turn = one user question + assistant response (+ optional process trace).
//
// Lifted from the old ScenarioView.tsx's TurnCard, with the internal
// SourceBadge and formatTime helpers exported so SynthesisPanel can reuse
// them without redefining.

import { Markdown } from "../Markdown";
import type { Turn } from "../../api/client";
import { ProcessStepRow } from "./ProcessStepRow";

export function TurnCard({
  turn, color, isLive,
}: {
  turn: Turn;
  color: string;
  isLive: boolean;
}) {
  const duration = turn.finishedTs && turn.ts
    ? Math.max(0, Math.round((turn.finishedTs - turn.ts) / 1000))
    : null;

  return (
    <div style={{
      marginBottom: 20,
      padding: "16px 20px",
      border: `1px solid var(--border-soft)`,
      borderRadius: "var(--radius-md)",
      background: "var(--bg-card)",
      boxShadow: "var(--shadow-sm)",
      transition: "all 0.2s ease",
    }}>
      {/* turn meta row: time + source + status */}
      <div style={{
        display: "flex", gap: 10, alignItems: "center",
        fontSize: 11, color: "var(--text-faint)",
        marginBottom: 14,
      }}>
        <span style={{ fontFamily: "ui-monospace, monospace" }}>{formatTime(turn.ts)}</span>
        <SourceBadge source={turn.source} />
        {isLive && (
          <span style={{ 
            color: color, 
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}>
            <span className="status-dot running" />
            进行中
          </span>
        )}
        {turn.status === "error" && (
          <span style={{ 
            color: "var(--err)", 
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}>
            <span className="status-dot error" />
            出错
          </span>
        )}
        {turn.status === "done" && (
          <span style={{ 
            color: "var(--ok)", 
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}>
            <span className="status-dot done" />
            完成
          </span>
        )}
        {duration !== null && (
          <span style={{ 
            color: "var(--text-faint)",
            fontFamily: "ui-monospace, monospace",
          }}>
            · 用时 {duration}s
          </span>
        )}
      </div>

      {/* USER block: full-width, preserved line breaks, no truncation */}
      <div style={{
        padding: "12px 16px",
        background: "var(--bg-soft)",
        borderLeft: `3px solid ${color}`,
        borderRadius: "var(--radius-sm)",
        fontSize: 13,
        lineHeight: 1.6,
        color: "var(--text)",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        marginBottom: 14,
      }}>
        <div style={{
          fontSize: 10, fontWeight: 700, letterSpacing: 0.8,
          color: "var(--text-faint)", marginBottom: 6,
          textTransform: "uppercase",
        }}>
          用户
        </div>
        {turn.request || <span style={{ color: "var(--text-faint)" }}>(空)</span>}
      </div>

      {/* 思考过程 (collapsible) */}
      {turn.process.length > 0 && (
        <details open style={{
          background: "var(--bg-soft)",
          border: "1px solid var(--border-soft)",
          borderRadius: "var(--radius-sm)",
          padding: 12,
          marginBottom: 14,
        }}>
          <summary style={{
            fontSize: 11, fontWeight: 600, color: "var(--text-dim)",
            cursor: "pointer", userSelect: "none",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}>
            <span style={{ color, fontSize: 12 }}>⚙</span>
            思考过程 · {turn.process.length} 步
          </summary>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
            {turn.process.map((step) => (
              <ProcessStepRow key={step.id} step={step} color={color} />
            ))}
          </div>
        </details>
      )}

      {/* ASSISTANT label + result */}
      <div style={{
        fontSize: 10, fontWeight: 700, letterSpacing: 0.8,
        color: "var(--text-faint)", marginBottom: 6,
        textTransform: "uppercase",
      }}>
        助手
      </div>
      {turn.text ? (
        <div style={{
          padding: "8px 0",
          minHeight: 40,
        }}>
          <Markdown text={turn.text} className="md-body" />
          {isLive && (
            <span style={{
              display: "inline-block",
              width: 6, height: 15, marginLeft: 3,
              background: color,
              verticalAlign: "text-bottom",
              borderRadius: 2,
              animation: "pulse 1s ease-in-out infinite",
            }} />
          )}
        </div>
      ) : isLive ? (
        <span style={{ 
          color: "var(--text-faint)",
          fontSize: 14,
        }}>…</span>
      ) : null}

      {/* error banner */}
      {turn.status === "error" && (
        <div style={{
          marginTop: 12, padding: 12, fontSize: 11,
          color: "#991b1b", 
          background: "var(--err-soft)", 
          borderRadius: "var(--radius-sm)",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          fontFamily: "ui-monospace, monospace",
        }}>
          <div style={{ 
            fontWeight: 700, 
            marginBottom: 4,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}>
            <span>⚠</span>
            调用失败
          </div>
          {turn.errorDetail || "(no detail)"}
        </div>
      )}
    </div>
  );
}


/** Where a turn came from — "场景" (multi-agent scenario) or "独立" (standalone). */
export function SourceBadge({ source }: { source: Turn["source"] }) {
  const label = source === "scenario" ? "场景" : "独立";
  const color = source === "scenario" ? "var(--accent)" : "var(--text-dim)";
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 3,
      background: color, color: "#ffffff",
      fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
    }}>
      {label}
    </span>
  );
}


/** Format ms-epoch to "HH:MM:SS". */
export function formatTime(tsMs: number): string {
  const d = new Date(tsMs);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
