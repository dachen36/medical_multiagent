// Shared TypeScript types (mirrors webui/server/models.py)

export type AgentColor =
  | "red" | "green" | "blue" | "yellow" | "purple"
  | "orange" | "cyan" | "magenta" | "white" | "gray";

export type PermissionMode =
  | "default" | "acceptEdits" | "bypassPermissions" | "plan" | "dontAsk";

export interface Skill {
  name: string;
  domain: string;
  path: string;
  description: string;
  has_scripts: boolean;
  source: string;
}

export interface Agent {
  name: string;
  subagent_type: string;
  display_name?: string;
  description: string;
  color: AgentColor;
  skills: string[];
  tools: string[];
  model: string;
  max_turns: number;
  permission_mode: PermissionMode;
  background: boolean;
  memory: string;
  system_prompt_body: string;
  /** P7.B — optional WebUI Q&A mode prompt. When non-empty, the server
   *  appends it to the system prompt so the LLM knows it's in direct
   *  Q&A mode (not CLI team mailbox mode). User-controlled via the
   *  AgentEditor checkbox + textarea. */
  webui_qa_prompt: string;
  role: "coordinator" | "specialist";
}

/** UI-facing label: Chinese display_name if set, else the canonical name. */
export function displayName(a: { name: string; display_name?: string }): string {
  return a.display_name?.trim() || a.name;
}

export type ViewState = "landing" | "bento" | "spotlight" | "synthesis";

export interface Health {
  status: string;
  agents_dir: string;
  skills_dir: string;
}
