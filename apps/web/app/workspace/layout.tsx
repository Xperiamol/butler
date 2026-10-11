import WorkspaceShell from "@/components/WorkspaceShell";
import { requireSession } from "@/lib/session";

export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const identity = await requireSession();
  return <WorkspaceShell identity={identity}>{children}</WorkspaceShell>;
}
