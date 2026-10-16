"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, FACT_LABEL, type Compare, type EvalReport } from "@/lib/api";
import { answerParts, deskFacts, type DeskView, type StoryPhase } from "@/lib/demo-story";
import AnswerText from "./AnswerText";
import EvidenceDesk from "./EvidenceDesk";
import { PEOPLE, SCENARIOS } from "@/lib/scenarios";
import DemoResults from "./DemoResults";

const STEPS = ["查资料", "生成回答", "检查权限", "发出答案"];
const ACTIONS = ["生成回答", "检查权限", "发出答案"];
const WORKING = ["整理授权资料", "正在写入草稿", "正在核对权限", "正在发出答案"];
type Turn = { question: string; response: Compare };

export default function Demo() {
  const [selected, setSelected] = useState(0);
  const [person, setPerson] = useState(0);
  const [phase, setPhase] = useState<StoryPhase>(0);
  const [unlocked, setUnlocked] = useState(0);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [roundIndex, setRoundIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [animating, setAnimating] = useState(true);
  const [replay, setReplay] = useState(0);
  const [error, setError] = useState("");
  const [report, setReport] = useState<EvalReport | null>(null);
  const phaseRef = useRef<StoryPhase>(0);
  const mounted = useRef(true);
  const session = useRef("");
  const runLock = useRef(false);
  const scenario = SCENARIOS[selected], who = PEOPLE[person];
  const latest = turns[roundIndex], result = latest?.response;
  const round = roundIndex + 1;
  const question = scenario.turns[roundIndex];
  const hasNext = round < scenario.turns.length;
  const locked = busy || animating;
  const onMotion = useCallback((current: StoryPhase, active: boolean) => {
    if (phaseRef.current === current) setAnimating(active);
  }, []);
  const view = useMemo<DeskView>(() => {
    const draft = answerParts(result?.baseline.text), sent = answerParts(result?.butler.text);
    const excerpt = (facts: string[]) => selected === 2 ? facts.filter((fact) => /每秒|限流|429/.test(fact)).slice(0, 1) : deskFacts(facts);
    return { phase, reader: who.name, role: who.role, multi: selected === 1, round,
      facts: excerpt(draft.facts), claim: draft.claim, sentFacts: excerpt(sent.facts), sentClaim: sent.claim,
      citations: (phase === 3 ? result?.butler : result?.baseline)?.citations.length ?? 0,
      blocked: !!result?.butler.degraded, restricted: result?.butler.blocked_facts.map((id) => FACT_LABEL[id] ?? id).join("、") || "组织调整" };
  }, [phase, who, selected, round, result]);
  useEffect(() => {
    mounted.current = true; session.current = crypto.randomUUID();
    api.eval().then((value) => { if (mounted.current) setReport(value); }).catch(() => {});
    return () => { mounted.current = false; };
  }, []);
  function go(next: StoryPhase) {
    phaseRef.current = next; setPhase(next); setUnlocked((value) => Math.max(value, next)); setAnimating(true);
  }
  function reset() {
    phaseRef.current = 0; setPhase(0); setUnlocked(0); setTurns([]); setRoundIndex(0); setError(""); setAnimating(true); setReplay((value) => value + 1); session.current = crypto.randomUUID();
  }
  async function sendNext() {
    if (runLock.current || result) return;
    runLock.current = true; setBusy(true); setError("");
    const nextQuestion = scenario.turns[roundIndex];
    try {
      const response = await api.compare(who.id, nextQuestion, session.current);
      if (mounted.current) { setTurns((previous) => [...previous, { question: nextQuestion, response }]); go(1); }
    } catch { if (mounted.current) setError("暂时连不上服务，请重试。"); }
    finally { runLock.current = false; if (mounted.current) setBusy(false); }
  }
  function advance() {
    if (locked) return;
    if (phase === 0) {
      if (result) go(1); else void sendNext();
    } else if (phase < 3) go((phase + 1) as StoryPhase);
    else if (hasNext) { setRoundIndex((value) => value + 1); setUnlocked(0); go(0); }
    else reset();
  }
  const title = phase === 0 ? selected === 1 ? "问题分开问，线索会累积。" : selected === 2 ? "先找到限流规则。" : "三份资料，都有权读。"
    : phase === 1 ? view.claim ? "线索拼在一起，变成了推断。" : "资料里的事实，写进了答案。"
    : phase === 2 ? animating ? "这句话，他有权知道吗？" : view.blocked ? `这句推断，${who.name} 无权知道。` : "权限匹配，答案保留。"
    : view.blocked ? "事实照发，越权推断删去。" : "检查通过，照常发出。";
  const note = phase === 0 ? selected === 2 ? "Ken 和 Pete 都能查。" : "裁撤计划，仅向管理层开放。"
    : phase === 1 ? view.claim ? "引用合规，不代表结论合规。" : "接下来检查答案本身。"
    : phase === 2 ? `${who.name} · ${who.role} / ${view.claim || view.blocked ? "组织调整 · 仅管理层" : "业务规则 · 可访问"}`
    : "身份、来源与判定，记入审计。";
  return <>
    <section className="demo-stage" id="demo" aria-labelledby="demo-heading">
      <header className="demo-stage-head"><div><span className="demo-label">01 / 现场演示</span><h2 id="demo-heading">答案出门前。</h2></div><span className="demo-note">这里是规则版示意动画。接了真实大模型的版本在工作台 → 攻防演示台。</span></header>
      <div className="demo-toolbar">
        <div className="scenario-tabs" role="group" aria-label="选择演示场景">{SCENARIOS.map((item, i) => <button key={item.name} aria-pressed={selected === i} disabled={busy} className={selected === i ? "active" : ""} onClick={() => { setSelected(i); reset(); }}><span>{item.name}</span></button>)}</div>
        <label className="demo-reader">提问人<select value={person} disabled={busy} onChange={(event) => { setPerson(Number(event.target.value)); reset(); }}>{PEOPLE.map((item, i) => <option value={i} key={item.id}>{item.name} · {item.role}</option>)}</select></label>
      </div>
      <div className="story-question"><span>{who.name} 问{selected === 1 ? ` · 第 ${round} / 3 轮` : ""}</span><p>{question}</p></div>
      <ol className="story-rail" aria-label="演示进度">{STEPS.map((step, i) => <li key={step}><button aria-current={phase === i ? "step" : undefined} disabled={locked || i > unlocked} onClick={() => { if (phase !== i) go(i as StoryPhase); }}><span>0{i + 1}</span>{step}<i aria-hidden="true" /></button></li>)}</ol>
      <div className="story-heading" aria-live="polite"><h3>{title}</h3><p>{note}</p></div>
      <EvidenceDesk key={`${selected}-${person}`} sources={scenario.sources} view={view} replay={replay} onMotion={onMotion} />
      <div className="story-actions"><button className="story-replay" disabled={locked} onClick={() => { setAnimating(true); setReplay((value) => value + 1); }}><span aria-hidden="true">↻</span> 重播本步</button><span className="story-action-state" role="status">{busy ? "正在回答…" : animating ? `${WORKING[phase]}…` : phase === 3 ? "已完成" : `0${phase + 1} / 04`}</span><button className="btn primary demo-run" disabled={locked} onClick={advance}>{phase < 3 ? ACTIONS[phase] : hasNext ? "问下一轮" : "再演示一次"}<span aria-hidden="true">→</span></button></div>
      {error && <p role="alert" className="demo-error">{error}</p>}
      {result && phase > 0 && <details className="full-demo-answer" key={`${selected}-${person}-${turns.length}`}><summary>完整回答与来源</summary><div className={`demo-answers ${phase === 1 ? "one-answer" : ""}`}><article className="demo-answer baseline"><header><span className="answer-index">A</span><h3>普通助手</h3></header><AnswerText text={result.baseline.text} citations={result.baseline.citations} highlight={view.blocked} /></article>{phase >= 2 && <article className="demo-answer guarded"><header><span className="answer-index">B</span><h3>Butler</h3></header><AnswerText text={result.butler.text} citations={result.butler.citations} /></article>}</div></details>}
      {turns.length > 1 && <details className="demo-rounds"><summary>前 {turns.length - 1} 轮记录</summary>{turns.slice(0, -1).map((turn, i) => <article key={i}><span>第 {i + 1} 轮 · {turn.response.butler.degraded ? "去掉越权推断" : "检查通过"}</span><h4>{turn.question}</h4><AnswerText text={turn.response.butler.text} citations={turn.response.butler.citations} /></article>)}</details>}
    </section>
    <DemoResults report={report} />
  </>;
}
