// 整改方案 v2.1 §C3 — 问诊 store
// 适配 LLM-driven 后端：
//   - 后端可能返回 0 个问题（信息已够）→ ready 状态
//   - 后端可能返回 1 个或多个问题（不再固定 5 个）
//   - 每题带 rationale（前端展示）
//   - 进度文案改为"问题 N"（无分母）

import { create } from "zustand";

export interface IntakeQuestion {
  id: string;
  text: string;
  options: string[];
  allow_free_text: boolean;
  required: boolean;
  multi?: boolean;
  /** LLM/rule-based 解释为什么问这个 */
  rationale?: string;
}

export interface IntakePlan {
  questions: IntakeQuestion[];
  is_complete: boolean;
  ready_to_run: boolean;
  reasoning: string;          // 整体判断理由（前端展示给用户）
  next_action: "answer" | "run" | "clarify";
}

export interface ClassificationResult {
  is_medical: boolean;
  l1_intent: string;
  needs_intake: boolean;
  l2_intent: string;
  stages: string[];
  reasoning: string;
  confidence: number;
  followup_hint: string;
}

interface IntakeState {
  // 输入
  userRequest: string;
  sessionId: string | null;
  // 入口分类结果
  classification: ClassificationResult | null;
  // 当前题
  questions: IntakeQuestion[];
  // 已答
  answers: Record<string, string>;
  answeredOrder: string[];
  // 状态
  status: "idle" | "loading" | "asking" | "ready" | "running" | "cancelled" | "red_flag" | "non_medical" | "error";
  errorMsg: string;
  // 元信息
  lastReasoning: string;          // 后端最近一次 plan 的 reasoning
  round: number;

  // actions
  start: (userRequest: string) => void;
  /** 调 /api/intake/classify，结果存 state，状态机按 is_medical/needs_intake 分流 */
  classify: (userRequest: string, sessionId: string | null) => Promise<ClassificationResult | null>;
  setPlan: (plan: IntakePlan) => void;
  setSessionId: (sid: string) => void;
  answerCurrent: (qid: string, value: string) => Promise<void>;
  goBack: () => void;
  reset: () => void;
  cancel: () => void;
}

export const useIntake = create<IntakeState>((set, get) => ({
  userRequest: "",
  sessionId: null,
  classification: null,
  questions: [],
  answers: {},
  answeredOrder: [],
  status: "idle",
  errorMsg: "",
  lastReasoning: "",
  round: 0,

  start: (userRequest) => set({
    userRequest,
    questions: [],
    answers: {},
    answeredOrder: [],
    round: 0,
    status: "loading",
    errorMsg: "",
    classification: null,
    lastReasoning: "",
    sessionId: null,
  }),

  classify: async (userRequest, sessionId) => {
    set({
      userRequest,
      questions: [],
      answers: {},
      answeredOrder: [],
      round: 0,
      status: "loading",
      errorMsg: "",
      classification: null,
      lastReasoning: "",
      sessionId: sessionId ?? null,
    });
    try {
      const r = await fetch("/api/intake/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_request: userRequest, session_id: sessionId }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data: ClassificationResult = await r.json();
      set({ classification: data });
      if (!data.is_medical) {
        set({ status: "non_medical" });
      } else if (!data.needs_intake) {
        // 追问场景：直接 ready
        set({ status: "ready" });
      }
      return data;
    } catch (e) {
      set({ status: "error", errorMsg: String(e) });
      return null;
    }
  },

  setPlan: (plan) => {
    if (plan.is_complete || plan.ready_to_run) {
      set({ status: "ready", lastReasoning: plan.reasoning });
      return;
    }
    set({
      questions: plan.questions,
      status: "asking",
      lastReasoning: plan.reasoning,
      round: get().round + 1,
    });
  },

  setSessionId: (sid) => set({ sessionId: sid }),

  answerCurrent: async (qid, value) => {
    const state = get();
    const newAnswers = { ...state.answers, [qid]: value };
    const newOrder = state.answeredOrder.includes(qid)
      ? state.answeredOrder
      : [...state.answeredOrder, qid];
    set({
      answers: newAnswers,
      answeredOrder: newOrder,
      status: "loading",
    });
    try {
      const r = await fetch("/api/intake/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_request: state.userRequest,
          partial_qa: newAnswers,
          history: newOrder.map((id) => ({
            qid: id, value: newAnswers[id],
            text: state.questions.find((q) => q.id === id)?.text,
          })),
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const plan: IntakePlan = await r.json();
      get().setPlan(plan);
    } catch (e) {
      set({ status: "error", errorMsg: String(e) });
      throw e;
    }
  },

  goBack: () => {
    const state = get();
    if (state.answeredOrder.length === 0) return;
    const lastQid = state.answeredOrder[state.answeredOrder.length - 1];
    const newAnswers = { ...state.answers };
    delete newAnswers[lastQid];
    const newOrder = state.answeredOrder.slice(0, -1);
    set({
      answers: newAnswers,
      answeredOrder: newOrder,
      status: "loading",
    });
    void (async () => {
      try {
        const r = await fetch("/api/intake/plan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_request: state.userRequest,
            partial_qa: newAnswers,
            history: newOrder.map((id) => ({
              qid: id, value: newAnswers[id],
              text: state.questions.find((q) => q.id === id)?.text,
            })),
          }),
        });
        if (r.ok) {
          const plan: IntakePlan = await r.json();
          get().setPlan(plan);
        }
      } catch { /* ignore */ }
    })();
  },

  reset: () => set({
    userRequest: "",
    sessionId: null,
    classification: null,
    questions: [],
    answers: {},
    answeredOrder: [],
    round: 0,
    status: "idle",
    errorMsg: "",
    lastReasoning: "",
  }),

  cancel: () => set({ status: "cancelled" }),
}));


// ---------------------------------------------------------------------------
// 辅助函数
// ---------------------------------------------------------------------------
export function currentQuestion(state: IntakeState): IntakeQuestion | null {
  return state.questions[0] ?? null;
}

/** 进度标签：旧"1/5" → 新"问题 1"（无固定分母） */
export function progressLabel(state: IntakeState): string {
  const answered = state.answeredOrder.length;
  if (state.status === "asking") {
    return `问题 ${answered + 1}`;
  }
  if (state.status === "ready") {
    return "信息已就绪";
  }
  return `已答 ${answered} 题`;
}

export async function commitIntake(
  userRequest: string,
  qa: Record<string, string>,
  sessionId: string | null,
): Promise<{ session_id: string; patient_record: any }> {
  const r = await fetch("/api/intake/commit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_request: userRequest,
      qa,
      session_id: sessionId,
    }),
  });
  if (!r.ok) throw new Error(`intake_commit failed: HTTP ${r.status}`);
  return r.json();
}
