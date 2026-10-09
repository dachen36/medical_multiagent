//UI 首页 == landing hero
//标题栏 说明栏 输入框

import type { Agent } from "../../types";
import { InputBar } from "../InputBar";
import { AgentStrip } from "./AgentStrip";


interface Props {
  specialists: Agent[];
  historyTurnCounts: Record<string, number>;
  scenarioMode: "classic" | "coordinator";
  onScenarioModeChange: (m: "classic" | "coordinator") => void;
  onSend: (q: string) => void;
  disabled?: boolean;
}

export function LandingHero({
  specialists, historyTurnCounts,
  scenarioMode, onScenarioModeChange,
  onSend, disabled,
}: Props) {
  return (
    <div
      className="view-mount"
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "20px 24px",
        gap: 40,
        overflow: "auto",
      }}
    >
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center",
        gap: 8,
      }}>
        <div style={{
          fontSize: 22, fontWeight: 600, letterSpacing: 1,
          color: "var(--text)",
        }}>
          医疗智能体
        </div>
        <div style={{
          fontSize: 12, color: "var(--text-faint)",
        }}>
          输入问题吧
        </div>
      </div>

      <div style={{
        width: "100%",
        maxWidth: 720,
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}>
        <InputBar
          variant="hero"
          mode={"scenario"} //指定mode初始值
          onSend={onSend}
          disabled={disabled}
          scenarioMode={scenarioMode}
          onScenarioModeChange={onScenarioModeChange}
        />
        <AgentStrip
          specialists={specialists}
          historyTurnCounts={historyTurnCounts}
        />
      </div>
    </div>
  );
}
