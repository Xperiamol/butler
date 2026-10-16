"use client";
import { useEffect, useState } from "react";
import SourceChip from "./SourceChip";
import type { Citation } from "@/lib/api";

/** `typing` reveals the text progressively (used for a freshly arrived answer); citations appear once it is done. */
export default function AnswerText({ text, citations, highlight = false, typing = false }: { text: string; citations: Citation[]; highlight?: boolean; typing?: boolean }) {
  const lines = text.split("\n").filter(Boolean).map((line) => line.replace(/^- \[[\w.:/-]+\] /, ""));
  const total = lines.reduce((n, line) => n + line.length, 0);
  const [shown, setShown] = useState(typing ? 0 : total);
  useEffect(() => {
    if (!typing || matchMedia("(prefers-reduced-motion: reduce)").matches) { setShown(total); return; }
    let frame = 0; const start = performance.now(), duration = Math.min(2400, Math.max(700, total * 16));
    const tick = (now: number) => { const t = Math.min((now - start) / duration, 1); setShown(Math.round(total * (1 - Math.pow(1 - t, 2)))); if (t < 1) frame = requestAnimationFrame(tick); };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [typing, total]);
  let left = shown;
  const done = shown >= total;
  return <div className={`answer-text ${typing && !done ? "is-typing" : ""}`}>{lines.map((line, i) => { const part = line.slice(0, Math.max(0, left)); left -= line.length; return part ? <p key={i} className={highlight && line.startsWith("综合判断") ? "inference-line" : undefined}>{part}</p> : null; })}
    {citations.length > 0 && done && <div className="cites cites-in">{citations.map((c) => <SourceChip key={c.id} c={c} />)}</div>}
  </div>;
}
