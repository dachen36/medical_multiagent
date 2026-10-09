// CoordinatorTrace — small collapsible band shown above BentoGrid when
// the user picked coordinator mode (P10 hierarchical supervisor).
//
// Surfaces the timeline of `coordinator.tool_call` events so users can
// see "why is only 1 specialist active?" without diving into the
// SystemRail event log. The 7 supervisor tools are: dispatch, observe,
// proceed, revise, finish_agent, assert_goal_coverage, publish_final_report.
//
// Default collapsed; the user clicks the summary to expand. Even when
// collapsed, the count badge updates live as new tool calls fire.

import type { ScenarioEvent } from "../../api/client";

interface ToolCall {
  ts: number;
  tool_name: string;
  tool_id: string;
}

interface Props {
  events: ScenarioEvent[];
}

export function CoordinatorTrace({ events }: Props) {
  const calls: ToolCall[] = events
    .filter((e): e is Extract<ScenarioEvent, { type: "coordinator.tool_call" }> =>
      e.type === "coordinator.tool_call"
    )
    .map((e) => ({ ts: e.ts, tool_name: e.tool_name, tool_id: e.tool_id }));

  if (calls.length === 0) return null;

  return (
    <details style={{
      margin: "0 0 8px",
      padding: "6px 12px",
      background: "var(--bg-soft)",
      border: "1px solid var(--border-soft)",
      borderRadius: 8,
      fontSize: 11,
      color: "var(--text-dim)",
    }}>
      <summary style={{
        cursor: "pointer", userSelect: "none",
        display: "inline-flex", alignItems: "center", gap: 6,
        fontWeight: 600,
      }}>
        <span style={{ color: "var(--accent)" }}>⚙</span>
        协调者轨迹 · {calls.length} 个工具调用
      </summary>
      <div style={{
        marginTop: 8,
        display: "flex", flexWrap: "wrap", gap: 6,
        fontFamily: "ui-monospace, monospace",
      }}>
        {calls.map((c, idx) => (
          <span
            key={c.tool_id}
            title={`#${idx + 1} · ${new Date(c.ts * 1000).toLocaleTimeString()}`}
            style={{
              padding: "2px 8px",
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: 4,
              fontSize: 10,
              color: "var(--text-dim)",
            }}
          >
            <span style={{ color: "var(--text-faint)" }}>{idx + 1}.</span>{" "}
            {c.tool_name}
          </span>
        ))}
      </div>
    </details>
  );
}
