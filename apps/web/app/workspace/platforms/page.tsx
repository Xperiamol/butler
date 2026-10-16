import Link from "next/link";
import PlatformsPanel from "@/components/PlatformsPanel";
import { enterprise } from "@/lib/deployment";
import { requireSession } from "@/lib/session";

export default async function PlatformsPage() {
  const who = await requireSession();
  if (enterprise || !["admin", "security"].includes(who.role)) return <main className="page"><h1 className="title">这个页面需要管理权限，且只在演示环境开放。</h1><p className="sub">换 Sara 登录试试。</p><Link className="btn" href="/workspace">返回知识问答</Link></main>;
  return <PlatformsPanel />;
}
