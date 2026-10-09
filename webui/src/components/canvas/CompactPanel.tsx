// CompactPanel — minimal specialist tile.
//
// Used by:
//   - SidePanelStack (spotlight's right column — 3 tiles, 1/3 height each)
//   - SpecialistDock (synthesis bottom strip — 4 tiles in a row)
//
// Renders only: avatar + name + 1-line latest text preview + status dot.
// Streams "feel" live by re-rendering text length without parsing Markdown
// — cheapest possible per-token update.
//
// React.memo with a narrow comparator: a stream of `specialist.token` for
// agent A re-renders only A's tile, not the other 3.

import React, { useDeferredValue } from "react";
import type { Agent } from "../../types";
import { displayName } from "../../types";
import { AgentIcon } from "../AgentIcon";
import { colorToVar } from "../../lib/agentColor";
import { CardStatusBadge, type CardStatus } from "./CardStatusBadge";
import type { Turn } from "../../api/client";

interface Props {
  agent: Agent;
  /** Latest turn (null if the agent has no history yet). */
  turn: Turn | null;
  /** Visual highlight (used in SpotlightView's right column to dim the
   *  currently-spotlighted agent's own mini-tile). */
  isCurrent?: boolean;
  /** Dim the tile (e.g., coordinator mode: not yet dispatched). */
  dimmed?: boolean;
  onClick?: () => void;
}

function CompactPanelImpl({ agent, turn, isCurrent, dimmed, onClick }: Props) {
  const color = colorToVar(agent.color);
  const deferredText = useDeferredValue(turn?.text ?? "");
  const status: CardStatus = !turn
    ? "idle"
    : turn.status === "running"
    ? "running"
    : turn.status === "error"
    ? "error"
    : "done";

  // 1-line preview of the latest text (tail-biased so the cursor area is visible)
  const preview = deferredText
    ? deferredText.length > 60
      ? "…" + deferredText.slice(-60)
      : deferredText
    : dimmed
    ? "等待派发"
    : turn?.status === "running"
    ? "正在思考…"
    : "";

  return (
    <div
      onClick={onClick}
      style={{
        height: "100%",
        border: `1px solid ${isCurrent ? color : "var(--border)"}`,
        borderRadius: 8,
        background: isCurrent ? "var(--accent-soft)" : "var(--bg)",
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        cursor: onClick ? "pointer" : "default",
        opacity: dimmed ? 0.45 : 1,
        boxShadow: isCurrent ? `0 0 0 1px ${color}` : "none",
        transition: "border-color 0.15s, background 0.15s, opacity 0.2s",
        overflow: "hidden",
      }}
      onMouseEnter={(e) => {
        if (!isCurrent && onClick && !dimmed) e.currentTarget.style.background = "var(--bg-elev)";
      }}
      onMouseLeave={(e) => {
        if (!isCurrent) e.currentTarget.style.background = "var(--bg)";
      }}
      title={agent.name}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color, display: "inline-flex" }}>
          <AgentIcon name={agent.name} size={18} />
        </span>
        <span style={{
          fontWeight: 600, fontSize: 12, color: "var(--text)",
          flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {displayName(agent)}
        </span>
        <CardStatusBadge status={status} />
      </div>
      <div style={{
        flex: 1,
        fontSize: 11,
        lineHeight: 1.4,
        color: "var(--text-faint)",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        fontFamily: deferredText ? "ui-monospace, monospace" : undefined,
      }}>
        {preview}
        {turn?.status === "running" && deferredText && (
          <span style={{
            display: "inline-block",
            width: 4, height: 9, marginLeft: 2,
            background: color,
            verticalAlign: "text-bottom",
            animation: "pulse 0.9s ease-in-out infinite",
          }} />
        )}
      </div>
      {turn?.status === "error" && (
        <div style={{
          fontSize: 10, color: "var(--err)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          ⚠ {turn.errorDetail?.slice(0, 50) ?? "出错"}
        </div>
      )}
    </div>
  );
}

/** Narrow memo comparator: only re-render when something visible to compact
 *  view changes. Crucially, we compare text *length* not text content — the
 *  preview is a tail slice so length is sufficient to detect "new tokens". */
export const CompactPanel = React.memo(CompactPanelImpl, (prev, next) =>
  prev.agent.name === next.agent.name &&
  prev.isCurrent === next.isCurrent &&
  prev.dimmed === next.dimmed &&
  prev.onClick === next.onClick &&
  (prev.turn?.text.length ?? 0) === (next.turn?.text.length ?? 0) &&
  prev.turn?.status === next.turn?.status &&
  prev.turn?.errorDetail === next.turn?.errorDetail
);
