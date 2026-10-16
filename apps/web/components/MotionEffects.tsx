"use client";
import { useEffect, useRef } from "react";

/** Page-wide polish: scroll progress, a soft cursor glow, magnetic primary buttons, button ripples and card tilt. */
export default function MotionEffects() {
  const progress = useRef<HTMLDivElement>(null);
  const glow = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const fine = window.matchMedia("(pointer: fine)").matches;
    let frame = 0, gx = -400, gy = -400, tx = -400, ty = -400, running = false;
    const onScroll = () => {
      const max = document.documentElement.scrollHeight - innerHeight;
      progress.current?.style.setProperty("--p", String(max > 0 ? Math.min(scrollY / max, 1) : 0));
    };
    const loop = () => {
      gx += (tx - gx) * 0.14; gy += (ty - gy) * 0.14;
      if (glow.current) glow.current.style.transform = `translate3d(${gx - 220}px, ${gy - 220}px, 0)`;
      if (Math.abs(tx - gx) + Math.abs(ty - gy) > 0.5) frame = requestAnimationFrame(loop); else running = false;
    };
    let magnet: HTMLElement | null = null, tilted: HTMLElement | null = null;
    const release = (el: HTMLElement | null) => { if (el) { el.style.transform = ""; el.style.transition = "transform .45s cubic-bezier(.22,1,.36,1)"; } };
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      tx = e.clientX; ty = e.clientY; glow.current?.classList.add("on");
      if (!running) { running = true; frame = requestAnimationFrame(loop); }
      if (reduced) return;
      const target = (e.target as Element | null)?.closest<HTMLElement>(".btn.primary, [data-magnetic]") ?? null;
      if (magnet && magnet !== target) { release(magnet); magnet = null; }
      if (target && !target.hasAttribute("disabled")) {
        const r = target.getBoundingClientRect();
        target.style.transition = "transform .12s ease-out";
        target.style.transform = `translate(${(e.clientX - (r.left + r.width / 2)) * 0.18}px, ${(e.clientY - (r.top + r.height / 2)) * 0.28}px)`;
        magnet = target;
      }
      const card = (e.target as Element | null)?.closest<HTMLElement>("[data-tilt]") ?? null;
      if (tilted && tilted !== card) { release(tilted); tilted = null; }
      if (card) {
        const r = card.getBoundingClientRect(), px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
        card.style.transition = "transform .12s ease-out";
        card.style.transform = `perspective(900px) rotateX(${(-py * 5).toFixed(2)}deg) rotateY(${(px * 6).toFixed(2)}deg) translateY(-3px)`;
        card.style.setProperty("--mx", `${((px + 0.5) * 100).toFixed(1)}%`); card.style.setProperty("--my", `${((py + 0.5) * 100).toFixed(1)}%`);
        tilted = card;
      }
    };
    const onLeave = () => { glow.current?.classList.remove("on"); release(magnet); release(tilted); magnet = tilted = null; };
    const onDown = (e: PointerEvent) => {
      if (reduced) return;
      const button = (e.target as Element | null)?.closest<HTMLElement>(".btn, .story-rail button, .scenario-tabs button");
      if (!button || button.hasAttribute("disabled")) return;
      const r = button.getBoundingClientRect(), size = Math.max(r.width, r.height) * 1.6, ripple = document.createElement("span");
      ripple.className = "ripple"; ripple.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`;
      button.classList.add("has-ripple"); button.appendChild(ripple); setTimeout(() => ripple.remove(), 650);
    };
    onScroll();
    addEventListener("scroll", onScroll, { passive: true }); addEventListener("resize", onScroll);
    if (fine) { document.addEventListener("pointermove", onMove, { passive: true }); document.documentElement.addEventListener("pointerleave", onLeave); }
    document.addEventListener("pointerdown", onDown);
    return () => { cancelAnimationFrame(frame); removeEventListener("scroll", onScroll); removeEventListener("resize", onScroll); document.removeEventListener("pointermove", onMove); document.documentElement.removeEventListener("pointerleave", onLeave); document.removeEventListener("pointerdown", onDown); };
  }, []);
  return <><div ref={progress} className="scroll-progress" aria-hidden="true" /><div ref={glow} className="cursor-glow" aria-hidden="true" /></>;
}
