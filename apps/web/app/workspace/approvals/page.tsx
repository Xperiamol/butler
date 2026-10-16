import Link from "next/link";
import ApprovalsPanel from "@/components/ApprovalsPanel";
import { requireSession } from "@/lib/session";

export default async function ApprovalsPage() {
  const who = await requireSession();
  if (!["admin", "security"].includes(who.role)) return <main className="page"><h1 className="title">这个账号没有审批权限。</h1><p className="sub">预授权审批仅向管理员和安全团队开放。</p><Link className="btn" href="/workspace">返回知识问答</Link></main>;
  return <ApprovalsPanel />;
}
