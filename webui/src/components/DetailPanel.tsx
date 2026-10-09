// Right column: detail of the selected agent.
//
// P4 — collapsed / expanded two-state design.
//   - collapsed: 48px wide strip with agent color stripe + icon + ✎ button.
//     Click the strip to expand; ✎ to jump straight to the editor modal.
//   - expanded: 320px full panel (the original P3 design).
// Outside-click collapse is the App's responsibility (via useOutsideClick
// hook on this component's root ref), so the panel can stay dumb.
//
// We also accept a `ref` via the standard forwardRef pattern so the parent
// can attach the outside-click listener to the actual DOM node, including
// the collapsed strip variant (which is 48px wide, still inside the ref).

import { forwardRef } from "react";
import type { Agent, Skill } from "../types";
import { displayName } from "../types";
import { colorToVar } from "./AgentCard";
import { AgentIcon } from "./AgentIcon";
import { SkillSelector } from "./SkillSelector";

interface Props {
  agent: Agent | null;
  skills: Skill[];
  onClose?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onSkillsChange?: (newSkills: string[]) => Promise<void> | void;
  savingSkills?: boolean;
  /** When true, render the 48px collapsed strip instead of the full panel. */
  collapsed?: boolean;
  /** Required when collapsed + agent present. Expands the panel. */
  onExpand?: () => void;
}

