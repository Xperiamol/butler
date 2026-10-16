"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { workspaceApi, type Stats } from "@/lib/api";
import { CountUp, Reveal, Sparkline } from "./motion";

const LABEL: Record<string, string> = { answered: "直接放行", degraded: "去掉越权推断", needs_approval: "需要授权", refused: "拒答", citation_failed: "引用不成立", no_evidence: "没有资料" };
const TONE: Record<string, string> = { answered: "ok", degraded: "warn", needs_approval: "stop", refused: "stop", citation_failed: "stop", no_evidence: "muted" };

export default function StatsPanel({ admin }: { admin: boolean }) {
  const [stats, setStats] = useState<Stats | null>(null);
  useEffect(() => { let live = true; const load = () => workspaceApi.stats().then((s) => { if (live) setStats(s); }).catch(() => {}); void load(); const timer = setInterval(load, 6000); window.addEventListener("workspace-updated", load); return () => { live = false; clearInterval(timer); window.removeEventListener("workspace-updated", load); }; }, []);
  if (!stats) return null;
  const blocked = (stats.by_status.needs_approval ?? 0) + (stats.by_status.degraded ?? 0) + (stats.by_status.refused ?? 0);
  const rows = Object.entries(stats.by_status).sort((a, b) => b[1] - a[1]), max = Math.max(1, ...rows.map(([, n]) => n));
  return <Reveal as="section" className="admin-section stats-panel">
    <div className="section-title"><h2>回答守卫</h2><span className="quiet-tag"><i className="status-dot live" /> 实时 · 来自审计链</span></div>
    <div className="stats-grid">
      <div className="stat-tiles">
        <div><span>总问答</span><strong><CountUp value={stats.asks} /></strong></div>
        <div><span>被拦截或收窄</span><strong><CountUp value={blocked} /></strong></div>
        <div><span>待审批</span><strong><CountUp value={stats.approvals.pending} /></strong>{admin && <Link href="/workspace/approvals">去处理 ↗</Link>}</div>
        <div><span>已批准</span><strong><CountUp value={stats.approvals.approved} /></strong></div>
      </div>
      <div className="stat-chart"><span>近 14 天</span><Sparkline data={stats.series.map((b) => b.asks)} label="近 14 天问答量" /><Sparkline data={stats.series.map((b) => b.blocked)} label="近 14 天拦截量" height={44} /><small><i className="legend-a" />问答 <i className="legend-b" />拦截</small></div>
      <div className="stat-bars">{rows.length ? rows.map(([key, n]) => <div key={key} className={`stat-bar tone-${TONE[key] ?? "muted"}`}><span>{LABEL[key] ?? key}</span><div><i style={{ transform: `scaleX(${n / max})` }} /></div><b>{n}</b></div>) : <p>还没有问答记录。去知识问答里提一个问题。</p>}</div>
    </div>
  </Reveal>;
}
