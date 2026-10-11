import "server-only";
import { enterprise } from "./deployment";

export const publicDemoEnabled = !enterprise || Boolean(process.env.BUTLER_DEMO_API);

export async function publicDemo(path: "/compare" | "/eval", init?: RequestInit) {
  // Never attach a workspace cookie, member ID or internal service credential.
  const origin = enterprise ? process.env.BUTLER_DEMO_API : process.env.BUTLER_API || "http://127.0.0.1:8000";
  if (!origin) return Response.json({ error: "演示服务未配置。" }, { status: 503 });
  try {
    const response = await fetch(`${origin}${path}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(15000) });
    return new Response(await response.text(), { status: response.status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
  } catch { return Response.json({ error: "演示服务暂时不可用。" }, { status: 502 }); }
}
