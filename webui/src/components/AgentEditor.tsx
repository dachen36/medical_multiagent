// Modal for creating a new agent or editing an existing one.
//
// Triggered by:
//   - AgentList header `+ 新建`   (mode: "create")
//   - DetailPanel header `编辑`   (mode: "edit",  name disabled)
//
// Form mirrors the AgentWrite backend model field-for-field. The `skills`
// field is a checkbox grid over the known skills; P2.4 will refine this
// (search/filter, group by domain). For now it's a flat multi-select.

import { useEffect, useMemo, useState } from "react";
import type { Agent, AgentColor, PermissionMode, Skill } from "../types";
import { ApiError, api, type AgentWritePayload } from "../api/client";

type Mode = "create" | "edit";

interface Props {
  mode: Mode;
  initial: Agent | null;            // null in create mode
  skills: Skill[];
  onClose: () => void;
  onSaved: (agent: Agent) => void;
}

const COLORS: AgentColor[] = [
  "red", "green", "blue", "yellow", "purple",
  "orange", "cyan", "magenta", "white", "gray",
];

const PERMISSIONS: PermissionMode[] = [
  "default", "acceptEdits", "bypassPermissions", "plan", "dontAsk",
];

// P7.B — default text for the "WebUI Q&A mode" prompt that gets appended
// to the system prompt at LLM call time. Lives only on the frontend;
// the backend never holds a copy of this default. If the user clears
// the field (via the checkbox), the backend just won't append anything.
const DEFAULT_WEBUI_QA_PROMPT = `## WebUI Q&A mode

When invoked from the WebUI (direct user question, no mailbox):
- The user is asking YOU directly, not coordinating with teammates.
- Do NOT try to read mailboxes or write back to coordinators in this mode.
- For each request:
  1. Check if one of your skills is directly relevant to the question.
  2. If yes → invoke it via the \`skill\` tool and follow its instructions.
  3. If no → answer directly from your general knowledge, briefly noting
     that the question is outside your primary scope.
- You DO see the prior conversation history (server keeps it across turns).
  Use it to give a context-aware answer if the user is following up.`;

const DEFAULT_PAYLOAD: AgentWritePayload = {
  name: "",
  subagent_type: "",
  display_name: "",
  description: "",
  color: "gray",
  skills: [],
  tools: [],
  model: "inherit",
  max_turns: 30,
  permission_mode: "default",
  background: false,
  memory: "user",
  system_prompt_body: "",
  webui_qa_prompt: DEFAULT_WEBUI_QA_PROMPT,  // P7.B — new agents start with QA mode on
};

function fromAgent(a: Agent): AgentWritePayload {
  return {
    name: a.name,
    subagent_type: a.subagent_type,
    display_name: a.display_name ?? "",
    description: a.description,
    color: a.color,
    skills: [...a.skills],
    tools: [...a.tools],
    model: a.model,
    max_turns: a.max_turns,
    permission_mode: a.permission_mode,
    background: a.background,
    memory: a.memory,
    system_prompt_body: a.system_prompt_body,
    webui_qa_prompt: a.webui_qa_prompt ?? "",  // P7.B
  };
}

const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

