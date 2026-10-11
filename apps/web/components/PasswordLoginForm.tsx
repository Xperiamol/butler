"use client";
import { useActionState, useState } from "react";
import { passwordLogin } from "@/app/login/actions";

export default function PasswordLoginForm() {
  const [error, action, pending] = useActionState(passwordLogin, "");
  const [username, setUsername] = useState("");
  return <form action={action} className="login-form"><fieldset className="settings-fields field-stack" disabled={pending}>
    <label className="field">账号<input name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={80} required placeholder="输入账号" value={username} onChange={(e) => setUsername(e.target.value)} /></label>
    <label className="field">密码<input name="password" type="password" autoComplete="current-password" maxLength={128} required placeholder="输入密码" /></label>
    {error && <p className="error" role="alert">{error}</p>}
    <button className="btn primary login-submit" disabled={pending}>{pending ? "正在登录…" : "登录"}<span aria-hidden="true">↗</span></button>
  </fieldset><p className="login-disclosure">账号由管理员开通。忘记密码请联系管理员。</p></form>;
}
