// 整改方案 §S4-C — 诊断工作流 tab 实装
// 替代原 Placeholder，展示本次 workflow 跑的：
//   - 阶段时间线（复用 TaskRow）
//   - 会话元信息（轮次 / 意图 / 跑的 stages）
//   - ctx 关键产物卡片（病历 / 证据 / 鉴别 / 进化 / 最终报告）
//   - 完成后显示"查看最终报告"按钮
//
// 数据来源：
//   - taskRows   — App.tsx 累积的工作流任务
//   - intentMeta — App.tsx 累积的会话元信息
//   - histories  — 全局 specialistHistories，每个 agent 的最新 turn 文本
//   - onJumpToReport — 切到报告 tab

import { useEffect, useRef, useState } from "react";
import type { Turn } from "../api/client";
import { Markdown } from "./Markdown";
import type { TaskRow } from "./TaskRow";

interface Props {
  taskRows: TaskRow[];
  intentMeta: { round?: number; intent?: string; stages?: string[] };
  histories: Record<string, Turn[]>;
  hasSynthesis: boolean;
  onJumpToReport: () => void;
  onJumpToHome: () => void;
  /** S5-D — 点击 agent 名字跳到该 specialist 的 timeline tab。 */
  onJumpToAgent?: (agentName: string) => void;
}

const STAGE_LABEL: Record<string, { icon: string; color: string }> = {
  intake: { icon: "🩺", color: "var(--c-yellow)" },
  knowledge: { icon: "📚", color: "var(--c-blue)" },
  analysis: { icon: "💊", color: "var(--c-red)" },
  knowledge_analysis: { icon: "📚+💊", color: "var(--c-purple)" },
  evolution: { icon: "🧬", color: "var(--c-green)" },
  report: { icon: "📋", color: "var(--c-purple)" },
};

const INTENT_LABEL: Record<string, string> = {
  new_case: "新病例",
  follow_up_drug: "用药复查",
  follow_up_knowledge: "知识补充",
  follow_up_diag: "重新评估",
  meta_query: "进化查询",
  unknown: "未识别",
};

