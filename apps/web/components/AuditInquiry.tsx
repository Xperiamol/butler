"use client";
import { useState } from "react";
import { SOURCE_META, workspaceApi, type AuditDoc, type AuditResult } from "@/lib/api";

const EXAMPLES = [
  "Show me everything user 'jdoe' accessed related to the 'payment-gateway' Confluence space in the last 30 days.",
  "Which access attempts were denied for user ken?",
  "What did mliu access on Slack last week?",
];
const when = (ts: number) => new Date(ts * 1000).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
const Chip = ({ d, denied }: { d: AuditDoc; denied?: boolean }) => <span className={`audit-chip ${denied ? "is-denied" : ""}`} title={d.id}><i style={{ background: SOURCE_META[d.platform]?.color ?? "#999" }} />{denied && <b>拒绝</b>}{d.title.length > 46 ? d.title.slice(0, 46) + "…" : d.title}</span>;

/** Audit inquiry: ask in one sentence or filter by hand. Every result shows who, when, which documents were retrieved, and the authorization decision for each. */
export default function AuditInquiry() {
  const [text, setText] = useState(EXAMPLES[0]);
  const [f, setF] = useState({ user: "", platform: "", container: "", days: 30, decision: "" });
  const [result, setResult] = useState<AuditResult | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const run = async (fn: () => Promise<AuditResult>) => { setBusy(true); setError(""); try { setResult(await fn()); } catch (e) { setError(e instanceof Error ? e.message : "查询未完成。"); } finally { setBusy(false); } };
  return <section className="audit-inquiry">
    <div className="section-title"><h2>审计查询</h2><span className="quiet-tag">问一句话，或者手动筛选</span></div>
    <form className="audit-ask" onSubmit={(e) => { e.preventDefault(); void run(() => workspaceApi.auditAsk(text)); }}>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={400} aria-label="用一句话描述要查的审计记录" />
      <button className="btn primary" disabled={busy || text.trim().length < 2}>{busy ? "查询中…" : "查询"}<span aria-hidden="true">→</span></button>
    </form>
    <div className="audit-examples">{EXAMPLES.map((x) => <button key={x} onClick={() => setText(x)}>{x.length > 70 ? x.slice(0, 70) + "…" : x}</button>)}</div>
    <details className="audit-filters"><summary>手动筛选</summary>
      <div><label>用户<input value={f.user} onChange={(e) => setF({ ...f, user: e.target.value })} placeholder="如 jdoe" /></label>
        <label>平台<select value={f.platform} onChange={(e) => setF({ ...f, platform: e.target.value })}><option value="">全部</option>{["confluence", "jira", "slack", "drive"].map((p) => <option key={p} value={p}>{SOURCE_META[p].label}</option>)}</select></label>
        <label>空间 / 项目 / 频道<input value={f.container} onChange={(e) => setF({ ...f, container: e.target.value })} placeholder="如 payment-gateway" /></label>
        <label>时间窗口<select value={f.days} onChange={(e) => setF({ ...f, days: Number(e.target.value) })}>{[7, 30, 90, 0].map((d) => <option key={d} value={d}>{d ? `最近 ${d} 天` : "不限"}</option>)}</select></label>
        <label>授权决定<select value={f.decision} onChange={(e) => setF({ ...f, decision: e.target.value })}><option value="">全部</option><option value="allowed">放行</option><option value="denied">拒绝</option></select></label>
        <button className="btn sm" disabled={busy} onClick={(e) => { e.preventDefault(); void run(() => workspaceApi.auditQuery(f)); }}>按条件查询</button></div></details>
    {error && <p className="error" role="alert">{error}</p>}
    {result && <div className="audit-result" aria-live="polite">
      <p className="audit-summary-line"><b>{result.total}</b> 条记录{result.filters && Object.keys(result.filters).length > 0 && <> · 解析为 {Object.entries(result.filters).map(([k, v]) => <code key={k}>{k}={String(v)}</code>)}{result.via && <em>（{result.via === "llm" ? "模型解析" : "规则解析"}）</em>}</>}</p>
      <div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>时间</th><th>用户</th><th>检索到并放行的文档</th><th>被拒绝的候选</th><th>结果</th></tr></thead><tbody>
        {result.rows.map((r, i) => <tr key={`${r.hash}${i}`}><td className="mono">{when(r.ts)}{r.synthetic && <small title="合成的历史记录，用来演示查询">合成</small>}</td><td><b>{r.user}</b></td>
          <td><div className="audit-chips">{r.allowed.length ? r.allowed.map((d) => <Chip key={d.id} d={d} />) : <span className="muted">—</span>}</div></td>
          <td><div className="audit-chips">{r.denied.length ? r.denied.map((d) => <Chip key={d.id} d={d} denied />) : <span className="muted">—</span>}</div></td>
          <td className="mono">{r.status}</td></tr>)}</tbody></table></div>
      {result.total > result.rows.length && <p className="lab-blurb">只显示最近 {result.rows.length} 条。</p>}
    </div>}
  </section>;
}
