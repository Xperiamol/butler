import Link from "next/link";
import EvalPanel from "@/components/EvalPanel";
import { requireSession } from "@/lib/session";
import { enterprise } from "@/lib/deployment";

export default async function Page() {
  const who = await requireSession();
  if (!["admin", "security", "auditor"].includes(who.role)) return <main className="admin-page"><h1>需要审计权限</h1><Link className="btn" href="/workspace">返回问答</Link></main>;
  if (enterprise) return <main className="admin-page"><h1>安全评测</h1><p>请在独立演示环境运行离线评测。</p></main>;
  return <EvalPanel />;
}
