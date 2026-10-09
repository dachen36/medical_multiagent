// Shared role-shape human-figure icons for the agent list rows and the
// scenario Overview cards. Dispatch is by name prefix; unknown agents
// fall back to a plain person silhouette.
//
// `currentColor` is set by the parent's `color` (the agent's color token).
// `var(--bg)` (#ffffff) is used to "punch through" accessories (cross,
// book, crate lid) — a small white shape reads as visual contrast.

export function AgentIcon({ name, size = 18 }: { name: string; size?: number }) {
  const inner = (() => {
    // 整改方案 S5-H — 4 个 specialist + 协调者各加专属图标
    // 优先级：更具体的前缀先匹配
    if (name.includes("coordinator") || name.startsWith("team-")) return <CoordinatorPath />;
    if (name.startsWith("intake-"))     return <IntakePath />;
    if (name.startsWith("knowledge-"))  return <KnowledgePath />;
    if (name.startsWith("analysis-"))   return <AnalysisPath />;
    if (name.startsWith("evolution-"))  return <EvolutionPath />;
    // 兼容旧版前缀
    if (name.startsWith("nas-"))      return <NasPath />;
    if (name.startsWith("iot-"))      return <IotPath />;
    if (name.startsWith("medical-"))  return <MedicalPath />;
    if (name.startsWith("education-") || name.startsWith("edu-")) return <EducationPath />;
    return <DefaultPath />;
  })();
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" fill="currentColor" aria-hidden>
      {inner}
    </svg>
  );
}

// Each path is the inner content of the 18×18 viewBox. Putting them as
// separate functions makes the markup easy to read inline.

function CoordinatorPath() {
  // person with both arms spread wide (orchestrator pose)
  return (
    <>
      <circle cx="9" cy="3.6" r="1.9"/>
      <rect x="0.8" y="7.6" width="16.4" height="1.4" rx="0.7"/>
      <path d="M6.2 8.7 L11.8 8.7 L12.4 16 L5.6 16 Z"/>
      <rect x="8.6" y="14" width="0.8" height="2" fill="var(--bg)"/>
    </>
  );
}

function NasPath() {
  // person carrying/holding a storage crate
  return (
    <>
      <circle cx="9" cy="3.2" r="1.7"/>
      <path d="M3.0 7.5 L7 7.5 L7 8.6 L3 8.6 Z M11 7.5 L15 7.5 L15 8.6 L11 8.6 Z"/>
      <path d="M6.2 7.0 L11.8 7.0 L11.6 8.4 L6.4 8.4 Z"/>
      <rect x="2.6" y="8.4" width="12.8" height="4.2" rx="0.4"
            fill="var(--bg)" stroke="currentColor" strokeWidth="1"/>
      <line x1="9" y1="8.4" x2="9" y2="12.6" stroke="currentColor" strokeWidth="0.8"/>
      <rect x="6.4" y="12.6" width="1.6" height="2.6"/>
      <rect x="10.0" y="12.6" width="1.6" height="2.6"/>
    </>
  );
}

function IotPath() {
  // person with antenna + signal arcs above head
  return (
    <>
      <g fill="none" stroke="currentColor" strokeWidth="0.9" strokeLinecap="round">
        <path d="M5.4 2.0 Q9 -0.4 12.6 2.0" opacity="0.5"/>
        <path d="M6.5 3.0 Q9 1.4 11.5 3.0"/>
        <line x1="9" y1="3.2" x2="9" y2="4.6" strokeWidth="1"/>
      </g>
      <circle cx="9" cy="5.6" r="1.7"/>
      <path d="M3.8 16 Q3.8 8.4 9 7.5 Q14.2 8.4 14.2 16 Z"/>
      <rect x="8.6" y="13.5" width="0.8" height="2.5" fill="var(--bg)"/>
    </>
  );
}

function MedicalPath() {
  // person with a large medical cross on the chest
  return (
    <>
      <circle cx="9" cy="3.6" r="1.9"/>
      <path d="M3.8 16 Q3.8 8.4 9 7.5 Q14.2 8.4 14.2 16 Z"/>
      <rect x="6.6" y="10.4" width="4.8" height="1.8" fill="var(--bg)"/>
      <rect x="8.1" y="8.9" width="1.8" height="4.8" fill="var(--bg)"/>
    </>
  );
}

