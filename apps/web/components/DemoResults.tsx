"use client";
import { useEffect, useRef, useState } from "react";
import type { EvalReport } from "@/lib/api";

export default function DemoResults({ report }: { report: EvalReport | null }) {
  const root = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setVisible(true); observer.disconnect(); }
    }, { threshold: 0.35 });
    if (root.current) observer.observe(root.current);
    return () => observer.disconnect();
  }, []);
  return <section id="results" className={`demo-results ${visible ? "is-visible" : ""}`} ref={root} aria-labelledby="results-heading">
    <div className="results-heading"><div><span className="demo-label">02 / 评测结果</span><h2 id="results-heading">少泄露，也少误拦。</h2></div><span>离线评测</span></div>
    <div className="results-content"><div className="result-bars" aria-label="受限结论泄露率">{[{ name: "仅查文档权限", rate: report?.doc.leak_rate, className: "before" }, { name: "Butler", rate: report?.butler.leak_rate, className: "after" }].map((item) => <div className={`result-bar-row ${item.className}`} key={item.name}><span>{item.name}</span><div className="result-bar-track"><div style={{ transform: `scaleX(${visible ? item.rate ?? 0 : 0})` }} /></div><strong>{item.rate === undefined ? "—" : `${Math.round(item.rate * 100)}%`}</strong></div>)}<p>受限结论泄露率</p></div><div className="results-facts"><div><strong>{report?.butler.attacks ?? "—"}<small>组</small></strong><span>攻击问题</span></div><div><strong>{report ? `${Math.round(report.butler.false_block_rate * 100)}%` : "—"}</strong><span>误拦率 · {report?.butler.controls ?? "—"} 组正常问题</span></div></div></div>
  </section>;
}
