"use client";
import { useEffect, useState, type ReactNode } from "react";
import CitationCards from "./CitationCards";
import SourceChip from "./SourceChip";
import type { Citation } from "@/lib/api";

const INLINE = /(\*\*[^*\n]+\*\*|\[[A-Za-z0-9_.:/@\-]+\])/g;

/** Inline text: **bold** and [source-id] markers, which become numbered references matching the source list below. */
function inline(text: string, index: Map<string, number>, keyBase: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={`${keyBase}${i}`}>{part.slice(2, -2)}</strong>;
    const id = part.match(/^\[([A-Za-z0-9_.:/@\-]+)\]$/)?.[1];
    if (id !== undefined) { const n = index.get(id); return n ? <sup key={`${keyBase}${i}`} className="cite-ref" title={id}>{n}</sup> : null; }
    return part;
  });
}

type Block = { kind: "p" | "h" | "ul" | "todo"; lines: string[] };
function blocks(raw: string): Block[] {
  const out: Block[] = [];
  for (const line of raw.split("\n")) {
    const t = line.trim();
    if (!t) { out.push({ kind: "p", lines: [] }); continue; }
    const last = out[out.length - 1];
    if (/^#{1,4}\s+/.test(t)) out.push({ kind: "h", lines: [t.replace(/^#{1,4}\s+/, "")] });
    else if (/^[-*•]\s+/.test(t)) { const item = t.replace(/^[-*•]\s+/, ""); if (last?.kind === "ul") last.lines.push(item); else out.push({ kind: "ul", lines: [item] }); }
    else if (/^(待确认|注意|提示)[:：]/.test(t)) out.push({ kind: "todo", lines: [t] });
    else if (last?.kind === "p" && last.lines.length) last.lines.push(t); else out.push({ kind: "p", lines: [t] });
  }
  return out.filter((b) => b.lines.length);
}

/** `typing` reveals the text progressively (a freshly arrived answer); the source list appears once it is done. */
export default function AnswerText({ text, citations, highlight = false, typing = false }: { text: string; citations: Citation[]; highlight?: boolean; typing?: boolean }) {
  // Rule-based answers arrive as "- [id] fact"; show the fact with its reference at the end, like the model answers do.
  const raw = text.split("\n").map((l) => l.replace(/^- \[([\w.:/@-]+)\]\s+(.*)$/, "- $2 [$1]")).join("\n").trim();
  const [shown, setShown] = useState(typing ? 0 : raw.length);
  useEffect(() => {
    if (!typing || matchMedia("(prefers-reduced-motion: reduce)").matches) { setShown(raw.length); return; }
    let frame = 0; const start = performance.now(), duration = Math.min(3200, Math.max(700, raw.length * 9));
    const tick = (now: number) => { const t = Math.min((now - start) / duration, 1); setShown(Math.round(raw.length * (1 - Math.pow(1 - t, 2)))); if (t < 1) frame = requestAnimationFrame(tick); };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [typing, raw]);
  const done = shown >= raw.length;
  let visible = (done ? raw : raw.slice(0, shown)).replace(/\[[^\]]*$/, "");
  if ((visible.match(/\*\*/g) ?? []).length % 2 === 1) { const at = visible.lastIndexOf("**"); visible = visible.slice(0, at) + (done ? visible.slice(at + 2) : ""); }   // 不成对的 ** 不显示
  const index = new Map(citations.map((c, i) => [c.id, i + 1]));
  return <div className={`answer-text ${typing && !done ? "is-typing" : ""}`}>
    {blocks(visible).map((b, i) => b.kind === "h" ? <h4 key={i}>{inline(b.lines[0], index, `h${i}`)}</h4>
      : b.kind === "ul" ? <ul key={i}>{b.lines.map((l, k) => <li key={k}>{inline(l, index, `u${i}${k}`)}</li>)}</ul>
      : b.kind === "todo" ? <p key={i} className="answer-todo">{inline(b.lines[0], index, `t${i}`)}</p>
      : <p key={i} className={highlight && b.lines[0].startsWith("综合判断") ? "inference-line" : undefined}>{inline(b.lines.join(" "), index, `p${i}`)}</p>)}
    {citations.length > 0 && done && (citations.some((c) => c.container || c.modality) ? <div className="cites-in"><CitationCards citations={citations} /></div> : <div className="cites cites-in">{citations.map((c, i) => <SourceChip key={c.id} c={c} n={i + 1} />)}</div>)}
  </div>;
}
