import AccountPanel from "@/components/AccountPanel";
import { requireSession } from "@/lib/session";
export default async function Page() {
  const who = await requireSession();
  return who.username ? <AccountPanel username={who.username} /> : <main className="admin-page"><h1>账号设置</h1><p>密码由身份平台管理。</p></main>;
}
