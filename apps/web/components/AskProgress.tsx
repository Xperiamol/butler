"use client";
import { useEffect, useState } from "react";
import type { AskStage } from "@/lib/api";
import { SOURCE_META } from "@/lib/api";

const STEPS = [{ key: "search", label: "检索资料" }, { key: "generating", label: "生成回答" }, { key: "checking", label: "检查权限与结论" }] as const;
export type Progress = { stage: "search" | "generating" | "checking"; docs: NonNullable<AskStage["docs"]>; marks: Record<string, number>; start: number };
export const startProgress = (): Progress => ({ stage: "search", docs: [], marks: {}, start: Date.now() });
export function advance(p: Progress, s: AskStage): Progress {
  const t = Date.now() - p.start;
  if (s.stage === "retrieved") return { ...p, stage: "generating", docs: s.docs ?? [], marks: { ...p.marks, search: t } };
  if (s.stage === "generating") return { ...p, stage: "generating" };
  return { ...p, stage: "checking", marks: { ...p.marks, generating: t } };
}

/** Live view of what the assistant is doing while it works: which sources it found, generation, and the guard. */
export default function AskProgress({ p }: { p: Progress }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 200); return () => clearInterval(timer); }, []);
  const order = STEPS.findIndex((s) => s.key === p.stage);
  const secs = (ms: number) => `${(ms / 1000).toFixed(1)} 秒`;
  return <div className="ask-progress" role="status" aria-live="polite">
    <ol>{STEPS.map((s, i) => { const state = i < order ? "done" : i === order ? "active" : "todo"; const at = i === 0 ? p.marks.search : i === 1 ? p.marks.generating : undefined, from = i === 0 ? 0 : i === 1 ? p.marks.search : p.marks.generating;
      return <li key={s.key} className={`is-${state}`}><span className="progress-mark">{state === "done" ? "✓" : state === "active" ? <span className="spinner" /> : ""}</span><b>{s.label}</b>
        <small>{state === "done" ? secs((at ?? 0) - (from ?? 0)) : state === "active" ? secs(now - p.start - (from ?? 0)) : ""}</small></li>; })}</ol>
    {p.docs.length > 0 && <div className="progress-docs"><span>找到 {p.docs.length} 份你有权读的资料</span>{p.docs.map((d, i) => <em key={d.id} style={{ "--i": i } as React.CSSProperties}><i style={{ background: (SOURCE_META[d.source] ?? { color: "#888" }).color }} />{d.title}</em>)}</div>}
  </div>;
}
