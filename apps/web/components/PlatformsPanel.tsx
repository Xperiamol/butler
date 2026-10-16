"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { switchIdentity } from "@/app/login/actions";
import { SOURCE_META, workspaceApi, type SimPreset, type SimStatus } from "@/lib/api";
import { ago } from "./CitationCards";
import { CountUp, Reveal } from "./motion";

const PLATFORMS = ["confluence", "jira", "slack", "drive"] as const;
const NAME: Record<string, string> = { confluence: "Confluence", jira: "Jira", slack: "Slack", drive: "Google Drive" };
const FACTS = (s: NonNullable<SimStatus["stats"]>) => ({
  confluence: [["空间", s.confluence.spaces], ["页面", s.confluence.pages], ["页面级限制", s.confluence.restricted_pages]],
  jira: [["项目", s.jira.projects], ["问题", s.jira.issues], ["带安全级别", s.jira.secured_issues]],
  slack: [["频道", s.slack.channels], ["线程", s.slack.threads], ["私有 / 私信", s.slack.private_channels]],
  drive: [["共享盘", s.drive.shared_drives], ["文件", s.drive.files], ["受限访问", s.drive.limited_files]],
} as Record<string, [string, number][]>);

export default function PlatformsPanel() {
  const [status, setStatus] = useState<SimStatus | null>(null);
  const [presets, setPresets] = useState<SimPreset[]>([]);
  const [busy, setBusy] = useState(""), [done, setDone] = useState<Record<string, { seconds: number; at: number }>>({}), [error, setError] = useState("");
  const load = useCallback(() => { workspaceApi.simStatus().then(setStatus).catch(() => setError("读取来源平台状态失败。")); }, []);
  useEffect(() => { load(); workspaceApi.simPresets().then((r) => setPresets(r.presets)).catch(() => {}); const t = setInterval(() => { if (!document.hidden) load(); }, 3000); return () => clearInterval(t); }, [load]);
  const run = async (id: string, action: string, params: Record<string, unknown>) => {
    setBusy(id); setError("");
    const t0 = performance.now();
    try { await workspaceApi.simMutate(action, params); setDone((d) => ({ ...d, [id]: { seconds: (performance.now() - t0) / 1000, at: Date.now() } })); load(); window.dispatchEvent(new Event("workspace-updated")); }
    catch (e) { setError(e instanceof Error ? e.message : "操作未完成。"); } finally { setBusy(""); }
  };
  const sync = async () => { setBusy("sync"); try { await workspaceApi.simSync(); load(); } catch (e) { setError(e instanceof Error ? e.message : "同步未完成。"); } finally { setBusy(""); } };
  if (status && !status.enabled) return <main className="admin-page"><div className="admin-heading"><div><span className="overline">来源平台</span><h1>当前不是公司演示世界</h1><p>用默认设置启动即可（不要设 BUTLER_DEMO_WORLD=tiny）。</p></div></div></main>;
  const platforms = status?.platforms, stats = status?.stats;
  const scenarios = [...new Set(presets.map((p) => p.scenario))];
  return <main className="admin-page platforms-page">
    <div className="admin-heading"><div><span className="overline">体验 / 来源平台</span><h1>四个来源平台，各管各的权限。</h1><p>这里是模拟的 Confluence、Jira、Slack、Google Drive（合成数据，体量按 Company A 缩放）。在来源平台上做一次真实变更，几秒内就会同步进来，并反映在下一次回答里。</p></div>
      <button className="btn primary" disabled={!!busy} onClick={sync}>{busy === "sync" ? "同步中…" : "立即全量对账"}<span aria-hidden="true">↻</span></button></div>
    {error && <p className="error" role="alert">{error}</p>}
    <section className="platform-grid">{PLATFORMS.map((p, i) => { const st = platforms?.[p]; const facts = stats ? FACTS(stats)[p] : [];
      return <Reveal key={p} delay={i * 80} className="platform-card"><div style={{ "--c": SOURCE_META[p].color } as React.CSSProperties}>
        <header><span className="platform-badge">{p[0].toUpperCase()}</span><h3>{NAME[p]}</h3><span className={`sync-state is-${st?.state ?? "pending"}`}>{st?.state === "loading" ? `首次灌入 ${st.total ? Math.round(st.loaded / st.total * 100) : 0}%` : st?.state === "ready" ? "已同步" : st?.state === "error" ? "出错" : "等待"}</span></header>
        <dl>{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd><CountUp value={v} /></dd></div>)}</dl>
        {st?.state === "loading" && <div className="load-bar"><i style={{ transform: `scaleX(${st.total ? st.loaded / st.total : 0})` }} /></div>}
        <footer>{st?.last_sync ? `最近同步 ${ago(st.last_sync)} · 积压 ${st.lag_seconds.toFixed(0)} 秒` : "—"}{st && st.last_changes > 0 ? ` · 刚同步了 ${st.last_changes} 个变更` : ""}</footer></div></Reveal>; })}</section>
    {stats && <div className="platform-extra"><span>多模态资料</span>{Object.entries(stats.multimodal).map(([m, n]) => <b key={m}>{({ image: "图片", pdf: "扫描 PDF", audio: "录音", video: "视频" } as Record<string, string>)[m] ?? m} {n}</b>)}<span>人员</span><b>{stats.people}</b><span>文档总数</span><b>{status?.documents?.toLocaleString()}</b><span>增量同步间隔</span><b>{status?.interval_seconds} 秒</b></div>}
    <section className="admin-section"><div className="section-title"><h2>在来源平台上做一次真实变更</h2><span className="quiet-tag">变更 → 入库 → 下一次回答，全程可审计</span></div>
      {scenarios.map((sc) => <div key={sc} className="preset-group"><h4>{sc}</h4><div className="preset-list">{presets.filter((p) => p.scenario === sc).map((p) => <article key={p.id} className="preset" data-done={!!done[p.id]}>
        <div><span className="preset-platform" style={{ color: SOURCE_META[p.platform]?.color }}>{NAME[p.platform]}</span><h5>{p.title}</h5></div>
        <footer><button className="btn sm primary" disabled={!!busy} onClick={() => run(p.id, p.action, p.params)}>{busy === p.id ? "执行中…" : done[p.id] ? "再执行一次" : "执行"}</button>
          {p.undo && <button className="btn sm" disabled={!!busy} onClick={() => run(p.id + "-undo", p.undo!.action, p.undo!.params)}>还原</button>}
          {done[p.id] && <span className="preset-done">✓ 已生效（含同步 {done[p.id].seconds.toFixed(1)} 秒）</span>}
          {done[p.id] && p.then && <form action={switchIdentity}><input type="hidden" name="identity" value={p.then.user} /><input type="hidden" name="next" value={`/workspace?q=${encodeURIComponent(p.then.question)}`} /><button className="btn sm">以 {p.then.user} 的身份再问一次 →</button></form>}</footer></article>)}</div></div>)}
      <p className="lab-blurb">还有一个检验：先<b>执行</b>变更，不等同步，立刻再问——回答也不会带出已被撤权的内容，因为每次提问都会按平台原生语义对最终进入上下文的每份资料<b>实时复核</b>一次，同步只是把快照追平。</p>
      <p className="lab-blurb"><Link href="/workspace/scenarios">想一键跑完赛题的五个用例？去「赛题用例验收」→</Link></p></section>
  </main>;
}
