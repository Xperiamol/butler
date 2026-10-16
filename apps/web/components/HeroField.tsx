"use client";
import { useEffect, useRef } from "react";

type P = { x: number; y: number; vx: number; vy: number; r: number; secret: boolean; heat: number };
/**
 * Hero backdrop: documents drift and link up; a few "protected conclusion" fragments try to reach the centre
 * and are pushed back by a scanning ring that follows the pointer. It is the product in one picture.
 */
export default function HeroField() {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = canvas.current; const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, dpr = 1, frame = 0, visible = true, particles: P[] = [];
    const pointer = { x: -999, y: -999, active: false };
    const ring = { x: 0, y: 0, r: 96 };
    const build = () => {
      const box = el.getBoundingClientRect(); w = box.width; h = box.height; dpr = Math.min(devicePixelRatio || 1, 2);
      el.width = w * dpr; el.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.max(36, Math.min(110, Math.round((w * h) / 15000)));
      particles = Array.from({ length: count }, (_, i) => ({ x: Math.random() * w, y: Math.random() * h, vx: (Math.random() - 0.5) * 0.32, vy: (Math.random() - 0.5) * 0.32, r: 1.2 + Math.random() * 1.7, secret: i < 7, heat: 0 }));
      ring.x = w * 0.56; ring.y = h * 0.46;
    };
    const draw = (time: number) => {
      ctx.clearRect(0, 0, w, h);
      const idle = !pointer.active, gx = idle ? w * 0.56 + Math.cos(time / 2600) * w * 0.07 : pointer.x, gy = idle ? h * 0.46 + Math.sin(time / 2100) * h * 0.14 : pointer.y;
      ring.x += (gx - ring.x) * 0.06; ring.y += (gy - ring.y) * 0.06; ring.r = 92 + Math.sin(time / 700) * 5;
      const goal = { x: w * 0.3, y: h * 0.52 };
      for (const p of particles) {
        if (p.secret) { p.vx += (goal.x - p.x) * 0.00005; p.vy += (goal.y - p.y) * 0.00005; }
        const dx = p.x - ring.x, dy = p.y - ring.y, d = Math.hypot(dx, dy);
        const near = d < ring.r + (p.secret ? 26 : 0);
        if (p.secret && near) { const f = (ring.r + 26 - d) * 0.0028; p.vx += (dx / (d || 1)) * f * 6; p.vy += (dy / (d || 1)) * f * 6; p.heat = 1; }
        p.heat *= 0.96; p.vx *= 0.995; p.vy *= 0.995;
        p.x += p.vx; p.y += p.vy;
        if (p.x < -10) p.x = w + 10; if (p.x > w + 10) p.x = -10; if (p.y < -10) p.y = h + 10; if (p.y > h + 10) p.y = -10;
      }
      for (let i = 0; i < particles.length; i++) for (let j = i + 1; j < particles.length; j++) {
        const a = particles[i], b = particles[j], d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d < 118) { const hot = a.secret || b.secret; ctx.strokeStyle = hot ? `rgba(170,116,87,${(1 - d / 118) * 0.32})` : `rgba(69,108,76,${(1 - d / 118) * 0.2})`; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
      }
      for (const p of particles) {
        const inside = Math.hypot(p.x - ring.x, p.y - ring.y) < ring.r;
        ctx.fillStyle = p.secret ? `rgba(170,116,87,${0.75 + p.heat * 0.25})` : inside ? "rgba(41,79,62,.95)" : "rgba(80,118,86,.55)";
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r * (inside ? 1.35 : 1) + (p.secret ? 1.2 + p.heat * 2 : 0), 0, Math.PI * 2); ctx.fill();
      }
      ctx.lineWidth = 1.2; ctx.strokeStyle = "rgba(41,79,62,.55)"; ctx.setLineDash([2, 7]);
      ctx.beginPath(); ctx.arc(ring.x, ring.y, ring.r, time / 1800, time / 1800 + Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
      ctx.strokeStyle = "rgba(41,79,62,.18)"; ctx.beginPath(); ctx.arc(ring.x, ring.y, ring.r - 14, 0, Math.PI * 2); ctx.stroke();
      ctx.font = "10px ui-monospace, Menlo, monospace"; ctx.fillStyle = "rgba(41,79,62,.65)"; ctx.fillText("权限检查", ring.x - 21, ring.y + ring.r + 18);
    };
    const loop = (time: number) => { if (visible && !document.hidden) draw(time); frame = requestAnimationFrame(loop); };
    build();
    if (reduced) draw(0); else frame = requestAnimationFrame(loop);
    const move = (e: PointerEvent) => { const b = el.getBoundingClientRect(); pointer.x = e.clientX - b.left; pointer.y = e.clientY - b.top; pointer.active = pointer.x >= 0 && pointer.y >= 0 && pointer.x <= b.width && pointer.y <= b.height; };
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; });
    observer.observe(el);
    const resize = new ResizeObserver(build); resize.observe(el);
    addEventListener("pointermove", move, { passive: true });
    return () => { cancelAnimationFrame(frame); observer.disconnect(); resize.disconnect(); removeEventListener("pointermove", move); };
  }, []);
  return <canvas ref={canvas} className="hero-field" aria-hidden="true" />;
}
