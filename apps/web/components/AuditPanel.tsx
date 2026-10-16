"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { workspaceApi, type AuditRow, type Verify } from "@/lib/api";
import AuditInquiry from "./AuditInquiry";

const short = (hash: string) => `${hash.slice(0, 12)}…${hash.slice(-6)}`;

export default function AuditPanel() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [verification, setVerification] = useState<Verify | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { const [a, v] = await Promise.all([workspaceApi.audit(), workspaceApi.verify()]); setRows(a.entries.slice().reverse()); setVerification(v); setError(""); }
    catch { setError("暂时无法读取审计记录。请稍后重试，或重新登录。"); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const firstBad = verification?.first_bad_index ?? Infinity;
  return <main className="page"><div className="page-head"><div><span className="overline">安全 / 审计</span><h1 className="title">每次回答，都有记录。</h1><p className="sub">查看提问身份、使用的资料与检查结果。你无权访问的资料会显示为“受限”。</p></div><button className="btn" onClick={load}>刷新记录 ↻</button></div>
    <div className="audit-summary"><div><span className={`audit-indicator ${verification?.ok === false ? "bad" : ""}`} /><b>{verification ? verification.ok ? "哈希链完整" : `第 ${firstBad} 条记录起校验失败` : "正在校验…"}</b></div><span>{verification?.length ?? "—"} 条记录</span></div>
    {error && <p className="error" role="alert">{error}</p>}
    {!rows.length && !error && verification && <div className="panel empty">还没有审计记录。<Link href="/workspace">先去问一个问题 ↗</Link></div>}
    <AuditInquiry /><div className="section-title audit-chain-title"><h2>哈希链原始记录</h2><span className="quiet-tag">最近 200 条 · 改一条就验不过</span></div><div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>序号 / 时间</th><th>提问账号</th><th>使用的资料</th><th>检查结果</th><th>链记录</th></tr></thead><tbody>{rows.map((r) => <tr key={r.index} className={r.index >= firstBad ? "tampered" : ""}><td><b className="mono">#{r.index}</b><small>{new Date(r.payload.ts * 1000).toLocaleString("zh-CN", { timeZone: "Asia/Singapore", hour12: false })}</small></td><td>{r.payload.user}<small>{r.payload.event ? "管理操作" : "知识问答"}</small></td><td><div className="audit-docs">{r.payload.docs.map((d, i) => <span className="chip" key={i}>{d}</span>)}</div></td><td><span className={`result-label ${r.payload.degraded ? "restricted" : ""}`}>{r.payload.event ? ({ "settings.updated": "更新配置", "member.updated": "更新成员", "member.created": "创建账号", "auth.login": "账号登录", "auth.password_changed": "修改密码", "auth.password_reset": "重置密码", "knowledge.imported": "导入资料" } as Record<string, string>)[r.payload.event] || r.payload.event : r.payload.degraded ? "去掉越权推断" : "正常放行"}</span></td><td><details><summary className="mono">{short(r.hash)}</summary><dl className="hash-detail"><dt>前一条</dt><dd>{r.prev_hash}</dd><dt>当前条</dt><dd>{r.hash}</dd><dt>问题哈希</dt><dd>{r.payload.question_hash}</dd></dl></details></td></tr>)}</tbody></table></div>
  </main>;
}
