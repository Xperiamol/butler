"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import Brand from "./Brand";
import { logout } from "@/app/login/actions";
import { workspaceApi, type Identity, type WorkspaceStatus } from "@/lib/api";

export default function WorkspaceShell({ identity, children }: { identity: Identity; children: React.ReactNode }) {
  const path = usePathname();
  const [status, setStatus] = useState<WorkspaceStatus | null>(null);
  const [offline, setOffline] = useState(false);
  const [pending, setPending] = useState(0);
  useEffect(() => { let active = true; const load = () => workspaceApi.status().then((s) => { if (active) { setStatus(s); setOffline(false); } }).catch(() => { if (active) setOffline(true); }); void load(); window.addEventListener("workspace-updated", load); return () => { active = false; window.removeEventListener("workspace-updated", load); }; }, [path]);
  const admin = ["admin", "security"].includes(identity.role);
  useEffect(() => { if (!admin) return; let live = true; const load = () => workspaceApi.approvals().then((r) => { if (live) setPending(r.filter((a) => a.status === "pending").length); }).catch(() => {}); void load(); const timer = setInterval(load, 5000); window.addEventListener("workspace-updated", load); return () => { live = false; clearInterval(timer); window.removeEventListener("workspace-updated", load); }; }, [admin]);
  const audit = ["admin", "security", "auditor"].includes(identity.role);
  const groups = [{ title: "工作台", links: [{ href: "/workspace/overview", label: "概览", mark: "◫" }, { href: "/workspace", label: "知识问答", mark: "↗" }, ...(identity.username ? [{ href: "/workspace/account", label: "账号设置", mark: "♙" }] : [])] },
    ...(status?.mode === "demo" ? [{ title: "体验", links: [{ href: "/workspace/lab", label: "攻防演示台", mark: "✦" }] }] : []),
    ...(admin ? [{ title: "管理", links: [{ href: "/workspace/approvals", label: "预授权审批", mark: "✓", badge: pending }, { href: "/workspace/knowledge", label: "知识资料", mark: "▤" }, { href: "/workspace/members", label: "成员与权限", mark: "♧" }, { href: "/workspace/settings", label: "配置中心", mark: "⚙" }] }] : []),
    ...(audit ? [{ title: "安全", links: [{ href: "/workspace/audit", label: "审计记录", mark: "≡" }, ...(status?.mode === "demo" ? [{ href: "/workspace/eval", label: "安全评测", mark: "◷" }] : [])] }] : [])];
  const links = groups.flatMap((g) => g.links);
  return <div className="workspace-shell">
    <aside className="workspace-sidebar">
      <Brand href="/workspace/overview" inverse />
      <div className="workspace-org"><span className="org-symbol">{status?.organization.slice(0, 1) || "B"}</span><span>{status?.organization || "Butler"}<small>{status?.mode === "enterprise" ? "企业工作区" : status ? "演示工作区" : "正在连接"}</small></span></div>
      <nav aria-label="工作台导航">{groups.map((g) => <div className="sidebar-group" key={g.title}><span className="sidebar-label">{g.title}</span>{g.links.map((l) => <Link key={l.href} href={l.href} className={path === l.href ? "active" : ""} aria-current={path === l.href ? "page" : undefined}><span aria-hidden="true">{l.mark}</span>{l.label}{"badge" in l && l.badge ? <em className="nav-badge">{l.badge}</em> : null}</Link>)}</div>)}</nav>
      <div className="sidebar-bottom"><Link href="/">← 返回演示首页</Link><div className="sidebar-person"><span className="account-avatar">{identity.name.slice(0, 1)}</span><span><b>{identity.name.split("（")[0]}</b><small>{identity.name.match(/（(.+)）/)?.[1] ?? identity.role}</small></span><form action={logout}><button aria-label="退出登录" title="退出登录">↪</button></form></div></div>
    </aside>
    <div className="workspace-body"><header className="workspace-topbar"><span>{links.find((l) => l.href === path)?.label ?? "工作台"}</span><span><i className={`status-dot ${offline ? "offline" : ""}`} />{offline ? "连接中断" : status ? status.mode === "enterprise" ? "企业环境" : "演示环境" : "正在连接"}{status?.answering === "live" && <em className="model-chip">真实模型 · {status.generation_model}</em>}{status?.answering === "rules" && status.mode === "demo" && <em className="model-chip rules">离线规则</em>}</span></header><div className="page-enter" key={path}>{children}</div></div>
  </div>;
}
