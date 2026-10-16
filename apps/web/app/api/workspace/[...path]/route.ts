import { backend } from "@/lib/backend";
import { readSession } from "@/lib/session";
import { enterprise } from "@/lib/deployment";

async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const who = await readSession();
  if (!who) return Response.json({ error: "请先登录。" }, { status: 401 });
  const path = (await context.params).path.join("/");
  const method = request.method;
  const allowed = method === "GET" ? /^(me|status|sources|settings|members|knowledge|conversations(?:\/[\w-]+)?|audit(?:\/verify)?|eval(?:\/cases)?|stats|lab\/scenarios|approvals(?:\/[\w-]+)?)$/ :
    method === "PUT" ? /^(settings|members\/[\w-]+(?:\/password)?|account\/password)$/ : /^(ask(?:\/stream)?|knowledge\/import|members|lab\/scan|lab\/tamper|lab\/compare|approvals\/[\w-]+\/decide)$/;
  if (!allowed.test(path)) return Response.json({ error: "接口不存在。" }, { status: 404 });
  if ((/^(settings|members|knowledge)/.test(path) || path === "approvals" || /^approvals\/[\w-]+\/decide$/.test(path)) && !["admin", "security"].includes(who.role)) return Response.json({ error: "需要管理员权限。" }, { status: 403 });
  if ((/^(audit|eval|stats)/.test(path) || path === "lab/tamper") && !["admin", "security", "auditor"].includes(who.role)) return Response.json({ error: "需要审计权限。" }, { status: 403 });
  if (enterprise && path.startsWith("eval")) return Response.json({ error: "评测只在独立演示环境开放。" }, { status: 403 });
  if (method !== "GET") {
    const origin = request.headers.get("origin");
    if (origin && origin !== new URL(process.env.BUTLER_PUBLIC_URL || request.url).origin) return Response.json({ error: "请求来源不正确。" }, { status: 403 });
  }
  try {
    let body: Record<string, unknown> | undefined;
    if (method !== "GET") {
      if (Number(request.headers.get("content-length")) > 2_000_000) return Response.json({ error: "导入内容不能超过 2 MB。" }, { status: 413 });
      const raw = await request.text();
      if (new TextEncoder().encode(raw).length > 2_000_000) return Response.json({ error: "导入内容不能超过 2 MB。" }, { status: 413 });
      try { body = JSON.parse(raw); } catch { return Response.json({ error: "请求格式不正确。" }, { status: 400 }); }
      if (!body || typeof body !== "object" || Array.isArray(body)) return Response.json({ error: "请求格式不正确。" }, { status: 400 });
    }
    const target = path.startsWith("eval") ? `/${path}` : `/workspace/${path}`;
    const response = await backend(target, { method,
      ...(body ? { body: JSON.stringify(body), headers: { "content-type": "application/json" } } : {}),
    }, who.id);
    if (path === "ask/stream" && response.ok) return new Response(response.body, { status: 200, headers: { "content-type": "application/x-ndjson", "cache-control": "no-store", "x-accel-buffering": "no" } });
    return new Response(await response.text(), { status: response.status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
  } catch { return Response.json({ error: "暂时无法连接工作区，请稍后重试。" }, { status: 502 }); }
}

export { handle as GET, handle as POST, handle as PUT };
