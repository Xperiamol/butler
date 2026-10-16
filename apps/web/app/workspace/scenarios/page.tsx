import Link from "next/link";
import ScenariosPanel from "@/components/ScenariosPanel";
import { enterprise } from "@/lib/deployment";
import { requireSession } from "@/lib/session";

export default async function ScenariosPage() {
  const who = await requireSession();
  if (enterprise || !["admin", "security"].includes(who.role)) return <main className="page"><h1 className="title">验收用例需要管理权限，且只在演示环境开放。</h1><p className="sub">用例会修改来源平台并以不同身份提问。换 Sara 登录试试。</p><Link className="btn" href="/workspace">返回知识问答</Link></main>;
  return <ScenariosPanel />;
}
