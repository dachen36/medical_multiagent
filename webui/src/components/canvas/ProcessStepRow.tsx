// One process step (tool call + its result) — one row in the timeline.
//
// Lifted verbatim from the old ScenarioView.tsx's ProcessStepRow.
// Used by MediumPanel (latest 3 steps) and LargePanel (full timeline).

import type { ProcessStep } from "../../api/client";

export function ProcessStepRow({ step, color }: { step: ProcessStep; color: string }) {
  const statusColor = step.is_error
    ? "var(--err)"
    : step.status === "running"
    ? color
    : "var(--ok)";
  
  const bgColor = step.is_error 
    ? "var(--err-soft)" 
    : step.status === "running" 
      ? `${color}10` 
      : "var(--bg)";
  
  const icon = step.status === "running" ? "⚙" : step.is_error ? "✗" : "✓";

  return (
    <div style={{
      fontSize: 11,
      fontFamily: "ui-monospace, monospace",
      border: `1px solid ${statusColor}30`,
      borderRadius: "var(--radius-sm)",
      padding: 10,
      background: bgColor,
      opacity: step.status === "running" ? 0.9 : 1,
      transition: "all 0.2s ease",
    }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ 
          color: statusColor, 
          fontWeight: 700, 
          width: 18, 
          height: 18,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: `${statusColor}15`,
          borderRadius: "4px",
          fontSize: 10,
        }}>{icon}</span>
        <span style={{ 
          color: statusColor, 
          fontWeight: 600,
          fontSize: 12,
        }}>{step.tool_name}</span>
        <span style={{ 
          color: "var(--text-faint)",
          fontSize: 10,
        }}>({step.id.slice(0, 8)}…)</span>
        {step.status === "running" && (
          <span style={{ 
            color: color, 
            fontSize: 10, 
            marginLeft: 4,
            fontWeight: 500,
            padding: "1px 6px",
            background: `${color}15`,
            borderRadius: "3px",
          }}>
            <span className="status-dot running" style={{ width: 6, height: 6, marginRight: 3 }} />
            运行中
          </span>
        )}
        {step.status === "done" && !step.is_error && (
          <span style={{ 
            color: "var(--ok)", 
            fontSize: 10, 
            marginLeft: 4,
            fontWeight: 500,
          }}>
            <span className="status-dot done" style={{ width: 6, height: 6, marginRight: 3 }} />
            完成
          </span>
        )}
        {step.is_error && (
          <span style={{ 
            color: "var(--err)", 
            fontSize: 10, 
            marginLeft: 4,
            fontWeight: 500,
          }}>
            <span className="status-dot error" style={{ width: 6, height: 6, marginRight: 3 }} />
            失败
          </span>
        )}
      </div>
      
      {/* input section */}
      <div style={{ 
        marginTop: 8, 
        color: "var(--text-dim)",
        display: "flex",
        flexDirection: "column",
        gap: 2,
      }}>
        <span style={{ 
          color: "var(--text-faint)",
          fontSize: 9,
          fontWeight: 600,
          letterSpacing: 0.5,
        }}>输入</span>
        <code style={{ 
          fontSize: 11, 
          whiteSpace: "pre-wrap", 
          wordBreak: "break-word",
          color: "var(--text-dim)",
        }}>
          {JSON.stringify(step.tool_input, null, 2)}
        </code>
      </div>
      
      {/* output section */}
      {step.output !== undefined && (
        <div style={{ 
          marginTop: 8, 
          color: "var(--text-dim)",
          display: "flex",
          flexDirection: "column",
          gap: 2,
        }}>
          <span style={{ 
            color: step.is_error ? "var(--err)" : "var(--text-faint)",
            fontSize: 9,
            fontWeight: 600,
            letterSpacing: 0.5,
          }}>输出</span>
          <span style={{
            whiteSpace: "pre-wrap", 
            wordBreak: "break-word",
            color: step.is_error ? "var(--err)" : "var(--text-dim)",
            fontSize: 11,
            fontFamily: "ui-monospace, monospace",
          }}>
            {step.output.length > 600
              ? step.output.slice(0, 600) + "…(+" + (step.output.length - 600) + " 字符)"
              : step.output}
          </span>
        </div>
      )}
    </div>
  );
}
