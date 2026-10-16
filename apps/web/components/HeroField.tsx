"use client";
import { useEffect, useRef } from "react";

/**
 * Hero backdrop: a calm dot matrix that tells the product story on a 13-second loop.
 *   1. three "documents" light up as small dot cards — each one readable on its own;
 *   2. their dots fly together and assemble into a padlock — the conclusion they add up to;
 *   3. a scan line passes over it and stamps it as a protected conclusion;
 *   4. the dots fall back into the grid with a ripple.
 * The pointer acts as a lens. The left side fades out so the headline stays clean.
 */
type Dot = { hx: number; hy: number; x: number; y: number; vx: number; vy: number; tx: number; ty: number; role: number; heat: number };
const GAP = 18;
const LOOP = 13000;
const T = { docs: 1800, gather: 4200, scan: 6600, release: 9400, calm: 11400 };
const GREEN = [41, 79, 62], LEAF = [96, 132, 92], TERRA = [170, 104, 70];

function lockPoints(cell: number): [number, number][] {
  const size = 240, c = document.createElement("canvas"); c.width = c.height = size;
  const g = c.getContext("2d")!;
  g.fillStyle = "#000"; g.strokeStyle = "#000";
  g.lineWidth = 34; g.beginPath(); g.arc(120, 104, 54, Math.PI, 0); g.stroke();
  g.beginPath(); g.roundRect(28, 98, 184, 134, 22); g.fill();
  g.globalCompositeOperation = "destination-out";
  g.beginPath(); g.arc(120, 150, 17, 0, Math.PI * 2); g.fill(); g.fillRect(111, 156, 18, 42);
  const data = g.getImageData(0, 0, size, size).data, step = 240 / 14, out: [number, number][] = [];
  for (let y = step / 2; y < size; y += step) for (let x = step / 2; x < size; x += step) if (data[(Math.floor(y) * size + Math.floor(x)) * 4 + 3] > 128) out.push([(x - 120) / step, (y - 135) / step]);
  return out;
}

const ease = (t: number) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
const rgba = (c: number[], a: number) => `rgba(${c[0]},${c[1]},${c[2]},${a.toFixed(3)})`;

