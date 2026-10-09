// LargePanel — the spotlight main area.
//
// Full timeline view of one specialist: header (with "独立对话" / "清空历史" /
// "返回总览" buttons), then a scrollable list of TurnCards (one per
// historical turn, oldest first, newest at the bottom with the live cursor).
//
// The "独立对话" button toggles a standaloneAgent state in App; while it's
// on, the InputBar at the bottom of the canvas accepts messages routed to
// /ws/specialist instead of /ws/scenario.

import React, { useEffect, useRef } from "react";
import type { Agent } from "../../types";
import { displayName } from "../../types";
import { AgentIcon } from "../AgentIcon";
import { colorToVar } from "../../lib/agentColor";
import { SpecialistHeader } from "./SpecialistHeader";
import { TurnCard } from "./TurnCard";
import type { Turn } from "../../api/client";

interface Props {
  agent: Agent;
  /** Full chronological list of turns for this specialist. */
  turns: Turn[];
  /** Whether a standalone-chat WS is currently open for THIS agent. */
  standaloneActive?: boolean;
  /** Callback: collapse back to BentoGrid. */
  onBackToBento?: () => void;
  /** Callback: toggle standalone-chat mode for this agent.
   *  Passing the agent name lets the parent set `standaloneAgent`. */
  onToggleStandalone?: () => void;
  /** Callback: cancel an in-flight standalone run for this agent. */
  onCancelStandalone?: () => void;
  /** Callback: clear server-side conversation history. */
  onClearHistory?: () => void;
  /** Callback: open the AgentEditor modal. */
  onEdit?: () => void;
}

function LargePanelImpl({
  agent, turns,
  standaloneActive, onBackToBento, onToggleStandalone, onCancelStandalone,
  onClearHistory, onEdit,
}: Props) {
  const color = colorToVar(agent.color);
  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const isLive = lastTurn?.status === "running";
  const totalChars = turns.reduce((acc, t) => acc + t.text.length, 0);

  // Auto-scroll to bottom while live
  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!isLive) return;
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, isLive]);

  return (
    <div style={{
      display: "flex", flexDirection: "column", height: "100%",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 10,
      overflow: "hidden",
    }}>
      <SpecialistHeader
        agent={agent}
        color={color}
        status={
          isLive ? "running"
          : lastTurn?.status === "error" ? "error"
          : turns.length > 0 ? "done" : "idle"
        }
        textLen={totalChars}
        turnCount={turns.length}
        onEdit={onEdit}
        onClearHistory={turns.length > 0 ? onClearHistory : undefined}
        rightExtra={
          <>
            {onToggleStandalone && (
              <button
                onClick={onToggleStandalone}
                title={standaloneActive ? "退出独立对话" : "与该智能体独立对话（不触发其他 3 位）"}
                style={{
                  padding: "1px 10px", fontSize: 11, lineHeight: 1.2,
                  color: standaloneActive ? "#ffffff" : "var(--accent-dim)",
                  background: standaloneActive ? "var(--accent)" : "transparent",
                  borderColor: "var(--accent)",
                }}
              >
                {standaloneActive ? "退出独立" : "独立对话"}
              </button>
            )}
            {standaloneActive && isLive && onCancelStandalone && (
              <button
                onClick={onCancelStandalone}
                style={{ padding: "1px 8px", fontSize: 11, color: "var(--err)" }}
              >
                取消
              </button>
            )}
            {onBackToBento && (
              <button
                onClick={onBackToBento}
                title="返回总览（Esc）"
                style={{ padding: "1px 8px", fontSize: 11, lineHeight: 1.2 }}
              >
                ⛶ 返回总览
              </button>
            )}
          </>
        }
      />

      <div
        ref={bodyRef}
        className="panel-content--mount"
        style={{
          flex: 1, overflow: "auto",
          padding: "16px 24px",
          fontSize: 13, lineHeight: 1.7,
          color: "var(--text)",
        }}
      >
        {turns.length === 0 ? (
          <div style={{
            minHeight: 240,
            display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center",
            color: "var(--text-faint)", fontSize: 12,
            padding: 24, textAlign: "center",
          }}>
            <div style={{ color, marginBottom: 12 }}>
              <AgentIcon name={agent.name} size={48} />
            </div>
            <div style={{
              color: "var(--text-dim)", fontWeight: 500, marginBottom: 4,
            }} title={agent.name}>
              {displayName(agent)}
            </div>
            <div style={{ fontSize: 11 }}>
              {standaloneActive
                ? "在下方输入提问，开始多轮对话"
                : "等待被场景调度。开启「独立对话」可直接提问。"}
            </div>
          </div>
        ) : (
          turns.map((turn, idx) => (
            <TurnCard
              key={turn.id}
              turn={turn}
              color={color}
              isLive={isLive && idx === turns.length - 1}
            />
          ))
        )}
        {/* spacer so the last turn's pulsing cursor doesn't clip */}
        {isLive && <div style={{ height: 24 }} />}
      </div>
    </div>
  );
}

/** Comparator: re-render when turn list grows, last turn streams, or
 *  callbacks change. */
export const LargePanel = React.memo(LargePanelImpl, (prev, next) => {
  if (prev.agent.name !== next.agent.name) return false;
  if (prev.standaloneActive !== next.standaloneActive) return false;
  if (prev.onBackToBento !== next.onBackToBento) return false;
  if (prev.onToggleStandalone !== next.onToggleStandalone) return false;
  if (prev.onCancelStandalone !== next.onCancelStandalone) return false;
  if (prev.onClearHistory !== next.onClearHistory) return false;
  if (prev.onEdit !== next.onEdit) return false;
  if (prev.turns.length !== next.turns.length) return false;
  const pLast = prev.turns[prev.turns.length - 1];
  const nLast = next.turns[next.turns.length - 1];
  if (!pLast || !nLast) return prev.turns.length === next.turns.length;
  return (
    pLast.text.length === nLast.text.length &&
    pLast.status === nLast.status &&
    pLast.process.length === nLast.process.length &&
    pLast.errorDetail === nLast.errorDetail
  );
});
