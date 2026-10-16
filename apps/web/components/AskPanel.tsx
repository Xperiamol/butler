"use client";
import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { MODALITY_LABEL, SOURCE_META, workspaceApi, type ChatTurn, type ConversationSummary, type Identity, type SourcesSummary } from "@/lib/api";
import AnswerText from "./AnswerText";
import ApprovalCard from "./ApprovalCard";
import AskProgress, { advance, startProgress, type Progress } from "./AskProgress";
import GuardTrace, { fmtMs } from "./GuardTrace";

const QUESTIONS = ["昨天支付故障的根本原因是什么？", "支付 API 限流是多少？", "供应商 X 合同、Payments 团队 Q4 预算有什么关联？"];
const COMPANY_DEFAULT = ["What was the root cause of the payment outage last quarter, and what follow-up tickets were created?", "What does the payment gateway architecture diagram show?", "What's the latest runbook for the payment-service incident?"];
const SUGGEST: Record<string, string[]> = {
  mliu: ["What's the status of the database migration project and were there any blockers raised in Slack last week?", "Summarize the design discussion around the new auth service from last sprint's Slack threads and link the Confluence decision doc.", "What does the payment gateway architecture diagram show?"],
  pete: ["What's the status of the database migration project and were there any blockers raised in Slack last week?", "Why was the settlement batch delayed on Oct 12 and what's the workaround?", "What did the leadership say about the migration budget?"],
  raj: ["What's the latest runbook for the payment-service incident?", "What was said on the incident bridge call about the root cause?", "What was the root cause of the payment outage last quarter, and what follow-up tickets were created?"],
  ken: ["Show me the security incident report from the Q3 breach", "What does the contractor onboarding checklist say?", "What are the rules for acceptable use of company devices?"],
  jdoe: ["show me all security vulnerabilities", "What's the latest runbook for the payment-service incident?", "What does the payment gateway architecture diagram show?"],
  alice: ["Why was the settlement batch delayed on Oct 12 and what's the workaround?", "What was the root cause of the payment outage last quarter, and what follow-up tickets were created?", "What does the payment gateway architecture diagram show?"],
  sara: ["Show me the security incident report from the Q3 breach", "What follow-up tickets were created after the Q3 breach?", "Summarize the design discussion around the new auth service from last sprint's Slack threads and link the Confluence decision doc."],
  amy: ["What does our policy say about vendor risk assessment?", "What is the PCI DSS scoping status?", "Which MAS notices are tracked in the compliance space?"],
};