export default function HeroField() {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = canvas.current, ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, frame = 0, visible = true, dots: Dot[] = [], lock: [number, number][] = [];
    let box = { x0: 0, y0: 0, x1: 0, y1: 0 }, center = { x: 0, y: 0 }, cards: { x: number; y: number; label: string }[] = [];
    const pointer = { x: -9999, y: -9999 };
    const start = performance.now();

    const build = () => {
      const rect = el.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
      w = rect.width; h = rect.height; el.width = w * dpr; el.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      dots = [];
      const ox = (w % GAP) / 2 + GAP / 2, oy = (h % GAP) / 2 + GAP / 2;
      for (let y = oy; y < h; y += GAP) for (let x = ox; x < w; x += GAP) dots.push({ hx: x, hy: y, x, y, vx: 0, vy: 0, tx: x, ty: y, role: 0, heat: 0 });
      center = { x: w * (w > 900 ? 0.6 : 0.5), y: h * 0.5 };
      lock = lockPoints(GAP);
      box = { x0: center.x + Math.min(...lock.map((p) => p[0])) * GAP - GAP * 0.6, x1: center.x + Math.max(...lock.map((p) => p[0])) * GAP + GAP * 0.6, y0: center.y + Math.min(...lock.map((p) => p[1])) * GAP - GAP * 0.6, y1: center.y + Math.max(...lock.map((p) => p[1])) * GAP + GAP * 0.6 };
      cards = w > 900
        ? [{ x: w * 0.43, y: h * 0.24, label: "JIRA · 合同暂停" }, { x: w * 0.74, y: h * 0.2, label: "DRIVE · 预算归零" }, { x: w * 0.5, y: h * 0.82, label: "SLACK · 周五全员会" }]
        : [{ x: w * 0.2, y: h * 0.2, label: "JIRA" }, { x: w * 0.8, y: h * 0.25, label: "DRIVE" }, { x: w * 0.5, y: h * 0.85, label: "SLACK" }];
      // Card members: a 5×3 block of dots around each card centre. Lock members: the nearest card dots first, then neighbours.
      const near = (cx: number, cy: number, n: number) => dots.map((d, i) => [i, Math.hypot(d.hx - cx, (d.hy - cy) * 1.6)] as const).sort((a, b) => a[1] - b[1]).slice(0, n).map(([i]) => i);
      const cols = Math.ceil((w - ox) / GAP), at = (cx: number, cy: number) => [Math.round((cx - ox) / GAP), Math.round((cy - oy) / GAP)];
      cards.forEach((card, k) => { const [c0, r0] = at(card.x, card.y); for (let r = -1; r <= 1; r++) for (let c = -2; c <= 2; c++) { const d = dots[(r0 + r) * cols + c0 + c]; if (d) d.role = k + 1; } });
      const members = dots.map((d, i) => i).filter((i) => dots[i].role > 0);
      const extra = near(center.x, center.y, lock.length * 2).filter((i) => dots[i].role === 0).slice(0, Math.max(0, lock.length - members.length));
      const pool = [...members, ...extra].sort((a, b) => dots[a].hx - dots[b].hx);
      const targets = lock.map(([lx, ly]) => [center.x + lx * GAP, center.y + ly * GAP]).sort((a, b) => a[0] - b[0]);
      pool.forEach((i, k) => { const t = targets[k]; if (t) { dots[i].tx = t[0]; dots[i].ty = t[1]; dots[i].role = dots[i].role || 9; } });
    };

    const draw = (now: number) => {
      const t = reduced ? T.scan + 1200 : (now - start) % LOOP;
      const gather = ease((t - T.gather) / 1500) * (1 - ease((t - T.release) / 1200));
      const docs = ease((t - T.docs) / 700) * (1 - ease((t - T.gather - 600) / 900));
      const scanY = center.y - 8 * GAP + ((t - T.scan) / 1400) * 16 * GAP;
      const stamped = t > T.scan + 900 && t < T.release + 400;
      const ripple = t > T.release ? (t - T.release) / 1000 : -1;
      ctx.clearRect(0, 0, w, h);
      for (const d of dots) {
        const member = d.role > 0 && d.tx !== d.hx;
        const goalX = member ? d.hx + (d.tx - d.hx) * gather : d.hx, goalY = member ? d.hy + (d.ty - d.hy) * gather : d.hy;
        const px = d.x - pointer.x, py = d.y - pointer.y, pd = Math.hypot(px, py), lens = pd < 130 ? (1 - pd / 130) : 0;
        d.vx += (goalX + (px / (pd || 1)) * lens * 14 - d.x) * 0.09; d.vy += (goalY + (py / (pd || 1)) * lens * 14 - d.y) * 0.09;
        d.vx *= 0.74; d.vy *= 0.74; d.x += d.vx; d.y += d.vy;
        if (reduced) { d.x = goalX; d.y = goalY; }
        const fade = 0.22 + 0.78 * ease((d.hx / w - 0.12) / 0.34);   // keep the headline side quiet
        const wave = 0.5 + 0.5 * Math.sin(d.hx * 0.018 + d.hy * 0.011 - now / 900);
        let r = 1.05 + wave * 0.35 + lens * 1.6, a = (0.1 + wave * 0.08) * fade + lens * 0.35, color = LEAF;
        if (!member && gather > 0 && d.hx > box.x0 && d.hx < box.x1 && d.hy > box.y0 && d.hy < box.y1) a *= 1 - gather;   // clear the stage behind the lock
        if (d.role >= 1 && d.role <= 3 && docs > 0) { r += docs * 1.1; a += docs * 0.55; color = GREEN; }
        if (member && gather > 0.02) {
          d.heat = stamped || (t > T.scan && d.y < scanY) ? Math.min(1, d.heat + 0.08) : Math.max(0, d.heat - 0.04);
          r = r + (2.6 - r) * gather + lens * 0.6; a = Math.max(a, 0.25 + gather * 0.65);   // uniform size once assembled
          color = d.heat > 0.05 ? [GREEN[0] + (TERRA[0] - GREEN[0]) * d.heat, GREEN[1] + (TERRA[1] - GREEN[1]) * d.heat, GREEN[2] + (TERRA[2] - GREEN[2]) * d.heat] : GREEN;
        } else d.heat = 0;
        if (ripple >= 0 && ripple < 1.4) { const rd = Math.abs(Math.hypot(d.hx - center.x, d.hy - center.y) - ripple * w * 0.45); if (rd < 30) { r += (1 - rd / 30) * 1.2; a += (1 - rd / 30) * 0.3 * (1.4 - ripple); } }
        ctx.fillStyle = rgba(color, Math.min(a, 0.95));
        ctx.beginPath(); ctx.arc(d.x, d.y, r, 0, Math.PI * 2); ctx.fill();
      }
      ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace"; ctx.textAlign = "center";
      if (docs > 0.05) cards.forEach((c) => { ctx.fillStyle = rgba(GREEN, docs * 0.75); ctx.fillText(c.label, c.x, c.y + GAP * 2.2); ctx.fillStyle = rgba(GREEN, docs * 0.45); ctx.fillText("✓ 有权读", c.x, c.y - GAP * 1.6); });
      if (t > T.scan && t < T.scan + 1500 && gather > 0.9) {
        const grad = ctx.createLinearGradient(0, scanY - 26, 0, scanY + 2);
        grad.addColorStop(0, "rgba(170,104,70,0)"); grad.addColorStop(1, "rgba(170,104,70,.22)");
        ctx.fillStyle = grad; ctx.fillRect(center.x - 8 * GAP, scanY - 26, 16 * GAP, 28);
        ctx.fillStyle = "rgba(170,104,70,.85)"; ctx.fillRect(center.x - 8 * GAP, scanY, 16 * GAP, 1.5);
      }
      if (gather > 0.85 && t < T.scan) { ctx.fillStyle = rgba(GREEN, (gather - 0.85) * 5); ctx.fillText("拼在一起 = ?", center.x, center.y + 7.4 * GAP); }
      if (stamped) {
        const k = ease((t - T.scan - 900) / 400) * (1 - ease((t - T.release) / 400));
        ctx.fillStyle = rgba(TERRA, k * 0.95); ctx.fillText("受限结论 · 回答前拦下", center.x, center.y + 7.4 * GAP);
      }
    };

    const loop = (now: number) => { if (visible && !document.hidden) draw(now); frame = requestAnimationFrame(loop); };
    build();
    if (reduced) draw(performance.now()); else frame = requestAnimationFrame(loop);
    const move = (e: PointerEvent) => { const b = el.getBoundingClientRect(); pointer.x = e.clientX - b.left; pointer.y = e.clientY - b.top; };
    const leave = () => { pointer.x = pointer.y = -9999; };
    const io = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; }); io.observe(el);
    const ro = new ResizeObserver(() => { build(); if (reduced) draw(performance.now()); }); ro.observe(el);
    addEventListener("pointermove", move, { passive: true }); document.documentElement.addEventListener("pointerleave", leave);
    return () => { cancelAnimationFrame(frame); io.disconnect(); ro.disconnect(); removeEventListener("pointermove", move); document.documentElement.removeEventListener("pointerleave", leave); };
  }, []);
  return <canvas ref={canvas} className="hero-field" aria-hidden="true" />;
}
