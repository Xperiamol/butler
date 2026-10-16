"use client";
import { useEffect, useRef, useState } from "react";
import { switchIdentity } from "@/app/login/actions";
import type { Identity } from "@/lib/api";

/** Demo-only: jump between the demo accounts without logging out (the scenarios are all about different people seeing different answers). */
export default function AccountSwitcher({ current }: { current: string }) {
  const [open, setOpen] = useState(false);
  const [people, setPeople] = useState<Identity[] | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open || people) return;
    fetch("/api/identities", { cache: "no-store" }).then((r) => r.ok ? r.json() : []).then(setPeople).catch(() => setPeople([]));
  }, [open, people]);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close); return () => document.removeEventListener("mousedown", close);
  }, []);
  return <div className="switcher" ref={box}>
    <button className="switcher-button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-label="切换演示账号" title="切换演示账号">⇄</button>
    {open && <div className="switcher-menu" role="menu"><span>切换演示账号</span>{!people ? <p><span className="spinner" /> 读取…</p> : people.map((p) => <form action={switchIdentity} key={p.id}><input type="hidden" name="identity" value={p.id} /><input type="hidden" name="next" value="/workspace" /><button role="menuitem" disabled={p.id === current} className={p.id === current ? "is-current" : ""}><b>{p.name.split("（")[0]}</b><small>{p.name.match(/（(.+)）/)?.[1] ?? p.role}</small>{p.id === current && <i aria-hidden="true">●</i>}</button></form>)}</div>}
  </div>;
}
