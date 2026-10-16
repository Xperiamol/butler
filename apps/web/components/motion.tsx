"use client";
import { createElement, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

export function usePrefersReduced() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update(); media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}

export function useInView<T extends Element>(threshold = 0.18) {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setSeen(true); observer.disconnect(); } }, { threshold, rootMargin: "0px 0px -6% 0px" });
    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold]);
  return [ref, seen] as const;
}

type RevealProps = { children: ReactNode; delay?: number; as?: string; className?: string; id?: string; style?: CSSProperties };
/** Fades and lifts its children in once, the first time they scroll into view. */
export function Reveal({ children, delay = 0, as = "div", className = "", ...rest }: RevealProps) {
  const [ref, seen] = useInView<HTMLElement>();
  return createElement(as, { ref, className: `reveal ${seen ? "in" : ""} ${className}`.trim(), ...rest, style: { ...rest.style, "--d": `${delay}ms` } as CSSProperties }, children);
}

export function CountUp({ value, decimals = 0, duration = 1100, suffix = "" }: { value: number; decimals?: number; duration?: number; suffix?: string }) {
  const [ref, seen] = useInView<HTMLSpanElement>(0.3);
  const reduced = usePrefersReduced();
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    if (!seen) return;
    if (reduced) { setShown(value); from.current = value; return; }
    let frame = 0; const start = performance.now(), origin = from.current;
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1), eased = 1 - Math.pow(1 - t, 3);
      const next = origin + (value - origin) * eased;
      setShown(next); from.current = next;
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [seen, value, duration, reduced]);
  return <span ref={ref}>{shown.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</span>;
}

/** Hand-drawn line chart: draws itself once visible. */
export function Sparkline({ data, height = 72, label }: { data: number[]; height?: number; label: string }) {
  const [ref, seen] = useInView<SVGSVGElement>(0.3);
  const width = 320, pad = 6, max = Math.max(1, ...data);
  const points = data.map((v, i) => [pad + (i * (width - pad * 2)) / Math.max(1, data.length - 1), height - pad - (v / max) * (height - pad * 2)]);
  const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${points[points.length - 1]?.[0].toFixed(1) ?? 0} ${height} L${pad} ${height} Z`;
  return <svg ref={ref} className={`sparkline ${seen ? "in" : ""}`} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} preserveAspectRatio="none">
    <path className="sparkline-area" d={area} /><path className="sparkline-line" d={line} pathLength={1} />
    {points.length > 0 && <circle className="sparkline-dot" cx={points[points.length - 1][0]} cy={points[points.length - 1][1]} r="3.5" />}
  </svg>;
}
