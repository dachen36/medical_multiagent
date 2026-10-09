// 整改方案 v2 — 主页（单屏可见，v2.2 修复）
//
// 用户要求：
//   - 不写技术细节（"LLM 判定意图"等）— 删
//   - 不在介绍后加输入框 — 改为提示文字
//   - 字体整体放大（介绍、核心能力、数据总览、团队总览标题都要大）

import { useEffect, useState } from "react";
import type { Agent } from "../types";
import { displayName } from "../types";
import { AgentIcon } from "./AgentIcon";
import { colorToVar } from "./AgentCard";
import type { ProcessStep, Turn } from "../api/client";

export interface SpecialistRuntime {
  text: string;
  status: "idle" | "running" | "done" | "error";
  errorDetail?: string;
  process: ProcessStep[];
}

interface Stats {
  textbooks: number;
  chapters: number;
  kg_entities: number;
  kg_relations: number;
  drug_pairs: number;
  loaded_at: number;
  source: "live" | "fallback";
}

const EMPTY_STATS: Stats = {
  textbooks: 0, chapters: 0, kg_entities: 0, kg_relations: 0, drug_pairs: 0,
  loaded_at: 0, source: "fallback",
};

interface Props {
  specialists: Agent[];
  runtimes: Record<string, SpecialistRuntime>;
  histories: Record<string, Turn[]>;
  hasSynthesis: boolean;
  onJumpToReport: () => void;
  onJumpToTeam: () => void;
  onSelectAgent?: (name: string) => void;
  onEditAgent?: (name: string) => void;
  onAddAgent?: () => void;
  selectedAgentName?: string | null;
}


// 6 个特点
const FEATURES = [
  { icon: "🩺", title: "结构化问诊", desc: "9 段式问诊 + 病历 CRUD + 实体抽取" },
  { icon: "📚", title: "三引擎知识检索", desc: "TOC + RAG + KG 混合搜索" },
  { icon: "💊", title: "智能分析", desc: "药物互作 / 化验解读 / 5 维度推理" },
  { icon: "🧬", title: "自我进化", desc: "聚合模式 → 提炼规律 → 注入知识图谱" },
  { icon: "🛡️", title: "安全优先", desc: "红旗症状拦截 + 医疗免责声明" },
  { icon: "⚡", title: "协同工作流", desc: "串/并混合编排，意图感知多轮会话" },
];


