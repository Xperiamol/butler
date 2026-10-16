"use client";
import { useEffect, useRef, useState } from "react";
import { SOURCE_META, workspaceApi, type ScenarioDef, type ScenarioEvent } from "@/lib/api";
import { CountUp, Reveal } from "./motion";

type StepState = { status: "todo" | "running" | "pass" | "fail"; seconds?: number; checks?: { label: string; ok: boolean }[]; answer?: ScenarioEvent["answer"]; audit?: ScenarioEvent["audit"] };
type RunState = { running: boolean; steps: StepState[]; passed?: number; total?: number; error?: string };

export default function ScenariosPanel() {
  const [defs, setDefs] = useState<ScenarioDef[]>([]);
  const [runs, setRuns] = useState<Record<string, RunState>>({});
  const [all, setAll] = useState(false);
  const cancel = useRef(false);
  useEffect(() => { workspaceApi.scenarios().then(setDefs).catch(() => {}); }, []);
  const setRun = (id: string, f: (r: RunState) => RunState) => setRuns((m) => ({ ...m, [id]: f(m[id] ?? { running: false, steps: [] }) }));
  const run = async (sc: ScenarioDef) => {
    setRuns((m) => ({ ...m, [sc.id]: { running: true, steps: sc.steps.map(() => ({ status: "todo" as const })) } }));
    try {
      await workspaceApi.runScenario(sc.id, (e) => {
        if (e.event === "step" && e.i !== undefined) setRun(sc.id, (r) => ({ ...r, steps: r.steps.map((s, i) => i === e.i ? { ...s, status: "running" } : s) }));
        else if (e.event === "result" && e.i !== undefined) setRun(sc.id, (r) => ({ ...r, steps: r.steps.map((s, i) => i === e.i ? { status: e.status ?? "fail", seconds: e.seconds, checks: e.checks, answer: e.answer, audit: e.audit } : s) }));
        else if (e.event === "done") setRun(sc.id, (r) => ({ ...r, running: false, passed: e.passed, total: e.total }));
      });
    } catch (error) { setRun(sc.id, (r) => ({ ...r, running: false, error: error instanceof Error ? error.message : "用例没有运行起来。" })); }
    setRun(sc.id, (r) => ({ ...r, running: false }));
  };
  const runAll = async () => { setAll(true); cancel.current = false; for (const sc of defs) { if (cancel.current) break; await run(sc); } setAll(false); };
  const passedSteps = Object.values(runs).reduce((n, r) => n + r.steps.filter((s) => s.status === "pass").length, 0);
  const failedSteps = Object.values(runs).reduce((n, r) => n + r.steps.filter((s) => s.status === "fail").length, 0);
  return <main className="admin-page scenarios-page">
    <div className="admin-heading"><div><span className="overline">体验 / 赛题用例验收</span><h1>赛题要求的五个用例，自己跑一遍。</h1><p>每个用例都是真实执行：真实提问、真实变更来源平台、真实同步，再对回答逐项断言。红色的就是没做到，不会被藏起来。</p></div>
      <div className="scenario-total"><div><strong><CountUp value={passedSteps} /></strong><span>项通过</span></div><div className={failedSteps ? "bad" : ""}><strong><CountUp value={failedSteps} /></strong><span>项未通过</span></div></div></div>
    <div className="scenario-actions"><button className="btn primary" disabled={all || Object.values(runs).some((r) => r.running)} onClick={runAll}>{all ? "正在依次运行…" : "全部运行"}<span aria-hidden="true">▶</span></button>{all && <button className="btn" onClick={() => { cancel.current = true; }}>运行完当前用例后停止</button>}<span className="quiet-tag">真实模型下每个提问约 15–25 秒，全部跑完约 6–8 分钟</span></div>
    <div className="scenario-list">{defs.map((sc, k) => { const r = runs[sc.id]; const pass = r && r.steps.length > 0 && r.steps.every((s) => s.status === "pass"); const fail = r?.steps.some((s) => s.status === "fail");
      return <Reveal key={sc.id} delay={k * 50} className="scenario-card-wrap"><article className={`scenario-card ${pass ? "is-pass" : fail ? "is-fail" : ""}`}>
        <header><div><h3>{sc.title}</h3><p>{sc.brief}</p></div><button className="btn sm" disabled={all || r?.running} onClick={() => run(sc)}>{r?.running ? "运行中…" : r?.steps.length ? "再运行" : "运行"}</button></header>
        <ol className="scenario-steps">{sc.steps.map((st, i) => { const s = r?.steps[i]; const state = s?.status ?? "todo";
          return <li key={i} className={`is-${state}`}><span className="step-mark">{state === "pass" ? "✓" : state === "fail" ? "✗" : state === "running" ? <span className="spinner" /> : i + 1}</span>
            <div><b>{st.label}</b><small>{st.as ? `身份 ${st.as}` : st.kind === "mutate" ? "来源平台变更" : st.kind}{s?.seconds !== undefined ? ` · ${s.seconds} 秒` : ""}</small>{st.q && <p className="step-q">“{st.q}”</p>}
              {s?.checks && <ul className="step-checks">{s.checks.map((c, j) => <li key={j} className={c.ok ? "ok" : "no"}><span>{c.ok ? "✓" : "✗"}</span>{c.label}</li>)}</ul>}
              {s?.answer && <details><summary>回答摘录（{s.answer.status}{s.answer.trace?.platforms ? ` · ${Object.entries(s.answer.trace.platforms).map(([p, n]) => `${SOURCE_META[p]?.label ?? p} ${n}`).join(" / ")}` : ""}）</summary><p className="step-answer">{s.answer.text.slice(0, 700)}{s.answer.text.length > 700 ? "…" : ""}</p><div className="step-cites">{s.answer.citations.slice(0, 10).map((c) => <span key={c.id} title={c.id}><i style={{ background: SOURCE_META[c.source]?.color }} />{c.title.slice(0, 44)}</span>)}</div></details>}
              {s?.audit && <p className="step-audit">解析出的过滤条件：{Object.entries(s.audit.filters).map(([k, v]) => `${k}=${String(v)}`).join("，")} · 命中 {s.audit.total} 条</p>}</div></li>; })}</ol>
        {r?.error && <p className="error" role="alert">{r.error}</p>}
        {r && !r.running && r.total !== undefined && <footer className={pass ? "pass" : "fail"}>{r.passed} / {r.total} 步通过</footer>}
      </article></Reveal>; })}</div>
  </main>;
}