export const DetailPanel = forwardRef<HTMLElement, Props>(function DetailPanel({
  agent, skills, onClose, onEdit, onDelete,
  onSkillsChange, savingSkills = false,
  collapsed = false, onExpand,
}, ref) {
  if (!agent) {
    // No selection. Render a placeholder strip in collapsed mode, the
    // original centered message in expanded mode.
    if (collapsed) {
      return (
        <aside
          ref={ref as React.Ref<HTMLElement>}
          style={{
            width: 48, flexShrink: 0,
            borderLeft: "1px solid var(--border)",
            background: "var(--bg-soft)",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "var(--text-faint)", fontSize: 10,
            cursor: onExpand ? "pointer" : "default",
          }}
          onClick={onExpand}
          title="未选择智能体"
        >
          —
        </aside>
      );
    }
    return (
      <aside
        ref={ref as React.Ref<HTMLElement>}
        style={{
          width: 320,
          flexShrink: 0,
          borderLeft: "1px solid var(--border)",
          background: "var(--bg-soft)",
          padding: 32,
          color: "var(--text-faint)",
          fontSize: 12,
          textAlign: "center",
        }}
      >
        ← 请选择智能体
      </aside>
    );
  }

  // Agent present + collapsed → render the 48px strip
  if (collapsed) {
    const color = colorToVar(agent.color);
    return (
      <aside
        ref={ref as React.Ref<HTMLElement>}
        onClick={onExpand}
        style={{
          width: 48, flexShrink: 0,
          borderLeft: "1px solid var(--border)",
          background: "var(--bg-soft)",
          display: "flex", flexDirection: "column",
          alignItems: "center", padding: "10px 0",
          cursor: onExpand ? "pointer" : "default",
          position: "relative",
          transition: "background 0.12s",
        }}
        title={`${displayName(agent)} · 点击展开`}
      >
        {/* 3px color stripe at the top */}
        <span style={{
          position: "absolute", top: 0, left: 0, right: 0, height: 3,
          background: color,
        }} />

        {/* Edit button (stops propagation so it doesn't trigger onExpand) */}
        {onEdit && (
          <button
            onClick={(e) => { e.stopPropagation(); onEdit(); }}
            title="编辑"
            style={{
              padding: "2px 7px", fontSize: 11,
              marginBottom: 10,
              background: "var(--bg)",
            }}
          >
            ✎
          </button>
        )}

        {/* Agent icon centered */}
        <span style={{ color, display: "flex" }}>
          <AgentIcon name={agent.name} size={28} />
        </span>

        {/* Chevron at the bottom — visual cue that strip is clickable */}
        <span style={{
          marginTop: "auto",
          color: "var(--text-faint)", fontSize: 14,
          transform: "rotate(90deg)",
        }}>
          ‹
        </span>
      </aside>
    );
  }

  // Expanded mode — original P3 layout, ref attached for outside-click.
  const color = colorToVar(agent.color);

  return (
    <aside
      ref={ref as React.Ref<HTMLElement>}
      style={{
        width: 320,
        flexShrink: 0,
        borderLeft: "1px solid var(--border)",
        background: "var(--bg-soft)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div style={{
        padding: "14px 16px",
        borderBottom: "1px solid var(--border-soft)",
        background: "var(--bg)",
      }}>
        {/* Row 1: action buttons (right-aligned, on their own line) */}
        <div style={{
          display: "flex", justifyContent: "flex-end", gap: 6,
          marginBottom: 10,
        }}>
          {onEdit && (
            <button
              onClick={onEdit}
              title="编辑"
              style={{ padding: "3px 10px", fontSize: 11 }}
            >
              ✎ 编辑
            </button>
          )}
          {onDelete && (
            <button
              onClick={onDelete}
              title="删除"
              style={{
                padding: "3px 10px", fontSize: 11,
                color: "var(--err)",
              }}
            >
              ✕ 删除
            </button>
          )}
          {onClose && (
            <button
              onClick={onClose}
              title="关闭"
              style={{ padding: "3px 8px", fontSize: 11 }}
            >
              ✕
            </button>
          )}
        </div>

        {/* Row 2: 3px color stripe + title + ID meta */}
        <div style={{ borderTop: `3px solid ${color}`, paddingTop: 10 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color }} title={agent.name}>
            {displayName(agent)}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 4 }}>
            子代理类型: <code style={{ color: "var(--text-dim)" }}>{agent.subagent_type}</code>
            {agent.display_name && (
              <span style={{ marginLeft: 8 }}>
                · ID: <code style={{ color: "var(--text-dim)" }}>{agent.name}</code>
              </span>
            )}
          </div>
        </div>

        {agent.description && (
          <p style={{
            fontSize: 12,
            color: "var(--text-dim)",
            marginTop: 10,
            marginBottom: 0,
            lineHeight: 1.5,
          }}>
            {agent.description}
          </p>
        )}
        <div style={{ display: "flex", gap: 14, marginTop: 12, fontSize: 11 }}>
          <span><span style={{ color: "var(--text-faint)" }}>模型: </span><span style={{ color: "var(--text)" }}>{agent.model}</span></span>
          <span><span style={{ color: "var(--text-faint)" }}>轮次: </span><span style={{ color: "var(--text)" }}>≤{agent.max_turns}</span></span>
          <span><span style={{ color: "var(--text-faint)" }}>权限: </span><span style={{ color: "var(--text)" }}>{agent.permission_mode}</span></span>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflow: "auto", padding: "14px 16px" }}>
        {onSkillsChange ? (
          <SkillSelector
            attached={agent.skills}
            available={skills}
            saving={savingSkills}
            onChange={onSkillsChange}
          />
        ) : (() => {
          // Read-only fallback (no onSkillsChange handler)
          const skillDetails = agent.skills
            .map((name: string) => skills.find((s) => s.name === name))
            .filter((s: Skill | undefined): s is Skill => Boolean(s));
          return (
          <section>
            <h3 style={{
              fontSize: 11, fontWeight: 700, letterSpacing: 1.2,
              color: "var(--accent)", margin: "0 0 10px 0",
              textTransform: "uppercase",
            }}>
              技能 ({skillDetails.length})
            </h3>
            {skillDetails.length === 0 ? (
              <div style={{ fontSize: 11, color: "var(--text-faint)" }}>无</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {skillDetails.map((s) => (
                  <div
                    key={s.name}
                    style={{
                      background: "var(--bg)",
                      border: "1px solid var(--border-soft)",
                      borderRadius: 6,
                      padding: "8px 10px",
                      fontSize: 12,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontWeight: 600, color: "var(--text)" }}>{s.name}</span>
                      <span style={{
                        fontSize: 10, color: "var(--accent)",
                        padding: "1px 7px", borderRadius: 3,
                        background: "var(--accent-soft)",
                        fontWeight: 600,
                      }}>
                        {s.domain}
                      </span>
                    </div>
                    {s.description && (
                      <div style={{
                        fontSize: 11, color: "var(--text-dim)",
                        marginTop: 4, lineHeight: 1.4,
                      }}>
                        {s.description.length > 120
                          ? s.description.slice(0, 120) + "…"
                          : s.description}
                      </div>
                    )}
                    {s.has_scripts && (
                      <div style={{ fontSize: 10, color: "var(--accent)", marginTop: 4, fontWeight: 600 }}>
                        ▸ 含脚本
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
          );
        })()}

        <section style={{ marginTop: 20 }}>
          <h3 style={{
            fontSize: 11, fontWeight: 700, letterSpacing: 1.2,
            color: "var(--accent)", margin: "0 0 10px 0",
            textTransform: "uppercase",
          }}>
            工具 ({agent.tools.length})
          </h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {agent.tools.map((t) => (
              <span
                key={t}
                style={{
                  fontSize: 11,
                  padding: "3px 9px",
                  borderRadius: 4,
                  background: "var(--accent-soft)",
                  color: "var(--accent-dim)",
                  fontFamily: "ui-monospace, monospace",
                  fontWeight: 600,
                }}
              >
                {t}
              </span>
            ))}
          </div>
        </section>

        {agent.system_prompt_body && (
          <section style={{ marginTop: 20 }}>
            <h3 style={{
              fontSize: 11, fontWeight: 700, letterSpacing: 1.2,
              color: "var(--accent)", margin: "0 0 10px 0",
              textTransform: "uppercase",
            }}>
              系统提示词
            </h3>
            <pre style={{
              fontSize: 11,
              color: "var(--text-dim)",
              background: "var(--bg)",
              border: "1px solid var(--border-soft)",
              padding: 10,
              borderRadius: 6,
              maxHeight: 200,
              overflow: "auto",
              margin: 0,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontFamily: "ui-monospace, monospace",
            }}>
              {agent.system_prompt_body.slice(0, 600)}
              {agent.system_prompt_body.length > 600 ? "\n…" : ""}
            </pre>
          </section>
        )}
      </div>
    </aside>
  );
});