export function AgentEditor({ mode, initial, skills, onClose, onSaved }: Props) {
  const [form, setForm] = useState<AgentWritePayload>(
    initial ? fromAgent(initial) : { ...DEFAULT_PAYLOAD },
  );
  const [toolsText, setToolsText] = useState(
    initial ? initial.tools.join(", ") : "",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Lock body scroll while modal is open + close on Escape
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !saving) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [saving, onClose]);

  const nameValid = useMemo(
    () => NAME_PATTERN.test(form.name),
    [form.name],
  );

  const formValid =
    nameValid &&
    form.max_turns >= 1 && form.max_turns <= 1000 &&
    form.description.length <= 500 &&
    form.system_prompt_body.length <= 20000 &&
    form.webui_qa_prompt.length <= 8000;  // P7.B

  function set<K extends keyof AgentWritePayload>(k: K, v: AgentWritePayload[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function toggleSkill(name: string) {
    setForm((f) => ({
      ...f,
      skills: f.skills.includes(name)
        ? f.skills.filter((s) => s !== name)
        : [...f.skills, name],
    }));
  }

  async function save() {
    if (!formValid || saving) return;
    setSaving(true);
    setError(null);
    const payload: AgentWritePayload = {
      ...form,
      subagent_type: form.subagent_type.trim() || form.name,
      tools: toolsText
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    };
    try {
      const saved = mode === "create"
        ? await api.createAgent(payload)
        : await api.updateAgent(form.name, payload);
      onSaved(saved);
    } catch (e) {
      if (e instanceof ApiError) {
        // Try to extract FastAPI's `detail` (string or array of validation issues)
        try {
          const j = JSON.parse(e.detail);
          if (typeof j === "string") setError(j);
          else if (Array.isArray(j)) setError(j.map((x: any) => `${x.loc?.join(".") ?? "?"}: ${x.msg}`).join("; "));
          else if (j?.detail) setError(String(j.detail));
          else setError(e.message);
        } catch {
          setError(e.detail);
        }
      } else {
        setError(String(e));
      }
    } finally {
      setSaving(false);
    }
  }

  const title = mode === "create" ? "新建智能体" : `编辑智能体 · ${initial?.name}`;
  const submitLabel = mode === "create" ? "创建" : "保存";

  return (
    <div
      onClick={() => !saving && onClose()}
      style={{
        position: "fixed", inset: 0,
        background: "rgba(15, 23, 42, 0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000,
        animation: "slideUp 0.12s ease-out",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 720,
          maxWidth: "94vw",
          maxHeight: "90vh",
          background: "var(--bg)",
          borderRadius: 10,
          boxShadow: "0 12px 40px rgba(15, 23, 42, 0.25)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "14px 20px",
          borderBottom: "1px solid var(--border)",
          display: "flex", justifyContent: "space-between", alignItems: "center",
          background: "var(--bg-soft)",
          flexShrink: 0,
        }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text)" }}>
            {title}
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            style={{ padding: "2px 10px", fontSize: 13 }}
          >
            ✕
          </button>
        </div>

        {/* Body (scrollable) */}
        <div style={{
          flex: 1, overflow: "auto", padding: "18px 20px",
          display: "flex", flexDirection: "column", gap: 16,
        }}>
          {error && (
            <div style={{
              padding: "8px 12px",
              background: "#fee2e2", color: "#991b1b",
              border: "1px solid #fecaca", borderRadius: 6,
              fontSize: 12, lineHeight: 1.5,
            }}>
              ⚠ {error}
            </div>
          )}

          <FieldRow>
            <Field label="名称" hint="kebab-case, 1-64 字符">
              <input
                value={form.name}
                disabled={mode === "edit"}
                onChange={(e) => set("name", e.target.value)}
                placeholder="my-new-agent"
                style={{ width: "100%", fontFamily: "ui-monospace, monospace" }}
              />
              {form.name && !nameValid && (
                <div style={{ fontSize: 10, color: "var(--err)", marginTop: 4 }}>
                  必须以小写字母或数字开头, 后续只能是小写字母/数字/短横线
                </div>
              )}
            </Field>
            <Field label="子代理类型" hint="留空则与名称相同">
              <input
                value={form.subagent_type}
                onChange={(e) => set("subagent_type", e.target.value)}
                placeholder={form.name || "subagent_type"}
                style={{ width: "100%", fontFamily: "ui-monospace, monospace" }}
              />
            </Field>
            <Field label="中文显示名" hint="留空回退到 kebab-case 名称">
              <input
                value={form.display_name}
                onChange={(e) => set("display_name", e.target.value)}
                placeholder="如: 协调者 / IOT智能体"
                style={{ width: "100%" }}
              />
            </Field>
          </FieldRow>

          <Field label="描述" hint={`${form.description.length} / 500`}>
            <textarea
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
              placeholder="一句话说清楚这个 agent 负责什么..."
              rows={2}
              style={{ width: "100%", resize: "vertical", minHeight: 50 }}
            />
          </Field>

          <FieldRow>
            <Field label="颜色">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => set("color", c)}
                    title={c}
                    style={{
                      width: 26, height: 26, borderRadius: 6,
                      background: `var(--c-${c})`,
                      border: form.color === c
                        ? "2px solid var(--accent-dim)"
                        : "2px solid var(--border)",
                      cursor: "pointer",
                      padding: 0,
                      boxShadow: form.color === c
                        ? "0 0 0 2px var(--accent-soft)"
                        : "none",
                    }}
                  />
                ))}
              </div>
            </Field>

            <Field label="模型" hint='默认 "inherit"'>
              <input
                value={form.model}
                onChange={(e) => set("model", e.target.value)}
                style={{ width: "100%", fontFamily: "ui-monospace, monospace" }}
              />
            </Field>
          </FieldRow>

          <FieldRow>
            <Field label="最大轮次" hint="1 - 1000">
              <input
                type="number"
                min={1}
                max={1000}
                value={form.max_turns}
                onChange={(e) => set("max_turns", Number(e.target.value) || 0)}
                style={{ width: "100%" }}
              />
            </Field>
            <Field label="权限模式">
              <select
                value={form.permission_mode}
                onChange={(e) => set("permission_mode", e.target.value as PermissionMode)}
                style={{ width: "100%" }}
              >
                {PERMISSIONS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </Field>
          </FieldRow>

          <FieldRow>
            <Field label="记忆作用域">
              <input
                value={form.memory}
                onChange={(e) => set("memory", e.target.value)}
                style={{ width: "100%" }}
              />
            </Field>
            <Field label="后台运行">
              <label style={{
                display: "flex", alignItems: "center", gap: 6,
                fontSize: 12, color: "var(--text-dim)",
                padding: "7px 0",
              }}>
                <input
                  type="checkbox"
                  checked={form.background}
                  onChange={(e) => set("background", e.target.checked)}
                />
                允许在后台进程中执行
              </label>
            </Field>
          </FieldRow>

          <Field label="工具" hint="逗号分隔, 例如: Bash, Read, Glob, Grep, Skill, Agent">
            <input
              value={toolsText}
              onChange={(e) => setToolsText(e.target.value)}
              placeholder="Bash, Read, Glob"
              style={{ width: "100%", fontFamily: "ui-monospace, monospace" }}
            />
          </Field>

          <Field label={`技能 (${form.skills.length})`} hint="点击切换, 未知技能保存时会被拒绝">
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: 6,
              maxHeight: 180, overflow: "auto",
              padding: 6,
              border: "1px solid var(--border-soft)",
              borderRadius: 6,
              background: "var(--bg-soft)",
            }}>
              {skills.map((s) => {
                const on = form.skills.includes(s.name);
                return (
                  <label
                    key={s.name}
                    style={{
                      display: "flex", alignItems: "center", gap: 6,
                      padding: "5px 8px",
                      borderRadius: 4,
                      background: on ? "var(--accent-soft)" : "var(--bg)",
                      border: `1px solid ${on ? "var(--accent)" : "var(--border-soft)"}`,
                      cursor: "pointer",
                      fontSize: 11,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => toggleSkill(s.name)}
                    />
                    <span style={{
                      fontFamily: "ui-monospace, monospace",
                      color: on ? "var(--accent-dim)" : "var(--text)",
                      fontWeight: 600,
                    }}>
                      {s.name}
                    </span>
                    <span style={{
                      marginLeft: "auto",
                      fontSize: 9, color: "var(--text-faint)",
                    }}>
                      {s.domain}
                    </span>
                  </label>
                );
              })}
              {skills.length === 0 && (
                <div style={{ fontSize: 11, color: "var(--text-faint)" }}>
                  (暂无可用技能)
                </div>
              )}
            </div>
          </Field>

          <Field label="WebUI Q&A 模式提示词" hint="附加在系统提示词末尾">
            {/* P7.B explainer — why this region exists */}
            <div style={{
              padding: "8px 10px", marginBottom: 8,
              background: "var(--bg-soft)",
              border: "1px solid var(--border-soft)",
              borderRadius: 6,
              fontSize: 11, lineHeight: 1.55,
              color: "var(--text-dim)",
            }}>
              <div style={{fontWeight: 600, marginBottom: 4, color: "var(--text)"}}>
                ℹ️ 什么是 WebUI Q&A 模式？
              </div>
              <div>
                WebUI 是面向用户的<strong>直接问答</strong>模式,不是 CLI 团队的
                mailbox 模式。勾选后,LLM 会收到一段提示,知道:
              </div>
              <ul style={{margin: "4px 0 4px 18px", padding: 0}}>
                <li>不要去读 mailbox / 写 coordinator inbox</li>
                <li>优先调用相关 skill(若有)</li>
                <li>若 skill 不相关,直接用通用知识回答</li>
                <li>可看到多轮历史,支持上下文续接</li>
              </ul>
              <div>
                <strong>取消勾选 = 不附加任何提示词</strong>
                (LLM 只看 body,可能走错模式 → 读 mailbox)。
              </div>
            </div>

            <label style={{
              display: "flex", alignItems: "center", gap: 6,
              fontSize: 12, color: "var(--text-dim)",
              padding: "6px 0", cursor: "pointer",
            }}>
              <input
                type="checkbox"
                checked={form.webui_qa_prompt.length > 0}
                onChange={(e) => {
                  if (e.target.checked) {
                    // Enable: if empty, fill with default
                    set("webui_qa_prompt",
                        form.webui_qa_prompt || DEFAULT_WEBUI_QA_PROMPT);
                  } else {
                    // Disable: clear
                    set("webui_qa_prompt", "");
                  }
                }}
              />
              添加 WebUI Q&A 模式提示词(推荐)
            </label>

            {form.webui_qa_prompt.length > 0 && (
              <>
                <textarea
                  value={form.webui_qa_prompt}
                  onChange={(e) => set("webui_qa_prompt", e.target.value)}
                  placeholder={DEFAULT_WEBUI_QA_PROMPT}
                  rows={6}
                  style={{
                    width: "100%", resize: "vertical", minHeight: 110,
                    fontFamily: "ui-monospace, monospace", fontSize: 12,
                    marginTop: 6,
                  }}
                />
                <div style={{
                  display: "flex", justifyContent: "space-between",
                  fontSize: 10, color: "var(--text-faint)", marginTop: 4,
                }}>
                  <span>{form.webui_qa_prompt.length} / 8000</span>
                  <button
                    type="button"
                    onClick={() => set("webui_qa_prompt", DEFAULT_WEBUI_QA_PROMPT)}
                    style={{ padding: "0 8px", fontSize: 10, color: "var(--accent)" }}
                  >
                    重置为默认
                  </button>
                </div>
              </>
            )}
          </Field>

          <Field label="系统提示词" hint={`${form.system_prompt_body.length} / 20000`}>
            <textarea
              value={form.system_prompt_body}
              onChange={(e) => set("system_prompt_body", e.target.value)}
              placeholder="# Agent\n\nYou are the ...\n\n## How to work\n1. ...\n"
              rows={8}
              style={{
                width: "100%",
                resize: "vertical",
                minHeight: 120,
                fontFamily: "ui-monospace, monospace",
                fontSize: 12,
              }}
            />
          </Field>
        </div>

        {/* Footer */}
        <div style={{
          padding: "12px 20px",
          borderTop: "1px solid var(--border)",
          background: "var(--bg-soft)",
          display: "flex", justifyContent: "flex-end", gap: 8,
          flexShrink: 0,
        }}>
          <button onClick={onClose} disabled={saving}>取消</button>
          <button
            className="primary"
            onClick={save}
            disabled={!formValid || saving}
          >
            {saving ? "保存中…" : submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function FieldRow({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
      {children}
    </div>
  );
}

function Field({
  label, hint, children,
}: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "baseline",
        marginBottom: 4,
      }}>
        <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-dim)" }}>
          {label}
        </label>
        {hint && (
          <span style={{ fontSize: 10, color: "var(--text-faint)" }}>
            {hint}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}
