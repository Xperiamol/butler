"use client";
import { useEffect, useState } from "react";
import type { AskStage } from "@/lib/api";
import { SOURCE_META } from "@/lib/api";

type Stage = "plan" | "search" | "generating" | "checking";
const LABEL: Record<Stage, string> = { plan: "理解问题，规划检索", search: "检索各平台", generating: "生成回答", checking: "检查权限与结论" };
export type Progress = { stage: Stage; planned: boolean; queries: string[]; planPlatforms: string[]; planSource: string; docs: NonNullable<AskStage["docs"]>; platforms: Record<string, number>; marks: Record<string, number>; start: number };
export const startProgress = (): Progress => ({ stage: "search", planned: false, queries: [], planPlatforms: [], planSource: "", docs: [], platforms: {}, marks: {}, start: Date.now() });
export function advance(p: Progress, s: AskStage): Progress {
  const t = Date.now() - p.start;
  if (s.stage === "planning") return { ...p, planned: true, stage: "plan" };
  if (s.stage === "planned") return { ...p, stage: "search", marks: { ...p.marks, plan: t }, queries: s.queries ?? [], planPlatforms: Array.isArray(s.platforms) ? s.platforms : [], planSource: s.source ?? "" };
  if (s.stage === "retrieved") return { ...p, stage: "generating", docs: s.docs ?? [], platforms: !Array.isArray(s.platforms) && s.platforms ? s.platforms : {}, marks: { ...p.marks, search: t } };
  if (s.stage === "generating") return { ...p, stage: "generating" };
  return { ...p, stage: "checking", marks: { ...p.marks, generating: t } };
}

/** Live view of what the assistant is doing: the plan, which platforms it searched, which sources it found, then generation and the guard. */
export default function AskProgress({ p }: { p: Progress }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 200); return () => clearInterval(timer); }, []);
  const steps: Stage[] = p.planned ? ["plan", "search", "generating", "checking"] : ["search", "generating", "checking"];
  const order = steps.indexOf(p.stage);
  const secs = (ms: number) => `${(ms / 1000).toFixed(1)} 秒`;
  const keyOf = (s: Stage) => s === "plan" ? "plan" : s === "search" ? "search" : "generating";
  const startOf = (i: number) => i === 0 ? 0 : p.marks[keyOf(steps[i - 1])] ?? 0;
  return <div className="ask-progress" role="status" aria-live="polite">
    <ol>{steps.map((s, i) => { const state = i < order ? "done" : i === order ? "active" : "todo"; const end = p.marks[keyOf(s)];
      return <li key={s} className={`is-${state}`}><span className="progress-mark">{state === "done" ? "✓" : state === "active" ? <span className="spinner" /> : ""}</span><b>{LABEL[s]}</b>
        <small>{state === "done" && end !== undefined ? secs(end - startOf(i)) : state === "active" ? secs(now - p.start - startOf(i)) : ""}</small></li>; })}</ol>
    {p.queries.length > 0 && <div className="progress-plan"><span>{p.planSource === "llm" ? "检索计划（模型规划）" : "检索计划"}</span>{p.queries.map((q, i) => <em key={q} style={{ "--i": i } as React.CSSProperties}>{q}</em>)}{p.planPlatforms.length > 0 && p.planPlatforms.length < 4 && <b className="plan-platforms">只查 {p.planPlatforms.map((x) => SOURCE_META[x]?.label ?? x).join(" · ")}</b>}</div>}
    {Object.keys(p.platforms).length > 0 && <div className="progress-platforms">{Object.entries(p.platforms).map(([k, n], i) => <span key={k} style={{ "--i": i, "--c": (SOURCE_META[k] ?? { color: "#888" }).color } as React.CSSProperties}><i />{SOURCE_META[k]?.label ?? k}<b>{n}</b></span>)}<small>共 {p.docs.length || Object.values(p.platforms).reduce((a, b) => a + b, 0)} 份你有权读的资料</small></div>}
    {p.docs.length > 0 && <div className="progress-docs">{p.docs.slice(0, 6).map((d, i) => <em key={d.id} style={{ "--i": i } as React.CSSProperties}><i style={{ background: (SOURCE_META[d.source] ?? { color: "#888" }).color }} />{d.title}</em>)}</div>}
  </div>;
}
