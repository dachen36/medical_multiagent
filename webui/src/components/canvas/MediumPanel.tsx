// MediumPanel — bento grid tile.
//
// One of 4 panels in BentoGrid's 2×2. Shows enough that the user can read
// each specialist's progress at a glance: header (avatar + name + status +
// edit button), latest 3 process steps (collapsible), and a truncated
// streaming text region. Char count footer for quick scanning.
//
// Click anywhere on the panel (outside buttons) → callback to spotlight it.

import React, { useDeferredValue, useEffect, useRef, useState } from "react";
import type { Agent } from "../../types";
import { displayName } from "../../types";
import { AgentIcon } from "../AgentIcon";
import { colorToVar } from "../../lib/agentColor";
import { CardStatusBadge, type CardStatus } from "./CardStatusBadge";
import { ProcessStepRow } from "./ProcessStepRow";
import type { Turn } from "../../api/client";

interface Props {
  agent: Agent;
  /** Latest turn for this specialist (null if no history). */
  turn: Turn | null;
  /** Dim this tile (coordinator mode: not yet dispatched). */
  dimmed?: boolean;
  /** Click handler — clicking the tile (NOT a button) calls this. */
  onSpotlight?: () => void;
  onEdit?: () => void;
}

function MediumPanelImpl({ agent, turn, dimmed, onSpotlight, onEdit }: Props) {
  const color = colorToVar(agent.color);
  const deferredText = useDeferredValue(turn?.text ?? "");
  const [isHovered, setIsHovered] = useState(false);
  
  const status: CardStatus = !turn
    ? "idle"
    : turn.status === "running"
    ? "running"
    : turn.status === "error"
    ? "error"
    : "done";
  const isLive = turn?.status === "running";
  const charCount = deferredText.length;
  const stepCount = turn?.process.length ?? 0;
  const latestSteps = turn?.process.slice(-3) ?? [];

  const textRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!isLive) return;
    const el = textRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [deferredText, isLive]);

  const isInteractive = onSpotlight && !dimmed;

  return (
    <div
      onClick={onSpotlight}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{
        height: "100%",
        border: `1px solid ${isLive ? color : "var(--border)"}`,
        borderRadius: "var(--radius-md)",
        background: "var(--bg-card)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        cursor: isInteractive ? "pointer" : "default",
        opacity: dimmed ? 0.5 : 1,
        boxShadow: isLive 
          ? `0 0 0 1px ${color}, 0 6px 20px rgba(0,0,0,0.08)` 
          : isHovered && isInteractive 
            ? "var(--shadow-md)" 
            : "none",
        transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
        transform: isHovered && isInteractive ? "translateY(-2px)" : "translateY(0)",
      }}
    >
      {/* color stripe along the top */}
      <div 
        style={{ 
          height: 3, 
          background: color, 
          flexShrink: 0,
          boxShadow: isLive ? `0 0 10px ${color}40` : "none",
        }} 
      />

      {/* header row */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "12px 16px 8px",
        flexShrink: 0,
      }}>
        <span 
          style={{ 
            color, 
            display: "inline-flex",
            padding: 4,
            borderRadius: "var(--radius-sm)",
            background: `${color}10`,
          }}
        >
          <AgentIcon name={agent.name} size={24} />
        </span>
        <span style={{
          fontWeight: 600, fontSize: 13, color: "var(--text)",
          flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }} title={agent.name}>
          {displayName(agent)}
        </span>
        <CardStatusBadge status={status} />
        {onEdit && (
          <button
            onClick={(e) => { e.stopPropagation(); onEdit(); }}
            title="编辑"
            className="icon-btn"
            style={{ padding: "2px 8px", fontSize: 12, lineHeight: 1.2 }}
          >
            ✎
          </button>
        )}
      </div>

      {/* latest process steps — collapsed by default, expand inline */}
      {latestSteps.length > 0 && (
        <details
          onClick={(e) => e.stopPropagation()}
          style={{
            margin: "0 16px 10px",
            background: "var(--bg-soft)",
            border: "1px solid var(--border-soft)",
            borderRadius: "var(--radius-sm)",
            padding: 8,
            flexShrink: 0,
          }}
        >
          <summary style={{
            fontSize: 10, fontWeight: 600, color: "var(--text-dim)",
            cursor: "pointer", userSelect: "none",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}>
            <span style={{ color }}>⚙</span>
            思考过程 · {stepCount} 步{stepCount > 3 ? "（仅显示最近 3 步）" : ""}
          </summary>
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
            {latestSteps.map((step) => (
              <ProcessStepRow key={step.id} step={step} color={color} />
            ))}
          </div>
        </details>
      )}

      {/* streaming text body (truncated to fixed height) */}
      <div
        ref={textRef}
        style={{
          flex: 1, minHeight: 0,
          padding: "0 16px",
          fontSize: 12, lineHeight: 1.6,
          color: "var(--text-dim)",
          overflow: "auto",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}
      >
        {deferredText || (
          <span style={{ 
            color: "var(--text-faint)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            height: "100%",
            padding: "12px 0",
          }}>
            {dimmed ? (
              <span>等待协调者派发…</span>
            ) : isLive ? (
              <span>正在思考…</span>
            ) : (
              <span>等待请求</span>
            )}
          </span>
        )}
        {isLive && deferredText && (
          <span style={{
            display: "inline-block",
            width: 6, height: 14, marginLeft: 2,
            background: color,
            verticalAlign: "text-bottom",
            borderRadius: 2,
            animation: "pulse 1s ease-in-out infinite",
          }} />
        )}
      </div>

      {/* error banner (inline) */}
      {turn?.status === "error" && (
        <div style={{
          margin: "10px 16px",
          padding: 10, fontSize: 11,
          color: "#991b1b", 
          background: "var(--err-soft)", 
          borderRadius: "var(--radius-sm)",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          fontFamily: "ui-monospace, monospace", 
          flexShrink: 0,
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>⚠ 调用失败</div>
          {turn.errorDetail || "(no detail)"}
        </div>
      )}

      {/* footer */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "8px 16px",
        borderTop: "1px solid var(--border-soft)",
        background: "var(--bg-soft)",
        fontSize: 10, color: "var(--text-faint)",
        flexShrink: 0,
      }}>
        <span>
          <span style={{ color, fontWeight: 600 }}>{agent.skills.length}</span> 技能
          <span> · </span>
          <span style={{ color, fontWeight: 600 }}>{agent.tools.length}</span> 工具
        </span>
        <span style={{ fontFamily: "ui-monospace, monospace", color: "var(--text-dim)" }}>
          {charCount.toLocaleString()} 字
        </span>
      </div>
    </div>
  );
}

/** Narrow comparator: only props that affect rendering, plus process length
 *  and last process step state (for the latest-3 collapsible). */
export const MediumPanel = React.memo(MediumPanelImpl, (prev, next) => {
  if (prev.agent.name !== next.agent.name) return false;
  if (prev.dimmed !== next.dimmed) return false;
  if (prev.onSpotlight !== next.onSpotlight) return false;
  if (prev.onEdit !== next.onEdit) return false;
  if (!!prev.turn !== !!next.turn) return false;
  if (!prev.turn || !next.turn) return true;
  // Text length captures every token; process length captures step add;
  // last step status captures tool_result freezing a running step.
  const pLast = prev.turn.process[prev.turn.process.length - 1];
  const nLast = next.turn.process[next.turn.process.length - 1];
  return (
    prev.turn.text.length === next.turn.text.length &&
    prev.turn.status === next.turn.status &&
    prev.turn.errorDetail === next.turn.errorDetail &&
    prev.turn.process.length === next.turn.process.length &&
    pLast?.status === nLast?.status &&
    pLast?.is_error === nLast?.is_error
  );
});
