"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FACT_LABEL, workspaceApi, type Approval } from "@/lib/api";
import { CountUp } from "./motion";

const ago = (ts: number) => { const s = Math.max(0, Math.floor(Date.now() / 1000 - ts)); return s < 60 ? "刚刚" : s < 3600 ? `${Math.floor(s / 60)} 分钟前` : s < 86400 ? `${Math.floor(s / 3600)} 小时前` : `${Math.floor(s / 86400)} 天前`; };
const MINUTES = [15, 30, 60, 240];

export default function ApprovalsPanel() {
  const [rows, setRows] = useState<Approval[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [minutes, setMinutes] = useState<Record<string, number>>({});
  const load = useCallback(async () => {
    try { setRows(await workspaceApi.approvals()); setError(""); } catch (e) { setError(e instanceof Error ? e.message : "暂时无法读取审批队列。"); }
  }, []);
  useEffect(() => { void load(); const timer = setInterval(() => { if (!document.hidden) void load(); }, 4000); return () => clearInterval(timer); }, [load]);
  const decide = async (row: Approval, approve: boolean) => {
    setBusy(row.id);
    try { await workspaceApi.decide(row.id, { approve, minutes: minutes[row.id] ?? 30 }); await load(); window.dispatchEvent(new Event("workspace-updated")); }
    catch (e) { setError(e instanceof Error ? e.message : "操作未完成，请重试。"); }
    finally { setBusy(""); }
  };
  const pending = rows?.filter((r) => r.status === "pending") ?? [], done = rows?.filter((r) => r.status !== "pending") ?? [];
  return <main className="admin-page">
    <div className="admin-heading"><div><span className="overline">安全 / 审批</span><h1>预授权审批</h1><p>用户累计拿到的资料凑齐某条受限结论时，回答会停在这里等你。批准只针对那一条结论，限时，到期自动失效；你不能批准自己的申请。</p></div>
      <div className="approval-counts"><div><strong><CountUp value={pending.length} /></strong><span>待处理</span></div><div><strong><CountUp value={done.filter((r) => r.status === "approved").length} /></strong><span>已批准</span></div></div></div>
    {error && <p className="error" role="alert">{error}</p>}
    {!rows && !error && <p className="admin-loading" role="status"><span className="spinner" />正在读取…</p>}
    {rows && !pending.length && <div className="approval-empty"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="26" /><path d="M20 33l8 8 16-18" /></svg><h2>没有待处理的申请</h2><p>试一下：用 Ken 登录，在知识问答里问“供应商 X 合同、Payments 团队 Q4 预算有什么关联？”，回答会停在这里。</p><Link className="btn sm" href="/workspace/lab">去攻防演示台 ↗</Link></div>}
    <div className="approval-list">{pending.map((row, i) => <article className="approval-item" key={row.id} style={{ "--i": i } as React.CSSProperties}>
      <header><span className="approval-who"><span className="account-avatar">{row.user.slice(0, 1).toUpperCase()}</span><b>{row.user}</b></span><span className="approval-time">{ago(row.created)} · 申请 {row.id}</span></header>
      <p className="approval-label">这条回答会让他得知：</p>
      <div className="approval-concl">{row.fact_ids.map((id, k) => { const hidden = row.conclusions[k]?.startsWith("（你无权"); return <span key={id}>{hidden ? FACT_LABEL[id] ?? "受限结论" : row.conclusions[k]}{hidden && <small>结论原文仅有权限的人可见</small>}</span>; })}</div>
      <footer><label>有效期<select value={minutes[row.id] ?? 30} onChange={(e) => setMinutes({ ...minutes, [row.id]: Number(e.target.value) })}>{MINUTES.map((m) => <option key={m} value={m}>{m >= 60 ? `${m / 60} 小时` : `${m} 分钟`}</option>)}</select></label>
        <span><button className="btn sm danger" disabled={busy === row.id} onClick={() => decide(row, false)}>拒绝</button><button className="btn sm primary" disabled={busy === row.id} onClick={() => decide(row, true)}>{busy === row.id ? "处理中…" : "批准"}<span aria-hidden="true">✓</span></button></span></footer>
    </article>)}</div>
    {done.length > 0 && <section className="admin-section"><div className="section-title"><h2>已处理</h2><span className="quiet-tag">{done.length} 条 · 记录进审计链</span></div>
      <div className="approval-history">{done.map((row) => <div key={row.id} className={`history-row is-${row.status}`}><span className="history-dot" /><b>{row.user}</b><span>{row.fact_ids.map((id) => FACT_LABEL[id] ?? "受限结论").join("、")}</span><span className="history-status">{row.status === "approved" ? row.expires * 1000 > Date.now() ? "已批准 · 生效中" : "已批准 · 已到期" : "已拒绝"}</span><span className="history-time">{row.decided_by ? `由 ${row.decided_by}` : ""} · {ago(row.created)}</span></div>)}</div></section>}
  </main>;
}
