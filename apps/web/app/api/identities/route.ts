import { backend } from "@/lib/backend";
import { enterprise } from "@/lib/deployment";

/** The demo accounts that can be switched to. Only exists in the demo environment. */
export async function GET() {
  if (enterprise) return Response.json({ error: "接口不存在。" }, { status: 404 });
  try {
    const r = await backend("/identities");
    return new Response(await r.text(), { status: r.status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
  } catch { return Response.json({ error: "暂时无法连接工作区。" }, { status: 502 }); }
}