function EducationPath() {
  // person with a graduation cap (mortarboard) — instantly readable as "teacher"
  return (
    <>
      <path d="M1.6 6.0 L9 3.0 L16.4 6.0 L9 9.0 Z"/>
      <path d="M3.6 6.7 L3.6 9.6 Q9 12.2 14.4 9.6 L14.4 6.7 L9 9.0 Z" fillOpacity="0.75"/>
      <line x1="15.4" y1="6.0" x2="15.4" y2="9.4" stroke="currentColor" strokeWidth="0.7"/>
      <circle cx="15.4" cy="9.6" r="0.7"/>
      <circle cx="9" cy="9.6" r="1.4"/>
      <path d="M5.5 16 Q5.5 12 9 11.4 Q12.5 12 12.5 16 Z"/>
    </>
  );
}

function DefaultPath() {
  // plain person silhouette
  return (
    <>
      <circle cx="9" cy="3.6" r="1.9"/>
      <path d="M3.8 16 Q3.8 8.4 9 7.5 Q14.2 8.4 14.2 16 Z"/>
    </>
  );
}

// S5-H: 问诊采集（intake-specialist）— person + 问号徽章
function IntakePath() {
  return (
    <>
      <circle cx="9" cy="3.6" r="1.9"/>
      <path d="M3.8 16 Q3.8 8.4 9 7.5 Q14.2 8.4 14.2 16 Z"/>
      <circle cx="9" cy="11.6" r="1.6" fill="var(--bg)"/>
      <path d="M8.3 11.0 Q8.3 10.3 9 10.3 Q9.7 10.3 9.7 10.8 Q9.7 11.1 9.4 11.3 L9 11.7 L9 12.1"
            stroke="currentColor" strokeWidth="0.7" fill="none" strokeLinecap="round"/>
      <circle cx="9" cy="12.7" r="0.3" fill="currentColor"/>
    </>
  );
}

// S5-H: 知识检索（knowledge-specialist）— person + 打开的书
function KnowledgePath() {
  return (
    <>
      <circle cx="9" cy="3.6" r="1.9"/>
      <path d="M3.8 16 Q3.8 8.4 9 7.5 Q14.2 8.4 14.2 16 Z"/>
      <path d="M5.5 10.6 L9 11.4 L12.5 10.6 L12.5 13.6 L9 14.4 L5.5 13.6 Z"
            fill="var(--bg)" stroke="currentColor" strokeWidth="0.5"/>
      <line x1="9" y1="11.4" x2="9" y2="14.4" stroke="currentColor" strokeWidth="0.4"/>
    </>
  );
}

// S5-H: 智能分析（analysis-specialist）— person + 药丸
function AnalysisPath() {
  return (
    <>
      <circle cx="9" cy="3.6" r="1.9"/>
      <path d="M3.8 16 Q3.8 8.4 9 7.5 Q14.2 8.4 14.2 16 Z"/>
      <g transform="rotate(-25 9 12.2)">
        <rect x="6" y="11.0" width="6" height="2.4" rx="1.2"
              fill="var(--bg)" stroke="currentColor" strokeWidth="0.5"/>
        <line x1="9" y1="11.0" x2="9" y2="13.4" stroke="currentColor" strokeWidth="0.4"/>
      </g>
    </>
  );
}

// S5-H: 自我进化（evolution-specialist）— person + DNA 双螺旋
function EvolutionPath() {
  return (
    <>
      <circle cx="9" cy="3.6" r="1.9"/>
      <path d="M3.8 16 Q3.8 8.4 9 7.5 Q14.2 8.4 14.2 16 Z"/>
      <path d="M6.4 10.4 Q9 11.4 11.6 10.4 Q9 12.0 6.4 13.2 Q9 13.8 11.6 14.4"
            stroke="currentColor" strokeWidth="0.5" fill="none"/>
      <path d="M11.6 10.4 Q9 11.4 6.4 10.4 Q9 12.0 11.6 13.2 Q9 13.8 6.4 14.4"
            stroke="currentColor" strokeWidth="0.5" fill="none"/>
      <line x1="6.6" y1="10.6" x2="11.4" y2="10.6" stroke="currentColor" strokeWidth="0.3"/>
      <line x1="7.0" y1="11.6" x2="11.0" y2="11.6" stroke="currentColor" strokeWidth="0.3"/>
      <line x1="6.6" y1="12.6" x2="11.4" y2="12.6" stroke="currentColor" strokeWidth="0.3"/>
      <line x1="7.0" y1="13.6" x2="11.0" y2="13.6" stroke="currentColor" strokeWidth="0.3"/>
    </>
  );
}