export function HomePane({
  specialists, runtimes, histories, hasSynthesis,
  onJumpToReport, onJumpToTeam,
  onSelectAgent, onEditAgent, onAddAgent, selectedAgentName,
}: Props) {
  const [stats, setStats] = useState<Stats>(EMPTY_STATS);
  const [loaded, setLoaded] = useState(false);

  // 拉统计
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await fetch("/api/dashboard/stats");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        if (cancelled) return;
        setStats({
          textbooks: data.textbooks ?? 0,
          chapters: data.chapters ?? 0,
          kg_entities: data.kg_entities ?? 0,
          kg_relations: data.kg_relations ?? 0,
          drug_pairs: data.drug_pairs ?? 0,
          loaded_at: Date.now(),
          source: data.source ?? "live",
        });
        setLoaded(true);
      } catch {
        if (!cancelled) setLoaded(true);
      }
    }
    load();
    const t = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return (
    <div style={{
      flex: 1, overflow: "auto", background: "var(--bg)",
      padding: "24px 32px 20px",
    }}>
      {/* ① 平台介绍（v2.2: 字体放大、删 LLM 技术描述） */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
          <span style={{ fontSize: 26, fontWeight: 700, color: "var(--text)" }}>
            MetaClaw
          </span>
          <span style={{ fontSize: 15, color: "var(--text-dim)", fontWeight: 500 }}>
            医疗多智能体协作平台
          </span>
          {loaded && (
            <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-faint)" }}>
              <span
                title={stats.source === "live"
                  ? "实时：扫描 DuckDB / KG 文件得到的实际数值"
                  : "估值：使用 agent 描述中的已知常量（文件扫描失败时兜底）"}
                style={{ cursor: "help" }}
              >
                {stats.source === "live" ? "🟢 实时数据" : "🟡 估值数据"}
              </span>
            </span>
          )}
        </div>
        <div style={{ fontSize: 14, lineHeight: 1.7, color: "var(--text-dim)", marginBottom: 10 }}>
          MetaClaw 由 <b>4 个领域智能体</b>（问诊采集 / 知识检索 / 智能分析 / 自我进化）
          和 <b>1 个协调者</b> 组成，基于临床教材 + 知识图谱 + 病历库，
          走完「问诊 → 检索 → 分析 → 进化 → 最终报告」完整链路。
        </div>
        <div style={{
          padding: "8px 12px",
          background: "var(--accent-soft)",
          border: "1px solid var(--accent)",
          borderRadius: 6,
          fontSize: 13, color: "var(--accent-dim)",
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <span style={{ fontSize: 16 }}>👇</span>
          <span><b>使用方法：</b>在<strong>页面底部的输入框</strong>描述临床问题（症状、年龄、病程），系统会自动开始问诊。</span>
        </div>
      </div>

      {/* ② 横排：核心能力 + 数据总览（5 项） */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 14,
        marginBottom: 16,
      }}>
        {/* 核心能力 6 个（2 行 3 列） */}
        <div style={{
          padding: "14px 16px",
          background: "var(--bg-soft)",
          border: "1px solid var(--border-soft)",
          borderRadius: 8,
        }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: "var(--text)",
            marginBottom: 10,
          }}>核心能力</div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: 8,
          }}>
            {FEATURES.map((f) => (
              <div key={f.title} style={{
                padding: "10px 12px",
                background: "var(--bg)", borderRadius: 5,
              }} title={f.desc}>
                <div style={{ fontSize: 22, marginBottom: 4 }}>{f.icon}</div>
                <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 13, marginBottom: 2 }}>
                  {f.title}
                </div>
                <div style={{ color: "var(--text-faint)", fontSize: 11, lineHeight: 1.4 }}>
                  {f.desc}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 数据总览 5 项（1 行 5 列） */}
        <div style={{
          padding: "14px 16px",
          background: "var(--bg-soft)",
          border: "1px solid var(--border-soft)",
          borderRadius: 8,
        }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: "var(--text)",
            marginBottom: 10,
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span>数据总览</span>
            {hasSynthesis && (
              <button
                onClick={onJumpToReport}
                style={{
                  fontSize: 11, padding: "4px 10px",
                  background: "var(--accent)", color: "#fff",
                  border: "none", borderRadius: 4, cursor: "pointer",
                }}
              >查看最终报告 →</button>
            )}
          </div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(5, 1fr)",
            gap: 6,
          }}>
            <StatCell label="教材" value={stats.textbooks} unit="本" icon="📘" />
            <StatCell label="章节" value={stats.chapters} unit="章" icon="📑" />
            <StatCell label="KG 实体" value={stats.kg_entities} unit="" icon="🕸️" />
            <StatCell label="KG 关系" value={stats.kg_relations} unit="" icon="🔗" />
            <StatCell label="药物互作" value={stats.drug_pairs} unit="对" icon="💊" />
          </div>
        </div>
      </div>

      {/* ③ 团队总览 4 卡 + 添加按钮（每卡带 description） */}
      <div>
        <div style={{
          display: "flex", alignItems: "baseline", justifyContent: "space-between",
          marginBottom: 8,
        }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}>
            团队总览
            <span style={{ fontSize: 12, color: "var(--text-faint)", marginLeft: 10, fontWeight: 400 }}>
              {specialists.length} 位领域智能体 · 点击卡片查看详细时间线
            </span>
          </div>
          {onAddAgent && (
            <button onClick={onAddAgent} style={{ padding: "4px 12px", fontSize: 12 }}>
              + 添加
            </button>
          )}
        </div>
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 10,
        }}>
          {specialists.map((a) => (
            <SpecialistCard
              key={a.name}
              agent={a}
              runtime={runtimes[a.name]}
              historyCount={histories[a.name]?.length ?? 0}
              onSelect={onSelectAgent ? () => onSelectAgent(a.name) : undefined}
              onEdit={onEditAgent ? () => onEditAgent(a.name) : undefined}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCell({ label, value, unit, icon }: {
  label: string; value: number; unit: string; icon: string;
}) {
  return (
    <div style={{
      padding: "8px 10px", background: "var(--bg)", borderRadius: 5,
      display: "flex", flexDirection: "column", gap: 2,
    }} title={`${label}: ${value.toLocaleString()} ${unit}`}>
      <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
        <span style={{ fontSize: 14 }}>{icon}</span>
        <span style={{ color: "var(--text-dim)" }}>{label}</span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
        <span style={{
          fontSize: 20, fontWeight: 700, color: "var(--accent-dim)",
          fontFamily: "ui-monospace, monospace", fontVariantNumeric: "tabular-nums",
        }}>
          {value >= 1000 ? (value / 1000).toFixed(1) + "k" : value.toLocaleString()}
        </span>
        {unit && <span style={{ fontSize: 11, color: "var(--text-faint)" }}>{unit}</span>}
      </div>
    </div>
  );
}


function SpecialistCard({
  agent, runtime, historyCount, onSelect, onEdit,
}: {
  agent: Agent;
  runtime?: SpecialistRuntime;
  historyCount: number;
  onSelect?: () => void;
  onEdit?: () => void;
}) {
  const color = colorToVar(agent.color);
  const status = runtime?.status ?? "idle";
  const isLive = status === "running";
  const latestText = runtime?.text ?? "";

  return (
    <div
      onClick={onSelect}
      style={{
        border: `1px solid ${isLive ? color : "var(--border)"}`,
        borderRadius: 8,
        background: "var(--bg)",
        padding: "12px 14px",
        position: "relative", overflow: "hidden",
        cursor: onSelect ? "pointer" : "default",
      }}
    >
      <span style={{
        position: "absolute", top: 0, left: 0, bottom: 0, width: 3, background: color,
      }} />
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 6,
      }}>
        <div style={{ color, flexShrink: 0 }}>
          <AgentIcon name={agent.name} size={22} />
        </div>
        <div style={{
          fontWeight: 600, fontSize: 14, color: "var(--text)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          flex: 1,
        }} title={agent.name}>
          {displayName(agent)}
        </div>
        {onEdit && (
          <button
            onClick={(e) => { e.stopPropagation(); onEdit(); }}
            title="编辑"
            style={{ padding: "1px 8px", fontSize: 11, lineHeight: 1.2 }}
          >✎</button>
        )}
      </div>
      <div style={{
        fontSize: 12, color: "var(--text-dim)",
        lineHeight: 1.55, marginBottom: 6,
        display: "-webkit-box", WebkitLineClamp: 2,
        WebkitBoxOrient: "vertical", overflow: "hidden",
      }} title={agent.description}>
        {agent.description || "—"}
      </div>
      <div style={{
        fontSize: 11, color: isLive ? color : "var(--text-faint)",
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {isLive ? <span style={{ color }}>● {latestText || "运行中..."}</span> :
         status === "done" ? `✓ 完成 · ${latestText.length} 字` :
         historyCount > 0 ? `${historyCount} 轮历史对话` :
         `${agent.skills.length} 技能 · ${agent.tools.length} 工具 · 最多 ${agent.max_turns} 轮`}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// 辅助函数
// ---------------------------------------------------------------------------
export function hasAnySpecialistHistory(
  histories: Record<string, Turn[]>,
): boolean {
  for (const turns of Object.values(histories)) {
    if (turns.length > 0) return true;
  }
  return false;
}
