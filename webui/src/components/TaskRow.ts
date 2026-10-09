// 整改方案 v2 — 任务行类型（type-only 模块）
// 原 TaskPanel.tsx 已删除（左侧栏被 WorkflowPane 替代）。
// 但 TaskRow / AgentStep / TaskStatus 三个类型被多处引用，保留为 type-only 模块。

export type TaskStatus = "pending" | "running" | "done" | "error";

export interface AgentStep {
  name: string;
  stage: string;
  status: "idle" | "running" | "done" | "error";
  text: string;
  toolCount: number;
  ts: number;
}

export interface TaskRow {
  stage: string;
  label: string;
  mode: "serial" | "parallel";
  agents: string[];
  status: TaskStatus;
  detail?: string;
  startTs?: number;
  finishTs?: number;
  agentSteps: AgentStep[];
}