export function WorkflowPane({
  taskRows, intentMeta, histories, hasSynthesis,
  onJumpToReport, onJumpToHome, onJumpToAgent,
}: Props) {
  const completedCount = taskRows.filter((r) => r.status === "done").length;
  const total = taskRows.length;
  const allDone = total > 0 && completedCount === total;
  const hasRun = total > 0;
  const intent = intentMeta.intent;

  return (
    <div style={{
      flex: 1, overflow: "auto",
      background: "var(--bg)",
      display: "flex", flexDirection: "column",
    }}>
      {/* 顶部会话元信息 */}
      {hasRun && (
        <div style={{
          padding: "14px 28px 10px",
          borderBottom: "1px solid var(--border-soft)",
          background: "var(--bg-soft)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            {intent && (
              <span style={{
                padding: "3px 10px", borderRadius: 12,
                background: "var(--accent-soft)", color: "var(--accent-dim)",
                fontSize: 11, fontWeight: 600,
              }}>
                {INTENT_LABEL[intent] || intent}
              </span>
            )}
            {intentMeta.round && (
              <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
                第 <b>{intentMeta.round}</b> 轮
              </span>
            )}
            {intentMeta.stages && (
              <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
                跑了 {intentMeta.stages.length} 个阶段
              </span>
            )}
            <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-faint)" }}>
              {completedCount}/{total} 完成
            </span>
          </div>
        </div>
      )}

      {/* 空状态：还没开始过（垂直水平居中，类似最终报告） */}
      {!hasRun && (
        <div style={{
          flex: 1, display: "flex",
          alignItems: "center", justifyContent: "center",
          flexDirection: "column", gap: 8,
          color: "var(--text-faint)", fontSize: 13,
          padding: 32, textAlign: "center",
        }}>
          <div style={{ fontSize: 36 }}>🔁</div>
          <div style={{ color: "var(--text-dim)", fontWeight: 500, marginBottom: 4 }}>
            还没有诊断记录
          </div>
          <div style={{ fontSize: 12 }}>
            在底部输入临床问题开始第一次问诊，
            <br />
            或回到「主页」查看系统介绍。
          </div>
          <button
            onClick={onJumpToHome}
            style={{ marginTop: 14, padding: "6px 14px" }}
          >回到主页</button>
        </div>
      )}

      {/* 阶段时间线 */}
      {hasRun && (
        <section style={{ padding: "16px 28px 4px" }}>
          <div style={{
            display: "flex", alignItems: "baseline", justifyContent: "space-between",
            marginBottom: 12,
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>
              阶段时间线
            </div>
            {onJumpToAgent && (
              <span style={{ fontSize: 10, color: "var(--text-faint)" }}>
                💡 点击下方 agent 名字 → 跳到该智能体时间线
              </span>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {taskRows.map((row) => (
              <StageTimelineRow key={row.stage} row={row} onJumpToAgent={onJumpToAgent} />
            ))}
          </div>
        </section>
      )}

      {/* 关键产物卡片 */}
      {hasRun && (
        <section style={{ padding: "12px 28px 4px" }}>
          <div style={{
            fontSize: 13, fontWeight: 600, color: "var(--text)",
            marginBottom: 12,
          }}>
            关键产物
          </div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, 1fr)",
            gap: 10,
          }}>
            <ProductCard
              title="病历摘要"
              icon="🩺"
              hint={histories["intake-specialist"]?.[histories["intake-specialist"].length - 1]}
              placeholder="问诊采集后会生成结构化病历（含主诉/现病史/既往史/过敏史）"
              agentName="intake-specialist"
              onJumpToAgent={onJumpToAgent}
            />
            <ProductCard
              title="知识证据"
              icon="📚"
              hint={histories["knowledge-specialist"]?.[histories["knowledge-specialist"].length - 1]}
              placeholder="知识智能体三引擎搜索后会输出关键证据 + 教材引用"
              agentName="knowledge-specialist"
              onJumpToAgent={onJumpToAgent}
            />
            <ProductCard
              title="鉴别诊断"
              icon="💊"
              hint={histories["analysis-specialist"]?.[histories["analysis-specialist"].length - 1]}
              placeholder="分析智能体会输出主诊 + 次诊 + 5 维度推理依据"
              agentName="analysis-specialist"
              onJumpToAgent={onJumpToAgent}
            />
            <ProductCard
              title="进化记录"
              icon="🧬"
              hint={histories["evolution-specialist"]?.[histories["evolution-specialist"].length - 1]}
              placeholder="进化智能体会提取诊断模式三元组 + 是否注入 KG"
              agentName="evolution-specialist"
              onJumpToAgent={onJumpToAgent}
            />
          </div>
        </section>
      )}

      {/* 完成后 CTA */}
      {allDone && (
        <section style={{ padding: "16px 28px 24px" }}>
          <div style={{
            padding: "14px 16px",
            background: "var(--bg-soft)",
            border: "1px solid var(--ok)",
            borderRadius: 8,
            display: "flex", alignItems: "center", gap: 12,
          }}>
            <div style={{ fontSize: 24 }}>✅</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ok)" }}>
                工作流已完成
              </div>
              <div style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 2 }}>
                {hasSynthesis
                  ? "报告已生成，点击下方查看"
                  : "报告还在生成中…"}
              </div>
            </div>
            <button
              onClick={onJumpToReport}
              className="primary"
              style={{ padding: "6px 14px" }}
              disabled={!hasSynthesis}
            >
              查看最终报告 →
            </button>
          </div>
        </section>
      )}
    </div>
  );
}


