import Link from "next/link";
import LabPanel from "@/components/LabPanel";
import { enterprise } from "@/lib/deployment";
import { requireSession } from "@/lib/session";

export default async function LabPage() {
  const who = await requireSession();
  if (enterprise) return <main className="page"><h1 className="title">演示台只在演示环境开放。</h1><Link className="btn" href="/workspace">返回知识问答</Link></main>;
  return <LabPanel who={who.name.split("（")[0]} role={who.name.match(/（(.+)）/)?.[1] ?? who.role} />;
}
