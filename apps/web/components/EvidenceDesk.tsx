"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import type { DeskSource, DeskView, StoryPhase } from "@/lib/demo-story";

const DeskScene = dynamic(() => import("./DeskScene"), { ssr: false });
type Props = { sources: DeskSource[]; view: DeskView; replay: number; onMotion: (phase: StoryPhase, active: boolean) => void };

export default function EvidenceDesk({ sources, view, replay, onMotion }: Props) {
  const [desktop, setDesktop] = useState(false);
  const [ready, setReady] = useState(false);
  const fallback = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const media = window.matchMedia("(min-width: 1001px)");
    const update = () => { setDesktop(media.matches); if (!media.matches) setReady(false); };
    update(); media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (ready || !fallback.current) return;
    const root = fallback.current;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    onMotion(view.phase, true);
    root.dataset.settled = "false";
    const nodes = [...root.querySelectorAll<HTMLElement>(".fallback-motion")];
    const duration = reduce ? 0 : [850, 1400, 1900, 1500][view.phase];
    const animations = nodes.map((node, i) => node.animate([
      { opacity: 0, transform: view.phase === 3 ? "translateX(-28px) rotate(-2deg)" : "translateY(18px) rotate(-1.5deg)" },
      { opacity: 1, transform: "translate(0) rotate(0)" },
    ], { duration: reduce ? 0 : 550, delay: reduce ? 0 : i * 100, easing: "cubic-bezier(.22,1,.36,1)", fill: "both" }));
    const timeline = root.animate([{ opacity: 1 }, { opacity: 1 }], { duration });
    let live = true;
    timeline.finished.then(() => { if (live) { root.dataset.settled = "true"; onMotion(view.phase, false); } }).catch(() => {});
    return () => { live = false; timeline.cancel(); animations.forEach((animation) => animation.cancel()); };
  }, [ready, view, replay, onMotion]);
  const sent = view.phase === 3;
  const facts = sent ? view.sentFacts : view.facts;
  const claim = sent ? view.sentClaim : view.claim;
  return <div className={`evidence-desk ${ready ? "desk-ready" : ""}`} data-phase={view.phase}>
    {desktop && <DeskScene sources={sources} view={view} replay={replay} onReady={setReady} onMotion={onMotion} />}
    <div ref={fallback} className="desk-fallback" hidden={ready} data-phase={view.phase}>
      {view.phase === 0 ? <div className="evidence-papers">{sources.map((source, i) => <article className={`evidence-paper fallback-motion ${view.multi && i + 1 === view.round ? "current-round" : ""}`} key={source.id}><div className="paper-heading"><span className="paper-source">{source.source}</span><span className="paper-access">{view.multi ? i + 1 === view.round ? "本轮" : i + 1 < view.round ? "已问" : "待问" : "✓ 可访问"}</span></div><p className="paper-message">{source.text}</p><span className="paper-footer">{source.id}</span></article>)}</div> : <article key={`${view.phase}-${view.round}-${replay}`} className={`fallback-letter fallback-motion ${view.phase === 2 && view.blocked ? "is-blocked" : ""}`}>
        <header><span>{sent ? `发给 ${view.reader}` : view.phase === 2 ? "Butler · 核对权限" : "普通助手 · 草稿"}</span><span>{view.citations} 份引用 · 摘录</span></header>
        <div className="fallback-facts">{facts.map((fact, i) => <p key={i} className={view.phase === 1 ? "fallback-motion" : undefined}><span aria-hidden="true">{view.phase > 1 ? "✓" : "·"}</span>{fact}</p>)}</div>
        {claim && <div className={`fallback-claim ${view.phase === 1 ? "fallback-motion" : ""} ${view.phase === 2 && view.blocked ? "is-rejected" : ""}`}><span>{view.phase === 2 && view.blocked ? "越权推断" : "推断"}</span><p>{claim}</p></div>}
        {view.phase === 2 && <><div className="fallback-scan" aria-hidden="true" /><div className={`fallback-verdict ${view.blocked ? "rejected" : ""}`}><span>{view.reader} · {view.role}</span><b>{view.blocked ? "去掉越权推断" : "权限匹配"}</b></div></>}
        {sent && <footer className="fallback-receipt">✓ 已发出 <span>身份 → 来源 → 判定</span></footer>}
      </article>}
    </div>
  </div>;
}
