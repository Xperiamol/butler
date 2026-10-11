import { KnowledgePanel } from "@/components/WorkspaceAdmin";
import { AdminOnly } from "@/lib/admin";
export default function Page() { return <AdminOnly><KnowledgePanel /></AdminOnly>; }
