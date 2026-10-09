// Status indicator dot.

import type { AgentColor } from "../types";

type Status = "idle" | "running" | "done" | "error" | "active" | "inactive";

interface Props {
  status: Status;
  size?: number;
}

const COLOR_MAP: Record<Status, string> = {
  idle:     "var(--text-faint)",
  running:  "var(--ok)",
  done:     "var(--info)",
  error:    "var(--err)",
  active:   "var(--ok)",
  inactive: "var(--text-faint)",
};

export function StatusDot({ status, size = 8 }: Props) {
  const color = COLOR_MAP[status] || COLOR_MAP.idle;
  return (
    <span
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        background: color,
        boxShadow: status === "running" ? `0 0 6px ${color}` : "none",
        animation: status === "running" ? "pulse 1.5s ease-in-out infinite" : "none",
      }}
    />
  );
}

export function colorToVar(c: AgentColor): string {
  return `var(--c-${c})`;
}
