// Card-style status badge — idle / running / done / error.
//
// Lifted from the old components/ScenarioView.tsx's CardStatusBadge.
// Used by every Panel size (Compact/Medium/Large) and the strip avatars,
// so it lives in its own file in the canvas/ directory.

export type CardStatus = "idle" | "running" | "done" | "error";

const META: Record<CardStatus, { label: string; bg: string; fg: string; pulse?: boolean }> = {
  idle:    { label: "等待",  bg: "var(--bg-elev)",     fg: "var(--text-faint)" },
  running: { label: "运行中", bg: "var(--accent-soft)", fg: "var(--accent-dim)", pulse: true },
  done:    { label: "完成",  bg: "#dcfce7",            fg: "#15803d" },
  error:   { label: "出错",  bg: "#fee2e2",            fg: "#991b1b" },
};

export function CardStatusBadge({ status }: { status: CardStatus }) {
  const m = META[status];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 10,
      background: m.bg, color: m.fg,
      fontSize: 10, fontWeight: 600, flexShrink: 0,
    }}>
      {m.pulse && (
        <span style={{
          width: 5, height: 5, borderRadius: "50%",
          background: m.fg,
          animation: "pulse 0.9s ease-in-out infinite",
        }} />
      )}
      {m.label}
    </span>
  );
}
