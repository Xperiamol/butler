import Link from "next/link";
import AuditPanel from "@/components/AuditPanel";
import { requireSession } from "@/lib/session";

export default async function AuditPage() {
  const who = await requireSession();
  if (!["auditor", "security", "admin", "compliance"].includes(who.role)) return <main className="page"><h1 className="title">这个账号没有审计权限。</h1><p className="sub">审计记录仅向审计员和安全团队开放。</p><Link className="btn" href="/workspace">返回知识问答</Link></main>;
  return <AuditPanel />;
}
