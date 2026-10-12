import SourceChip from "./SourceChip";
import type { Citation } from "@/lib/api";

export default function AnswerText({ text, citations, highlight = false }: { text: string; citations: Citation[]; highlight?: boolean }) {
  return <div className="answer-text">{text.split("\n").filter(Boolean).map((line, i) => <p key={i} className={highlight && line.startsWith("综合判断") ? "inference-line" : undefined}>{line.replace(/^- \[[\w.:/-]+\] /, "")}</p>)}
    {citations.length > 0 && <div className="cites">{citations.map((c) => <SourceChip key={c.id} c={c} />)}</div>}
  </div>;
}
