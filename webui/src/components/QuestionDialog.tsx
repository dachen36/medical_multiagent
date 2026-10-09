// 整改方案 v2.1 §C3 — 问诊弹窗（LLM-driven 适配）
// 关键变化：
//   1. 进度去分母（"问题 1" 而非 "1/5"）
//   2. 每题显示 LLM 生成的 rationale（为什么问这个）
//   3. 0 题自动 ready 状态（LLM 判定信息已够）
//   4. 入口分类状态分流：non_medical 友好提示
//   5. 跟进追问：ready 状态自动跳 workflow

import { useState, useEffect } from "react";
import {
  useIntake, currentQuestion, progressLabel, commitIntake,
  type IntakeQuestion, type ClassificationResult,
} from "../hooks/useIntake";

interface Props {
  /** 关闭弹窗（用户点 ESC 或 X） */
  onClose: () => void;
  /** intake 完成（红旗/就绪/取消/非医疗都走这里） */
  onCompleted: (result: IntakeCompleted) => void;
}

export interface IntakeCompleted {
  kind: "ready" | "cancelled" | "red_flag" | "non_medical";
  userRequest: string;
  sessionId: string | null;
  patientRecord: any;
  answers: Record<string, string>;
  classification?: ClassificationResult;
}

export function QuestionDialog({ onClose, onCompleted }: Props) {
  const intake = useIntake();
  const q = currentQuestion(intake);
  const progress = progressLabel(intake);

  const [selected, setSelected] = useState<string | null>(null);
  const [freeText, setFreeText] = useState("");
  const [multiSelected, setMultiSelected] = useState<string[]>([]);

  // 切题时重置
  useEffect(() => {
    setSelected(null);
    setFreeText("");
    setMultiSelected([]);
  }, [q?.id]);

  // ESC 关闭
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function handleConfirm() {
    if (!q) return;
    let value = "";
    if (q.multi) {
      value = [...multiSelected, ...(freeText.trim() ? [freeText.trim()] : [])].join("、");
      if (!value) return;
    } else {
      if (selected) value = selected;
      else if (freeText.trim()) value = freeText.trim();
      else return;
    }
    try {
      await intake.answerCurrent(q.id, value);
    } catch (e) {
      console.error("answerCurrent failed:", e);
    }
  }

  async function handleCommit() {
    try {
      const { session_id, patient_record } = await commitIntake(
        intake.userRequest,
        intake.answers,
        intake.sessionId,
      );
      intake.setSessionId(session_id);
      onCompleted({
        kind: "ready",
        userRequest: intake.userRequest,
        sessionId: session_id,
        patientRecord: patient_record,
        answers: intake.answers,
        classification: intake.classification ?? undefined,
      });
    } catch (e) {
      console.error("commitIntake failed:", e);
    }
  }

  function handleCancel() {
    onCompleted({
      kind: "cancelled",
      userRequest: intake.userRequest,
      sessionId: intake.sessionId,
      patientRecord: null,
      answers: intake.answers,
      classification: intake.classification ?? undefined,
    });
  }

  // 红旗：直接完成
  if (intake.status === "red_flag") {
    return (
      <ModalShell onClose={onClose} title="🚨 紧急红旗" badge="intake">
        <div style={{
          padding: "12px 14px", background: "#fee2e2",
          color: "#991b1b", borderRadius: 6, fontSize: 13, lineHeight: 1.6,
          marginBottom: 12,
        }}>
          检测到红旗症状（胸痛 / 呼吸困难 / 意识改变 / 大出血 / 卒中 / 高热惊厥等）。
          <br />
          <b>请立即拨打 120</b>，并停止进一步问诊。
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="primary"
            onClick={() => onCompleted({
              kind: "red_flag",
              userRequest: intake.userRequest,
              sessionId: null,
              patientRecord: null,
              answers: {},
              classification: intake.classification ?? undefined,
            })}
            style={{ padding: "6px 14px" }}
          >
            我已知晓，停止诊断
          </button>
          <button onClick={onClose} style={{ padding: "6px 14px" }}>关闭</button>
        </div>
      </ModalShell>
    );
  }

  // 非医疗：友好提示
  if (intake.status === "non_medical") {
    const cls = intake.classification;
    const isChitchat = cls?.l1_intent === "chitchat";
    return (
      <ModalShell onClose={onClose} title={isChitchat ? "👋 你好" : "⚠️ 非医疗请求"} badge="intake">
        <div style={{
          padding: "12px 14px", background: "var(--bg-soft)",
          borderRadius: 6, fontSize: 13, lineHeight: 1.7,
          marginBottom: 12, color: "var(--text-dim)",
        }}>
          {isChitchat
            ? <>我是 <b>MetaClaw</b>，医疗多智能体协作平台。<br />
              请在底部输入框描述临床症状，开始问诊。</>
            : <>我是 <b>医疗诊断系统</b>，无法回答医疗以外的问题。<br />
              请描述症状、用药问题或医学知识查询。</>
          }
          {cls?.reasoning && (
            <div style={{
              marginTop: 10, padding: "6px 10px",
              background: "var(--bg)", borderRadius: 4,
              fontSize: 11, color: "var(--text-faint)",
            }}>
              💡 分类理由：{cls.reasoning}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={onClose} style={{ padding: "6px 14px" }}>我知道了</button>
        </div>
      </ModalShell>
    );
  }

  // 错误
  if (intake.status === "error") {
    return (
      <ModalShell onClose={onClose} title="⚠️ 出错了" badge="intake">
        <div style={{
          padding: "12px 14px", background: "#fee2e2",
          color: "#991b1b", borderRadius: 6, fontSize: 13, marginBottom: 12,
        }}>
          入口分类服务异常：{intake.errorMsg || "未知错误"}
        </div>
        <button onClick={onClose} style={{ padding: "6px 14px" }}>关闭</button>
      </ModalShell>
    );
  }

  // Loading
  if (intake.status === "loading") {
    return (
      <ModalShell onClose={onClose} title="智能规划中" badge="intake · LLM">
        <div style={{ padding: 32, textAlign: "center", color: "var(--text-faint)" }}>
          <div style={{
            width: 16, height: 16, borderRadius: 8,
            border: "2px solid var(--accent)",
            borderTopColor: "transparent",
            animation: "spin 0.8s linear infinite",
            display: "inline-block", marginBottom: 10,
          }} />
          <div>LLM 正在分析...</div>
          {intake.lastReasoning && (
            <div style={{ marginTop: 8, fontSize: 11 }}>{intake.lastReasoning}</div>
          )}
        </div>
      </ModalShell>
    );
  }

  // Ready
  if (intake.status === "ready") {
    const cls = intake.classification;
    return (
      <ModalShell onClose={onClose} title="✓ 准备开始诊断" badge="intake">
        <div style={{
          padding: "12px 14px", background: "var(--bg-soft)",
          borderRadius: 6, fontSize: 12, color: "var(--text-dim)",
          marginBottom: 12, lineHeight: 1.7,
        }}>
          {intake.lastReasoning && (
            <div style={{ marginBottom: 8 }}>💡 {intake.lastReasoning}</div>
          )}
          {intake.answeredOrder.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              已采集 <b>{intake.answeredOrder.length}</b> 项关键信息
              {intake.answeredOrder.length === 0 && intake.userRequest && (
                <span>（未问诊，LLM 判定信息已够）</span>
              )}
            </div>
          )}
          {cls?.stages && cls.stages.length > 0 && (
            <div>
              <div style={{ marginBottom: 4 }}>本次将执行的工作流：</div>
              <div style={{
                display: "flex", gap: 6, flexWrap: "wrap",
              }}>
                {cls.stages.map((s) => (
                  <span key={s} style={{
                    padding: "1px 8px", borderRadius: 3,
                    background: "var(--accent-soft)", color: "var(--accent-dim)",
                    fontSize: 11, fontWeight: 600,
                  }}>
                    {stageLabel(s)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="primary"
            onClick={handleCommit}
            style={{ padding: "6px 14px" }}
          >
            开始诊断 →
          </button>
          <button onClick={handleCancel} style={{ padding: "6px 14px" }}>取消</button>
        </div>
      </ModalShell>
    );
  }

  // Asking - 显示当前题
  if (!q) {
    return (
      <ModalShell onClose={onClose} title="问诊" badge="intake">
        <div style={{ padding: 24, textAlign: "center", color: "var(--text-faint)" }}>
          （等待下一题）
        </div>
      </ModalShell>
    );
  }

  return (
    <ModalShell onClose={onClose} title="问诊采集" badge={`intake · ${progress}`}>
      {/* LLM 整体判断理由（最新一次 plan 的 reasoning） */}
      {intake.lastReasoning && (
        <div style={{
          padding: "6px 10px", marginBottom: 12,
          background: "var(--bg-soft)", borderRadius: 4,
          fontSize: 11, color: "var(--text-dim)", lineHeight: 1.5,
        }}>
          💡 {intake.lastReasoning}
        </div>
      )}

      <div style={{ marginBottom: 10 }}>
        <div style={{
          fontSize: 14, fontWeight: 600, color: "var(--text)",
          marginBottom: 6,
        }}>
          {q.text}
          {q.required && <span style={{ color: "var(--err)", marginLeft: 4 }}>*</span>}
        </div>
        {q.rationale && (
          <div style={{
            fontSize: 11, color: "var(--accent-dim)",
            marginBottom: 6, fontStyle: "italic",
          }}>
            ↳ {q.rationale}
          </div>
        )}
        <div style={{ fontSize: 11, color: "var(--text-faint)" }}>
          {q.multi
            ? "可多选 · 也可自由输入补充"
            : q.options.length > 0
              ? "单选 · 也可自由输入补充"
              : "请用自由输入回答"}
        </div>
      </div>

      {q.options.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
          {q.options.map((opt) => {
            const isSelected = q.multi
              ? multiSelected.includes(opt)
              : selected === opt;
            return (
              <button
                key={opt}
                onClick={() => {
                  if (q.multi) {
                    setMultiSelected((cur) => isSelected
                      ? cur.filter((x) => x !== opt)
                      : [...cur, opt]);
                  } else {
                    setSelected(opt);
                  }
                }}
                style={{
                  padding: "5px 10px", fontSize: 12,
                  border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                  background: isSelected ? "var(--accent-soft)" : "var(--bg)",
                  color: isSelected ? "var(--accent-dim)" : "var(--text)",
                  borderRadius: 16, cursor: "pointer",
                  fontWeight: isSelected ? 600 : 400,
                }}
              >
                {isSelected ? "✓ " : ""}{opt}
              </button>
            );
          })}
        </div>
      )}

      {q.allow_free_text && (
        <div style={{ marginBottom: 12 }}>
          <input
            type="text"
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder={q.options.length > 0 ? "或自由输入补充…" : "请输入您的回答…"}
            style={{ width: "100%", padding: "6px 10px", fontSize: 12 }}
          />
        </div>
      )}

      <div style={{
        display: "flex", gap: 8, alignItems: "center",
        borderTop: "1px solid var(--border-soft)", paddingTop: 10,
      }}>
        <button
          onClick={() => intake.goBack()}
          disabled={intake.answeredOrder.length === 0}
          style={{ padding: "5px 12px", fontSize: 12 }}
        >
          ← 上一步
        </button>
        <div style={{
          flex: 1, fontSize: 11, color: "var(--text-faint)",
          textAlign: "center",
        }}>
          {intake.answeredOrder.length > 0
            ? `已答 ${intake.answeredOrder.length} 题`
            : "（第 1 题）"}
        </div>
        <button
          className="primary"
          onClick={handleConfirm}
          disabled={q.multi
            ? (multiSelected.length === 0 && !freeText.trim())
            : q.options.length > 0
              ? (!selected && !freeText.trim())
              : !freeText.trim()}
          style={{ padding: "5px 14px", fontSize: 12 }}
        >
          确认并继续 →
        </button>
      </div>

      <div style={{
        marginTop: 8, fontSize: 10, color: "var(--text-faint)",
        textAlign: "right",
      }}>
        ESC 取消 · 已答问题可随时回改
      </div>
    </ModalShell>
  );
}


// ---------------------------------------------------------------------------
// Modal shell
// ---------------------------------------------------------------------------
function ModalShell({
  onClose, title, badge, children,
}: {
  onClose: () => void;
  title: string;
  badge?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0,
        background: "rgba(15, 23, 42, 0.45)",
        zIndex: 3000,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 560, maxWidth: "94vw",
          background: "var(--bg)",
          borderRadius: 10,
          boxShadow: "0 20px 60px rgba(15, 23, 42, 0.25)",
          padding: 20,
          display: "flex", flexDirection: "column",
        }}
      >
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 12,
        }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: "var(--text)" }}>
              {title}
            </span>
            {badge && (
              <span style={{
                fontSize: 10, fontWeight: 600,
                color: "var(--accent-dim)",
                background: "var(--accent-soft)",
                padding: "2px 8px", borderRadius: 3,
              }}>
                {badge}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            title="关闭（ESC）"
            style={{
              background: "transparent", border: "none",
              fontSize: 18, color: "var(--text-faint)",
              cursor: "pointer", padding: "0 4px",
            }}
          >×</button>
        </div>
        {children}
      </div>
    </div>
  );
}


function stageLabel(s: string): string {
  const m: Record<string, string> = {
    intake: "问诊采集",
    knowledge: "知识检索",
    analysis: "智能分析",
    knowledge_analysis: "知识+分析",
    evolution: "自我进化",
    report: "最终报告",
  };
  return m[s] || s;
}
