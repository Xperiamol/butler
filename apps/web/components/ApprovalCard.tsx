"use client";
import { useEffect, useState } from "react";
import { workspaceApi, type ApprovalState, type AskResult } from "@/lib/api";

const clock = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

/** Shown in place of a plain refusal: the request is queued, and the card follows it until it is approved or denied. */
export default function ApprovalCard({ answer, onRetry, busy }: { answer: AskResult; onRetry: () => void; busy: boolean }) {
  const [state, setState] = useState<ApprovalState | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const id = answer.approval_id;
  useEffect(() => {
    if (!id) return; let live = true;
    const poll = () => workspaceApi.approval(id).then((s) => { if (live) setState(s); }).catch(() => {});
    void poll(); const timer = setInterval(() => { if (!document.hidden) void poll(); }, 3000);
    return () => { live = false; clearInterval(timer); };
  }, [id]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(timer); }, []);
  const status = state?.status === "approved" && state.expires && state.expires <= now ? "expired" : state?.status ?? "pending";
  const left = state?.expires ? Math.max(0, Math.floor(state.expires - now)) : 0;
  return <div className={`approval-card is-${status}`} role="status">
    <span className="approval-lock" aria-hidden="true"><svg viewBox="0 0 32 32"><path className="shackle" d="M10 14V10a6 6 0 0 1 12 0v4" /><rect x="6" y="14" width="20" height="14" rx="3" /><circle cx="16" cy="21" r="2" /></svg></span>
    <div>
      <b>{status === "approved" ? "已获批准" : status === "denied" ? "申请被拒绝" : status === "expired" ? "授权已到期" : "需要授权"}</b>
      <p>{status === "approved" ? "审批人放行了这项结论，在有效期内可以再问一次。" : status === "denied" ? "审批人没有批准。如有需要，请直接联系审批人说明用途。" : status === "expired" ? "预授权已过期，需要重新申请。" : answer.text}</p>
      <div className="approval-meta">
        {status === "pending" && <><span className="pulse-dots" aria-hidden="true"><i /><i /><i /></span><span>申请 {id ?? "—"} · 等待审批人处理</span></>}
        {status === "approved" && <><span className="countdown">{clock(left)}</span><span>后到期</span><button className="btn sm primary" disabled={busy} onClick={onRetry}>重新提问 →</button></>}
        {(status === "denied" || status === "expired") && <span>申请 {id ?? "—"}</span>}
      </div>
    </div>
  </div>;
}
