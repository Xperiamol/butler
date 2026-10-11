import { publicDemo } from "@/lib/public-demo";

export async function POST(request: Request) {
  try {
    const raw = await request.text();
    if (raw.length > 6000) return Response.json({ error: "问题过长。" }, { status: 413 });
    const body = JSON.parse(raw);
    if (!body || typeof body !== "object" || !["ken", "pete", "alice", "sara", "amy"].includes(body.identity_id) ||
        typeof body.question !== "string" || !body.question.trim() || body.question.length > 4000 ||
        (body.session_id !== undefined && (typeof body.session_id !== "string" || body.session_id.length > 128))) {
      return Response.json({ error: "演示请求格式不正确。" }, { status: 400 });
    }
    return publicDemo("/compare", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ identity_id: body.identity_id, question: body.question, session_id: body.session_id }) });
  } catch { return Response.json({ error: "演示请求格式不正确。" }, { status: 400 }); }
}
