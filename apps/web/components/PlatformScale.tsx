"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { SOURCE_META, workspaceApi, type SimStatus } from "@/lib/api";
import { CountUp, Reveal } from "./motion";

const ROWS = [
  { key: "confluence", label: "Confluence", unit: ["个空间", "页"], get: (s: NonNullable<SimStatus["stats"]>) => [s.confluence.spaces, s.confluence.pages], note: (s: NonNullable<SimStatus["stats"]>) => `${s.confluence.restricted_pages} 个页面带页面级限制` },
  { key: "jira", label: "Jira", unit: ["个项目", "个问题"], get: (s: NonNullable<SimStatus["stats"]>) => [s.jira.projects, s.jira.issues], note: (s: NonNullable<SimStatus["stats"]>) => `${s.jira.secured_issues} 个问题带安全级别` },
  { key: "slack", label: "Slack", unit: ["个频道", "个线程"], get: (s: NonNullable<SimStatus["stats"]>) => [s.slack.channels, s.slack.threads], note: (s: NonNullable<SimStatus["stats"]>) => `${s.slack.private_channels} 个私有频道 / 私信` },
  { key: "drive", label: "Google Drive", unit: ["个共享盘", "个文件"], get: (s: NonNullable<SimStatus["stats"]>) => [s.drive.shared_drives, s.drive.files], note: (s: NonNullable<SimStatus["stats"]>) => `${s.drive.limited_files} 个文件设为受限访问` },
];
const MM: Record<string, string> = { image: "图片", pdf: "扫描 PDF", audio: "录音", video: "视频" };

/** How much the assistant is connected to, and whether it is keeping up. */
export default function PlatformScale() {
  const [status, setStatus] = useState<SimStatus | null>(null);
  useEffect(() => { let live = true; const load = () => workspaceApi.simStatus().then((s) => { if (live) setStatus(s); }).catch(() => {}); void load(); const t = setInterval(() => { if (!document.hidden) void load(); }, 4000); return () => { live = false; clearInterval(t); }; }, []);
  if (!status?.enabled || !status.stats) return null;
  const s = status.stats, loading = Object.values(status.platforms ?? {}).some((p) => p.state === "loading");
  return <Reveal as="section" className="admin-section scale-panel">
    <div className="section-title"><h2>接入的来源平台</h2><span className="quiet-tag">模拟数据 · 体量按 Company A 缩放 · <Link href="/workspace/platforms">来源平台控制台 ↗</Link></span></div>
    <div className="scale-grid">{ROWS.map((r, i) => { const [a, b] = r.get(s); const st = status.platforms?.[r.key];
      return <div key={r.key} style={{ "--c": SOURCE_META[r.key].color, "--i": i } as React.CSSProperties}><header><i>{r.key[0].toUpperCase()}</i><b>{r.label}</b><span className={`sync-state is-${st?.state ?? "pending"}`}>{st?.state === "loading" ? `灌入 ${st.total ? Math.round(st.loaded / st.total * 100) : 0}%` : "已同步"}</span></header>
        <p><strong><CountUp value={b} /></strong><small>{r.unit[1]}</small></p><p className="scale-sub"><CountUp value={a} /> {r.unit[0]} · {r.note(s)}</p></div>; })}</div>
    <p className="scale-foot">共 <b>{status.documents?.toLocaleString()}</b> 份资料{Object.keys(s.multimodal).length > 0 && <> · 含 {Object.entries(s.multimodal).map(([m, n]) => `${MM[m] ?? m} ${n}`).join("、")}</>} · {loading ? "首次全量同步进行中…" : `每 ${status.interval_seconds} 秒增量同步一次，权限变更每次提问都会实时复核`}</p>
  </Reveal>;
}
