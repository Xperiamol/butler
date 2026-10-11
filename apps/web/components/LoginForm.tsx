"use client";
import { useActionState, useState } from "react";
import { login } from "@/app/login/actions";
import type { Identity } from "@/lib/api";

const DESCRIPTIONS: Record<string, string> = {
  engineer: "查故障、看进度、找操作手册", contractor: "体验受限身份下的问答", security: "问答、审计与安全检查",
  pm: "查看项目与管理层资料", auditor: "查看授权范围内的审计记录",
};

export default function LoginForm({ identities }: { identities: Identity[] }) {
  const [selected, setSelected] = useState(identities[0]?.id ?? "");
  const [error, action, pending] = useActionState(login, "");
  return <form action={action} className="login-form">
    <fieldset disabled={pending}>
      <legend>选择演示账号</legend>
      {identities.map((i) => <label className={`account-option ${selected === i.id ? "selected" : ""}`} key={i.id}>
        <input type="radio" name="identity" value={i.id} checked={selected === i.id} onChange={() => setSelected(i.id)} />
        <span className="account-avatar">{i.name.slice(0, 1)}</span>
        <span><b>{i.name}</b><small>{DESCRIPTIONS[i.role] ?? i.groups.join(" · ")}</small></span>
        <span className="account-check" aria-hidden="true">{selected === i.id ? "✓" : ""}</span>
      </label>)}
    </fieldset>
    {error && <p className="error" role="alert">{error}</p>}
    <button className="btn primary login-submit" disabled={pending || !selected}>{pending ? "正在进入…" : "进入工作台"}<span aria-hidden="true">↗</span></button>
    <p className="login-disclosure">Sara 可管理资料、成员和配置。</p>
  </form>;
}
