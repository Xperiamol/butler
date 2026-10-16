"use client";
import Image from "next/image";
import { useEffect, useState } from "react";

const WORDS = ["查资料", "生成回答", "检查权限", "发出答案"];
/** One short intro per browser session. The inline script in the layout hides it for return visits before first paint. */
export default function Preloader() {
  const [count, setCount] = useState(0);
  const [phase, setPhase] = useState<"run" | "leave" | "gone">("run");
  useEffect(() => {
    let seen = false;
    try { seen = sessionStorage.getItem("butler-intro") === "1"; } catch { /* storage can be blocked */ }
    if (seen || matchMedia("(prefers-reduced-motion: reduce)").matches) { setPhase("gone"); return; }
    let frame = 0; const start = performance.now(), total = 1250;
    const tick = (now: number) => {
      const t = Math.min((now - start) / total, 1);
      setCount(Math.round((1 - Math.pow(1 - t, 2.4)) * 100));
      if (t < 1) frame = requestAnimationFrame(tick); else { try { sessionStorage.setItem("butler-intro", "1"); } catch { /* ignore */ } setPhase("leave"); setTimeout(() => setPhase("gone"), 900); }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);
  if (phase === "gone") return null;
  return <div className={`preloader ${phase === "leave" ? "leave" : ""}`} aria-hidden="true">
    <div className="preloader-inner">
      <Image src="/butler-avatar.png" width={96} height={96} alt="" priority />
      <div className="preloader-word"><span>butler</span><i>.</i></div>
      <div className="preloader-bar"><span style={{ transform: `scaleX(${count / 100})` }} /></div>
      <div className="preloader-meta"><span>{WORDS[Math.min(3, Math.floor(count / 26))]}…</span><b>{String(count).padStart(3, "0")}</b></div>
    </div>
  </div>;
}
