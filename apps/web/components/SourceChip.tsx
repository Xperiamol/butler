import { SOURCE_META, type Citation } from "@/lib/api";

export default function SourceChip({ c }: { c: Citation }) {
  const m = SOURCE_META[c.source] ?? { label: c.source, color: "#888" };
  return (
    <span className="chip" title={c.id}>
      <span className="dot" style={{ background: m.color }} />
      {m.label} · {c.title}
    </span>
  );
}
