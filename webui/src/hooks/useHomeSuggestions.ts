// 整改方案 S5-C — 主页智能建议 hook
// 调 /api/suggestions，缓存 stage 防止频繁请求
import { useEffect, useState, useCallback } from "react";

export interface Suggestion {
  icon: string;
  label: string;
  query: string;
  intent: string;
}

interface State {
  stage: string;
  suggestions: Suggestion[];
  source: "live" | "fallback";
  loading: boolean;
}

export function useHomeSuggestions(sessionId: string | null) {
  const [state, setState] = useState<State>({
    stage: "pre_intake",
    suggestions: [],
    source: "fallback",
    loading: false,
  });

  const load = useCallback(async (refresh: boolean) => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const r = await fetch("/api/suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, refresh }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      // S5-C 调试日志
      console.log("[home-suggestions] loaded", { sessionId, stage: d.stage, count: (d.suggestions || []).length });
      setState({
        stage: d.stage,
        suggestions: d.suggestions || [],
        source: d.source || "fallback",
        loading: false,
      });
    } catch (e) {
      console.error("[home-suggestions] load failed", e);
      setState((s) => ({ ...s, loading: false }));
    }
  }, [sessionId]);

  // session 变化时重新加载
  useEffect(() => { load(false); }, [load]);

  return { ...state, refresh: () => load(true) };
}
