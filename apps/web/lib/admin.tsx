import Link from "next/link";
import { requireSession } from "./session";

export async function AdminOnly({ children }: { children: React.ReactNode }) {
  const who = await requireSession();
  if (!["admin", "security"].includes(who.role)) return <main className="admin-page"><h1>需要管理员权限</h1><p>请联系工作区管理员。</p><Link className="btn" href="/workspace">返回问答</Link></main>;
  return children;
}
