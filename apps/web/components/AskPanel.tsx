"use client";
import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { workspaceApi, type ChatTurn, type ConversationSummary, type Citation, type Identity } from "@/lib/api";
import AnswerText from "./AnswerText";

const QUESTIONS = ["昨天支付故障的根本原因是什么？", "支付 API 限流是多少？", "供应商 X 合同现在是什么状态？"];

export default function AskPanel({ identity }: { identity: Identity }) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"history" | "sources">("history");
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sources, setSources] = useState<Citation[]>([]);
  const [sourcesError, setSourcesError] = useState(false);
  const session = useRef("");
  const end = useRef<HTMLDivElement>(null);
  const contextDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    session.current = crypto.randomUUID(); let active = true;
    workspaceApi.sources().then((r) => { if (active) setSources(r.docs); }).catch(() => { if (active) setSourcesError(true); });
    workspaceApi.conversations().then(async (list) => {
      if (!active) return; setHistory(list);
      if (list[0] && !list[0].stale) {
        const saved = await workspaceApi.conversation(list[0].id);
        if (active && !saved.stale) { session.current = saved.id; setSelected(saved.id); setTurns(saved.turns); }
      }
    }).catch((e) => { if (active) setError(e instanceof Error ? e.message : "会话记录读取失败。"); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => { if (turns.length || busy) end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [turns, busy]);
  const ask = async (q: string) => {
    if (!q.trim() || busy || loading) return;
    setBusy(true); setError("");
    try { const answer = await workspaceApi.ask(q.trim(), session.current); setTurns((t) => [...t, { question: q.trim(), answer }]); setQuestion(""); setSelected(session.current); workspaceApi.conversations().then(setHistory).catch(() => {}); window.dispatchEvent(new Event("workspace-updated")); }
    catch (e) { setError(e instanceof Error ? e.message : "这次没有拿到回答，请稍后再试。"); }
    finally { setBusy(false); }
  };
  const reset = () => {
    session.current = crypto.randomUUID(); setSelected(""); setTurns([]); setQuestion(""); setError("");
  };
  const open = async (id: string) => {
    setBusy(true); setError("");
    try { const saved = await workspaceApi.conversation(id); if (saved.stale) { reset(); setError("资料或权限已更新，旧会话已封存。请重新提问。"); } else { session.current = id; setSelected(id); setTurns(saved.turns); setQuestion(""); } contextDialog.current?.close(); }
    catch (e) { setError(e instanceof Error ? e.message : "会话读取失败。"); }
    finally { setBusy(false); }
  };
  const context = <><div className="knowledge-tabs"><button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>会话</button><button className={tab === "sources" ? "active" : ""} onClick={() => setTab("sources")}>资料</button></div>{tab === "history" ? <div className="conversation-list">{history.length ? history.map((c) => <button key={c.id} className={selected === c.id ? "active" : ""} disabled={busy || loading} onClick={() => open(c.id)}><b>{c.title}</b><small>{c.stale ? "资料或权限已更新" : new Date(c.updated * 1000).toLocaleDateString("zh-CN")}</small></button>) : <p>发送第一个问题后，会话会保存在这里。</p>}</div> : <><span className="overline">当前知识范围</span><h2>{sourcesError ? "暂不可用" : `${sources.length} 份资料`}</h2><p>当前账号可以访问的来源。</p><div className="knowledge-sources">{["confluence", "jira", "slack", "drive", "upload"].map((source) => <div key={source}><span className={`platform-mark ${source}`}>{source[0].toUpperCase()}</span><b>{{ confluence: "Confluence", jira: "Jira", slack: "Slack", drive: "Google Drive", upload: "手动导入" }[source]}</b><span>{sources.filter((d) => d.source === source).length}</span></div>)}</div><details><summary>查看资料目录</summary><ul>{sources.map((s) => <li key={s.id}>{s.title}</li>)}</ul></details><div className="knowledge-note"><span>关于当前账号</span><p>{identity.name}<br />回答不会使用其他账号的资料。</p></div></>}</>;
  return <main className="ask-workspace">
    <section className="chat-column"><div className="chat-toolbar"><span><i className="status-dot" />按 {identity.name.split("（")[0]} 的权限回答</span><div className="chat-toolbar-actions"><button className="btn sm mobile-context-button" aria-label="打开会话与资料" onClick={() => contextDialog.current?.showModal()}>会话 / 资料</button><button className="btn sm" disabled={busy || loading} onClick={reset}>＋ 新会话</button></div></div>
      <div className={`chat-content ${turns.length ? "has-turns" : ""}`}>
        {!turns.length && <div className="chat-welcome"><Image className="welcome-mark" src="/butler-avatar.png" width={88} height={88} alt="Butler 管家" /><span className="overline">知识问答</span><h1>今天想查什么？</h1><p>回答会附上你有权查看的来源。</p>{sources.some((s) => s.id === "slack-incident-1") && <div className="prompt-list">{QUESTIONS.map((q, i) => <button key={q} onClick={() => ask(q)} disabled={busy || loading}><span>0{i + 1}</span>{q}<span aria-hidden="true">↗</span></button>)}</div>}</div>}
        {turns.map((t, i) => <article className="chat-turn" key={i}><div className="user-question"><span className="message-label">你</span><p>{t.question}</p></div><div className="assistant-answer"><span className="message-label">Butler</span><AnswerText text={t.answer.text} citations={t.answer.citations} /><span className="meta">{t.answer.latency_ms.toFixed(1)} ms</span></div></article>)}
        {(busy || loading) && <p className="chat-pending" role="status"><span className="spinner" />{loading ? "正在恢复会话…" : "正在处理…"}</p>}<div ref={end} />
      </div>
      <div className="composer-area">{error && <p className="error" role="alert">{error}</p>}<form className="composer" onSubmit={(e) => { e.preventDefault(); ask(question); }}><label className="sr-only" htmlFor="question">输入问题</label><textarea id="question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="问一个工作上的问题…" rows={2} disabled={busy || loading} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(question); } }} /><div><span>Enter 发送 · Shift + Enter 换行</span><button className="send-button" disabled={busy || loading || !question.trim()} aria-label="发送问题">↑</button></div></form><p className="composer-note">会话自动保存 · 来源按当前权限访问</p></div>
    </section>
    <aside className="knowledge-sidebar">{context}</aside>
    <dialog ref={contextDialog} className="knowledge-dialog" aria-label="会话与资料"><header><b>会话与资料</b><button className="btn sm" onClick={() => contextDialog.current?.close()}>关闭 ×</button></header><div className="knowledge-sidebar">{context}</div></dialog>
  </main>;
}
