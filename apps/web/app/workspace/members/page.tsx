import { MembersPanel } from "@/components/WorkspaceAdmin";
import { AdminOnly } from "@/lib/admin";
import { requireSession } from "@/lib/session";
export default async function Page() { const who = await requireSession(); return <AdminOnly><MembersPanel currentId={who.id} /></AdminOnly>; }