export default function AskPanel({ identity }: { identity: Identity }) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"history" | "sources">("history");
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fresh, setFresh] = useState(-1);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState("");
  const [summary, setSummary] = useState<SourcesSummary | null>(null);
  const router = useRouter(), params = useSearchParams(), autoAsked = useRef(false);
  const [sourcesError, setSourcesError] = useState(false);
  const session = useRef("");
  const end = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const contextDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    session.current = crypto.randomUUID(); let active = true;
    workspaceApi.sourcesSummary().then((r) => { if (active) setSummary(r); }).catch(() => { if (active) setSourcesError(true); });
    workspaceApi.conversations().then(async (list) => {
      if (!active) return; setHistory(list);
      if (list[0] && !list[0].stale) {
        const saved = await workspaceApi.conversation(list[0].id);
        if (active && !saved.stale) { session.current = saved.id; setSelected(saved.id); setTurns(saved.turns); }
      }
    }).catch((e) => { if (active) setError(e instanceof Error ? e.message : "会话记录读取失败。"); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {   // 从“来源平台控制台 / 验收页”跳转过来时带着问题：加载完后自动提问一次
    const q = params.get("q");
    if (!q || autoAsked.current || loading || busy) return;
    autoAsked.current = true; router.replace("/workspace"); reset(); void ask(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, loading]);
  // Follow the answer as it types in, unless the reader has scrolled up to read earlier turns.
  useEffect(() => {
    const el = scroller.current; if (!el) return;
    let stick = true; const onScroll = () => { stick = el.scrollHeight - el.scrollTop - el.clientHeight < 160; };
    const observer = new MutationObserver(() => { if (stick) el.scrollTop = el.scrollHeight; });
    observer.observe(el, { childList: true, subtree: true, characterData: true }); el.addEventListener("scroll", onScroll);
    return () => { observer.disconnect(); el.removeEventListener("scroll", onScroll); };
  }, []);
  useEffect(() => { if (turns.length || busy) end.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [turns, busy, progress?.stage, progress?.docs.length]);
  const ask = async (q: string) => {
    if (!q.trim() || busy || loading) return;
    setBusy(true); setError(""); setPendingQuestion(q.trim()); setQuestion(""); setProgress(startProgress());
    try { const answer = await workspaceApi.askStream(q.trim(), session.current, (stage) => setProgress((p) => (p ? advance(p, stage) : p))); setFresh(turns.length); setTurns((t) => [...t, { question: q.trim(), answer }]); setQuestion(""); setSelected(session.current); workspaceApi.conversations().then(setHistory).catch(() => {}); window.dispatchEvent(new Event("workspace-updated")); }
    catch (e) { setError(e instanceof Error ? e.message : "这次没有拿到回答，请稍后再试。"); }
    finally { setBusy(false); setProgress(null); setPendingQuestion(""); }
  };
  const reset = () => {
    session.current = crypto.randomUUID(); setSelected(""); setTurns([]); setFresh(-1); setQuestion(""); setError("");
  };
  const open = async (id: string) => {
    setBusy(true); setError("");
    try { const saved = await workspaceApi.conversation(id); if (saved.stale) { reset(); setError("资料或权限已更新，旧会话已封存。请重新提问。"); } else { session.current = id; setSelected(id); setTurns(saved.turns); setQuestion(""); } contextDialog.current?.close(); }
    catch (e) { setError(e instanceof Error ? e.message : "会话读取失败。"); }
    finally { setBusy(false); }
  };
  const context = <><div className="knowledge-tabs"><button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>会话</button><button className={tab === "sources" ? "active" : ""} onClick={() => setTab("sources")}>资料</button></div>{tab === "history" ? <div className="conversation-list">{history.length ? history.map((c) => <button key={c.id} className={selected === c.id ? "active" : ""} disabled={busy || loading} onClick={() => open(c.id)}><b>{c.title}</b><small>{c.stale ? "资料或权限已更新" : new Date(c.updated * 1000).toLocaleDateString("zh-CN")}</small></button>) : <p>发送第一个问题后，会话会保存在这里。</p>}</div> : <><span className="overline">当前知识范围</span><h2>{sourcesError || !summary ? "暂不可用" : `${summary.visible.toLocaleString()} 份资料`}</h2><p>当前账号可以访问的来源。别人的权限不会影响你，你的也不会影响别人。</p>
    {summary && <><div className="knowledge-sources">{["confluence", "jira", "slack", "drive", "upload"].filter((k) => summary.by_source[k]).map((source) => <div key={source}><span className="platform-mark" style={{ color: SOURCE_META[source]?.color }}>{source[0].toUpperCase()}</span><b>{SOURCE_META[source]?.label ?? source}</b><span>{summary.by_source[source].toLocaleString()}</span></div>)}</div>
      {Object.keys(summary.by_modality).filter((m) => m !== "text").length > 0 && <div className="modality-row">{Object.entries(summary.by_modality).filter(([m]) => m !== "text").map(([m, n]) => <span key={m}>{MODALITY_LABEL[m] ?? m} <b>{n}</b></span>)}</div>}
      {summary.containers.length > 0 && <details><summary>按空间 / 项目 / 频道 / 共享盘看（{summary.containers.length} 个最大的）</summary><ul className="container-list">{summary.containers.map((c) => <li key={`${c.source}${c.name}`}><i style={{ background: SOURCE_META[c.source]?.color }} />{c.name}<b>{c.count}</b></li>)}</ul></details>}
      {summary.docs.length > 0 && <details><summary>查看资料目录</summary><ul>{summary.docs.map((d) => <li key={d.id}>{d.title}</li>)}</ul></details>}</>}
    <div className="knowledge-note"><span>关于当前账号</span><p>{identity.name}<br />回答不会使用其他账号的资料。</p></div></>}</>;
  return <main className="ask-workspace">
    <section className="chat-column"><div className="chat-toolbar"><span><i className="status-dot" />按 {identity.name.split("（")[0]} 的权限回答</span><div className="chat-toolbar-actions"><button className="btn sm mobile-context-button" aria-label="打开会话与资料" onClick={() => contextDialog.current?.showModal()}>会话 / 资料</button><button className="btn sm" disabled={busy || loading} onClick={reset}>＋ 新会话</button></div></div>
      <div ref={scroller} className={`chat-content ${turns.length ? "has-turns" : ""}`}>
        {!turns.length && <div className="chat-welcome"><Image className="welcome-mark" src="/butler-avatar.png" width={88} height={88} alt="Butler 管家" /><span className="overline">知识问答</span><h1>今天想查什么？</h1><p>回答会附上你有权查看的来源。</p>{summary && summary.visible > 0 && <div className="prompt-list">{(summary.docs.some((d) => d.id === "slack-incident-1") ? QUESTIONS : SUGGEST[identity.id] ?? COMPANY_DEFAULT).map((q, i) => <button key={q} onClick={() => ask(q)} disabled={busy || loading}><span>0{i + 1}</span>{q}<span aria-hidden="true">↗</span></button>)}</div>}</div>}
        {turns.map((t, i) => <article className="chat-turn" key={i}><div className="user-question"><span className="message-label">你</span><p>{t.question}</p></div><div className="assistant-answer"><span className="message-label">Butler</span>{t.answer.status === "needs_approval" ? <ApprovalCard answer={t.answer} busy={busy} onRetry={() => ask(t.question)} /> : <AnswerText text={t.answer.text} citations={t.answer.citations} typing={i === fresh} />}{!!t.answer.followups?.length && i === turns.length - 1 && <div className="followups"><span>你还可以问</span>{t.answer.followups.map((f) => <button key={f} disabled={busy || loading} onClick={() => ask(f)}>{f}<i aria-hidden="true">↗</i></button>)}</div>}{t.answer.status && <GuardTrace answer={t.answer} />}<span className="meta">{fmtMs(t.answer.latency_ms)}</span></div></article>)}
        {busy && pendingQuestion && progress && <article className="chat-turn"><div className="user-question"><span className="message-label">你</span><p>{pendingQuestion}</p></div><div className="assistant-answer"><span className="message-label">Butler</span><AskProgress p={progress} /></div></article>}{loading && <p className="chat-pending" role="status"><span className="spinner" />正在恢复会话…</p>}<div ref={end} />
      </div>
      <div className="composer-area">{error && <p className="error" role="alert">{error}</p>}<form className="composer" onSubmit={(e) => { e.preventDefault(); ask(question); }}><label className="sr-only" htmlFor="question">输入问题</label><textarea id="question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="问一个工作上的问题…" rows={2} disabled={busy || loading} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(question); } }} /><div><span>Enter 发送 · Shift + Enter 换行</span><button className="send-button" disabled={busy || loading || !question.trim()} aria-label="发送问题">↑</button></div></form><p className="composer-note">会话自动保存 · 来源按当前权限访问</p></div>
    </section>
    <aside className="knowledge-sidebar">{context}</aside>
    <dialog ref={contextDialog} className="knowledge-dialog" aria-label="会话与资料"><header><b>会话与资料</b><button className="btn sm" onClick={() => contextDialog.current?.close()}>关闭 ×</button></header><div className="knowledge-sidebar">{context}</div></dialog>
  </main>;
}
