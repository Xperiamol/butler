"use client";
import { useState } from "react";
import { workspaceApi } from "@/lib/api";

export default function AccountPanel({ username }: { username: string }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  return <main className="admin-page"><div className="admin-heading"><div><span className="overline">个人 / 账号</span><h1>账号设置</h1><p>{username}</p></div></div><section className="admin-section"><h2>修改密码</h2><form className="account-password-form field-stack" onSubmit={async (e) => {
    e.preventDefault(); const values = new FormData(e.currentTarget); setError("");
    if (values.get("password") !== values.get("confirm")) { setError("两次输入的新密码不一致。"); return; }
    setBusy(true); try { await workspaceApi.changePassword(String(values.get("current_password")), String(values.get("password"))); window.location.assign("/login"); } catch (e) { setError(e instanceof Error ? e.message : "修改失败。"); setBusy(false); }
  }}><fieldset className="settings-fields field-stack" disabled={busy}>
    <input className="sr-only" name="username" autoComplete="username" value={username} readOnly />
    <label className="field">当前密码<input name="current_password" type="password" autoComplete="current-password" maxLength={128} required /></label>
    <label className="field">新密码<input name="password" type="password" autoComplete="new-password" minLength={15} maxLength={128} required /></label>
    <label className="field">确认新密码<input name="confirm" type="password" autoComplete="new-password" minLength={15} maxLength={128} required /></label>
    <p className="field-help">15–128 个字符。修改后需重新登录。</p>{error && <p className="error" role="alert">{error}</p>}<button className="btn primary" disabled={busy}>{busy ? "正在修改…" : "修改密码"}</button>
  </fieldset></form></section></main>;
}
