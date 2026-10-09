// AgentStrip — bottom hint band on the Landing page.
//
// Displays the 4 specialist avatars + names as a horizontal strip with
// soft connectors between them. NOT clickable — clicking does NOT enter
// a specialist's tab (that was the original UX pitfall). Hover shows a
// tooltip ("点击下方输入框开始 — 或先看 N 轮历史").
//
// When `specialistHistories[name].length > 0` we surface a tiny "· N 轮"
// chip on the avatar so power-users know the history is preserved across
// sessions — but the click target is still the input box, not the chip.

import type { Agent } from "../../types";
import { displayName } from "../../types";
import { AgentIcon } from "../AgentIcon";
import { colorToVar } from "../../lib/agentColor";

interface Props {
  specialists: Agent[];
  historyTurnCounts: Record<string, number>;
}

export function AgentStrip({ specialists, historyTurnCounts }: Props) {
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 14,
      padding: "8px 18px",
      color: "var(--text-faint)",
      fontSize: 12,
      flexWrap: "wrap",
    }}>
      <span style={{ color: "var(--text-dim)", letterSpacing: 0.5 }}>
        将由
      </span>
      {specialists.map((a, i) => {
        const color = colorToVar(a.color);
        const turns = historyTurnCounts[a.name] ?? 0;
        return (
          <span key={a.name} style={{ display: "inline-flex", alignItems: "center", gap: 14 }}>
            <span
              title={turns > 0
                ? `${displayName(a)} · 历史 ${turns} 轮 — 在输入框提问可继续场景`
                : `${displayName(a)} — 在输入框提问开始`}
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "4px 10px", borderRadius: 999,
                background: "var(--bg-elev)",
                border: `1px solid ${color}`,
                cursor: "default",
              }}
            >
              <span style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 18, height: 18, borderRadius: "50%",
                background: color, color: "#ffffff",
                fontSize: 10, fontWeight: 700,
              }}>
                {i + 1}
              </span>
              <span style={{ color, display: "inline-flex" }}>
                <AgentIcon name={a.name} size={18} />
              </span>
              <span style={{ color: "var(--text)", fontWeight: 500 }}>
                {displayName(a)}
              </span>
              {turns > 0 && (
                <span style={{
                  fontSize: 10, color: "var(--text-faint)",
                  fontFamily: "ui-monospace, monospace",
                  marginLeft: 2,
                }}>
                  · {turns} 轮
                </span>
              )}
            </span>
            {i < specialists.length - 1 && (
              <span style={{ color: "var(--text-faint)", fontSize: 10 }}>·</span>
            )}
          </span>
        );
      })}
      <span style={{ color: "var(--text-dim)", letterSpacing: 0.5 }}>协作完成</span>
    </div>
  );
}
