"use client";
import { useEffect, useRef, useState } from "react";
import { MODALITY_LABEL, SOURCE_META, mediaUrl, workspaceApi, type Citation } from "@/lib/api";

export const ago = (ts?: number | null) => {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  return s < 90 ? "刚刚" : s < 3600 ? `${Math.floor(s / 60)} 分钟前` : s < 86400 ? `${Math.floor(s / 3600)} 小时前` : s < 86400 * 60 ? `${Math.floor(s / 86400)} 天前` : `${Math.floor(s / 86400 / 30)} 个月前`;
};
const MARK: Record<string, string> = { confluence: "C", jira: "J", slack: "S", drive: "D", upload: "U" };
const fmtTime = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function Transcript({ id, audio }: { id: string; audio: React.RefObject<HTMLAudioElement | null> }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof workspaceApi.transcript>> | null>(null), [error, setError] = useState(false);
  useEffect(() => { let live = true; workspaceApi.transcript(id).then((d) => { if (live) setData(d); }).catch(() => { if (live) setError(true); }); return () => { live = false; }; }, [id]);
  if (error) return <p className="cite-note">暂时读不到转写。</p>;
  if (!data) return <p className="cite-note"><span className="spinner" /> 读取转写…</p>;
  return <ol className="transcript">{data.segments.map((s, i) => <li key={i}><button onClick={() => { if (audio.current) { audio.current.currentTime = s.start; void audio.current.play(); } }}><span>{fmtTime(s.start)}</span><b>{s.speaker}</b>{s.text}</button></li>)}</ol>;
}

function Card({ c, n }: { c: Citation; n: number }) {
  const meta = SOURCE_META[c.source] ?? { label: c.source, color: "#888" };
  const [open, setOpen] = useState(false), [zoom, setZoom] = useState(false);
  const audio = useRef<HTMLAudioElement>(null), dialog = useRef<HTMLDialogElement>(null);
  const modality = c.modality ?? "text", mediaId = c.id;
  const rich = c.media && (modality === "image" || modality === "audio" || modality === "pdf");
  return <article className={`cite-card modality-${modality}`} style={{ "--i": n } as React.CSSProperties}>
    <header><span className="chip-no">{n}</span><span className="cite-platform" style={{ "--c": meta.color } as React.CSSProperties}><i>{MARK[c.source] ?? "?"}</i>{meta.label}</span>{modality !== "text" && <span className="cite-modality">{MODALITY_LABEL[modality] ?? modality}</span>}</header>
    <h5 title={c.id}>{c.title}</h5>
    <p className="cite-where">{c.container ?? c.source}{c.updated ? ` · 更新于 ${ago(c.updated)}` : ""}</p>
    {rich && modality === "image" && <button className="cite-thumb" onClick={() => { setZoom(true); dialog.current?.showModal(); }} aria-label="放大查看图片"><img src={mediaUrl(mediaId)} alt={c.file_name ?? c.title} loading="lazy" /></button>}
    {rich && modality === "audio" && <div className="cite-audio"><audio ref={audio} controls preload="none" src={mediaUrl(mediaId)} /><button className="btn sm" onClick={() => setOpen((v) => !v)}>{open ? "收起转写" : "查看转写"}</button>{open && <Transcript id={mediaId} audio={audio} />}</div>}
    {rich && modality === "pdf" && <a className="cite-open" href={mediaUrl(mediaId)} target="_blank" rel="noreferrer">打开扫描件原文件 ↗</a>}
    {!rich && (modality === "audio" || modality === "video") && <p className="cite-note">只有转写文本，没有实体文件</p>}
    {c.synced && <footer>同步于 {ago(c.synced)}{c.kind ? ` · ${c.kind}` : ""}</footer>}
    <dialog ref={dialog} className="image-dialog" onClose={() => setZoom(false)} onClick={(e) => { if (e.target === dialog.current) dialog.current?.close(); }}>{zoom && <><img src={mediaUrl(mediaId)} alt={c.file_name ?? c.title} /><button className="btn sm" onClick={() => dialog.current?.close()}>关闭 ×</button></>}</dialog>
  </article>;
}

/** Sources under an answer: which platform each came from, what kind of material it is, how fresh it is, and the original image / recording / scan when there is one. */
export default function CitationCards({ citations }: { citations: Citation[] }) {
  return <div className="cite-grid">{citations.map((c, i) => <Card key={c.id} c={c} n={i + 1} />)}</div>;
}
