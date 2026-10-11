import AskPanel from "@/components/AskPanel";
import { requireSession } from "@/lib/session";

export default async function WorkspacePage() {
  return <AskPanel identity={await requireSession()} />;
}
