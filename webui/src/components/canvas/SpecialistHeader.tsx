// Per-specialist header strip — agent name, status, char count, edit/clear buttons.
//
// Lifted from the old ScenarioView.tsx's SpecialistHeader.
// Used by LargePanel (spotlight main area) and standalone in tests/dev tools.

import type { Agent } from "../../types";
import { displayName } from "../../types";
import { AgentIcon } from "../AgentIcon";
import { CardStatusBadge, type CardStatus } from "./CardStatusBadge";

interface Props {
  agent: Agent;
  color: string;
  status: CardStatus;
  textLen: number;
  turnCount?: number;
  onEdit?: () => void;
  onClearHistory?: () => void;
  /** P-canvas: extra buttons for spotlight large mode. */
  rightExtra?: React.ReactNode;
}

export function SpecialistHeader({
  agent, color, status, textLen, turnCount, onEdit, onClearHistory, rightExtra,
}: Props) {
  return (
    <div style={{
      padding: "8px 18px",
      borderBottom: "1px solid var(--border-soft)",
      display: "flex", alignItems: "center", gap: 10,
      background: "var(--bg-soft)",
      flexShrink: 0,
    }}>
      <span style={{ color, display: "inline-flex" }}>
        <AgentIcon name={agent.name} size={20} />
      </span>
      <span style={{ fontWeight: 600, fontSize: 13, color: "var(--text)" }} title={agent.name}>
        {displayName(agent)}
      </span>
      <CardStatusBadge status={status} />
      {turnCount !== undefined && turnCount > 0 && (
        <span style={{
          fontSize: 10, color: "var(--text-faint)",
          fontFamily: "ui-monospace, monospace",
        }}>
          · {turnCount} 轮
        </span>
      )}
      <span style={{
        marginLeft: "auto", fontSize: 10, color: "var(--text-faint)",
        fontFamily: "ui-monospace, monospace",
      }}>
        {textLen} 字
      </span>
      {rightExtra}
      {onEdit && (
        <button
          onClick={onEdit}
          title="编辑"
          style={{ padding: "1px 8px", fontSize: 11, lineHeight: 1.2 }}
        >
          ✎
        </button>
      )}
      {onClearHistory && (
        <button
          onClick={onClearHistory}
          title="清空对话历史"
          style={{ padding: "1px 8px", fontSize: 11, lineHeight: 1.2, color: "var(--err)" }}
        >
          🗑
        </button>
      )}
    </div>
  );
}