function StageTimelineRow({ row, onJumpToAgent }: {
  row: TaskRow;
  onJumpToAgent?: (name: string) => void;
}) {
  const meta = STAGE_LABEL[row.stage] || { icon: "•", color: "var(--text-faint)" };
  const isRunning = row.status === "running";
  const isDone = row.status === "done";
  const isError = row.status === "error";
  const color = isRunning || isDone ? meta.color : isError ? "var(--err)" : "var(--text-faint)";

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "8px 12px",
      background: "var(--bg)",
      border: `1px solid ${isRunning ? color : "var(--border-soft)"}`,
      borderRadius: 6,
      position: "relative",
    }}>
      <div style={{
        width: 26, height: 26, borderRadius: 13,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: isDone ? "var(--ok)" : isRunning ? color : isError ? "var(--err)" : "var(--bg-elev)",
        color: isDone || isError || isRunning ? "#fff" : "var(--text-faint)",
        fontSize: 12, fontWeight: 700, flexShrink: 0,
      }}>
        {isDone ? "✓" : isError ? "✗" : isRunning ? (
          <span style={{
            width: 8, height: 8, borderRadius: 4,
            background: "#fff",
            animation: "pulse 1.2s ease-in-out infinite",
          }} />
        ) : "○"}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12, fontWeight: 600,
          color: isDone || isRunning ? "var(--text)" : "var(--text-faint)",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <span style={{ fontSize: 14 }}>{meta.icon}</span>
          {row.label}
          {row.mode === "parallel" && (
            <span style={{
              fontSize: 9, fontWeight: 700,
              padding: "1px 5px", borderRadius: 3,
              background: "var(--c-purple)", color: "#fff",
            }}>并行</span>
          )}
        </div>
        {row.detail && (
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 2 }}>
            {row.detail}
          </div>
        )}
        {row.agentSteps.length > 0 && (
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 2, display: "flex", gap: 4, flexWrap: "wrap" }}>
            {row.agentSteps.map((s) => (
              onJumpToAgent ? (
                <button
                  key={s.name}
                  onClick={() => onJumpToAgent(s.name)}
                  style={{
                    padding: "1px 6px", fontSize: 10, fontFamily: "ui-monospace, monospace",
                    background: "var(--bg-soft)", border: "1px solid var(--border)",
                    borderRadius: 3, cursor: "pointer",
                    color: "var(--text-dim)",
                  }}
                  title={`点击查看 ${s.name} 的详细时间线`}
                >
                  {s.name} →
                </button>
              ) : (
                <span key={s.name} style={{ fontFamily: "ui-monospace, monospace" }}>{s.name}</span>
              )
            ))}
          </div>
        )}
      </div>
      {row.startTs && row.finishTs && (
        <span style={{ fontSize: 10, color: "var(--text-faint)", fontFamily: "ui-monospace, monospace" }}>
          {((row.finishTs - row.startTs) * 1000).toFixed(1)}s
        </span>
      )}
    </div>
  );
}


function ProductCard({
  title, icon, hint, placeholder, agentName, onJumpToAgent,
}: {
  title: string;
  icon: string;
  hint?: Turn;
  placeholder: string;
  agentName?: string;
  onJumpToAgent?: (name: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const text = hint?.text ?? "";
  const hasContent = text.trim().length > 0;
  const canJump = hasContent && agentName && onJumpToAgent;

  return (
    <div
      onClick={canJump ? () => onJumpToAgent!(agentName!) : undefined}
      style={{
        padding: "10px 12px",
        background: "var(--bg)",
        border: "1px solid var(--border-soft)",
        borderRadius: 6,
        cursor: canJump ? "pointer" : "default",
        transition: "background 0.12s, border-color 0.12s",
      }}
      onMouseEnter={(e) => {
        if (canJump) e.currentTarget.style.background = "var(--bg-soft)";
      }}
      onMouseLeave={(e) => {
        if (canJump) e.currentTarget.style.background = "var(--bg)";
      }}
      title={canJump ? `点击查看 ${agentName} 的详细时间线` : undefined}
    >
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        marginBottom: 6,
      }}>
        <span style={{ fontSize: 14 }}>{icon}</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>
          {title}
        </span>
        {hint && (
          <span style={{
            fontSize: 9, marginLeft: "auto",
            padding: "1px 5px", borderRadius: 3,
            background: hint.status === "running" ? "var(--accent-soft)"
                       : hint.status === "error" ? "#fee2e2"
                       : hint.status === "done" ? "#dcfce7" : "var(--bg-elev)",
            color: hint.status === "running" ? "var(--accent-dim)"
                   : hint.status === "error" ? "#991b1b"
                   : hint.status === "done" ? "#15803d" : "var(--text-faint)",
            fontWeight: 600,
          }}>
            {hint.status === "running" ? "生成中" :
             hint.status === "done" ? "已完成" :
             hint.status === "error" ? "出错" : "等待"}
          </span>
        )}
      </div>
      {hasContent ? (
        <div
          onClick={() => setExpanded((v) => !v)}
          style={{
            fontSize: 11, color: "var(--text-dim)",
            lineHeight: 1.5,
            maxHeight: expanded ? "none" : 60,
            overflow: "hidden", cursor: "pointer",
            fontFamily: "ui-monospace, monospace",
            whiteSpace: expanded ? "pre-wrap" : "normal",
          }}
        >
          {expanded
            ? <Markdown text={text} className="md-body" />
            : (text.length > 80 ? text.slice(0, 80) + "…" : text)}
        </div>
      ) : (
        <div style={{ fontSize: 11, color: "var(--text-faint)", fontStyle: "italic" }}>
          {placeholder}
        </div>
      )}
    </div>
  );
}
