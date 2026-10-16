import type { AskResult } from "@/lib/api";

export const fmtMs = (ms: number) => ms < 1000 ? `${ms.toFixed(ms < 10 ? 1 : 0)} ms` : `${(ms / 1000).toFixed(1)} 秒`;

const RESULT: Record<string, { text: string; tone: "ok" | "warn" | "stop" }> = {
  answered: { text: "未触及受限结论", tone: "ok" },
  degraded: { text: "去掉了越权推断", tone: "warn" },
  needs_approval: { text: "触及受限结论，需授权", tone: "stop" },
  refused: { text: "无法确认，已拒答", tone: "stop" },
  citation_failed: { text: "引用对不上，已拒答", tone: "stop" },
  no_evidence: { text: "没有可用资料", tone: "warn" },
};

/** The four checks every answer went through, as a strip that lights up in order. */
export default function GuardTrace({ answer }: { answer: AskResult }) {
  const status = answer.status ?? "answered", result = RESULT[status] ?? RESULT.answered;
  const steps: { name: string; detail: string; tone: "ok" | "warn" | "stop" }[] = [
    { name: "身份与权限", detail: "只取有权读的资料", tone: "ok" },
    { name: "会话账本", detail: "合并此前已给你的内容", tone: "ok" },
    { name: "结论检查", detail: result.text, tone: result.tone },
    { name: "审计", detail: status === "needs_approval" ? "申请已登记" : "已记入哈希链", tone: status === "needs_approval" ? "warn" : "ok" },
  ];
  return <ol className="guard-trace" aria-label="这次回答经过的检查">
    {steps.map((s, i) => <li key={s.name} className={`trace-${s.tone}`} style={{ "--i": i } as React.CSSProperties}><span className="trace-mark" aria-hidden="true">{s.tone === "ok" ? "✓" : s.tone === "warn" ? "!" : "×"}</span><span><b>{s.name}</b><small>{s.detail}</small></span></li>)}
    {answer.guard_ms !== undefined && <li className="trace-time" style={{ "--i": 4 } as React.CSSProperties}>检查 {fmtMs(answer.guard_ms)}</li>}
  </ol>;
}
