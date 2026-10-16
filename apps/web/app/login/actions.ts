"use server";

import { redirect } from "next/navigation";
import { backend } from "@/lib/backend";
import { clearSession, createSession } from "@/lib/session";
import type { Identity } from "@/lib/api";
import { enterprise, localLogin, missingLoginConfiguration } from "@/lib/deployment";

export async function passwordLogin(_previous: string, form: FormData): Promise<string> {
  if (!localLogin) return "请使用企业统一身份登录。";
  if (enterprise && missingLoginConfiguration().length) return "登录服务配置不完整，请联系管理员。";
  const username = form.get("username"), password = form.get("password");
  if (typeof username !== "string" || typeof password !== "string" || !username.trim() || username.length > 80 || !password || password.length > 128) return "请填写账号和密码。";
  try {
    const response = await backend("/workspace/auth/password", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username, password }) });
    if (!response.ok) return response.status === 429 ? "尝试次数过多，请稍后再试。" : response.status === 401 ? "账号或密码不正确，或账号已停用。" : "登录暂时不可用，请稍后重试。";
    await createSession(await response.json() as Identity);
  } catch { return "暂时无法连接工作区，请稍后重试。"; }
  redirect("/workspace/overview");
}

export async function login(_previous: string, form: FormData): Promise<string> {
  if (enterprise) return "请使用企业账号登录。";
  try {
    const [health, people] = await Promise.all([backend("/health"), backend("/identities")]);
    if (!health.ok || !people.ok) return "暂时无法连接工作区，请稍后重试。";
    if ((await health.json()).data_source !== "fake") return "当前工作区未开放演示账号登录。";
    const identities: Identity[] = await people.json();
    const identity = identities.find((i) => i.id === form.get("identity"));
    if (!identity) return "请选择一个演示账号。";
    const current = await backend("/workspace/me", undefined, identity.id);
    if (!current.ok) return "这个账号已停用，请联系管理员。";
    await createSession(await current.json() as Identity);
  } catch { return "暂时无法连接工作区，请稍后重试。"; }
  redirect("/workspace/overview");
}

export async function logout() {
  await clearSession();
  redirect("/login");
}

/** Demo only: switch to another demo account without going through the login page (used by the console, the scenario runner and the sidebar). */
export async function switchIdentity(form: FormData) {
  if (enterprise) redirect("/login");
  const id = String(form.get("identity") ?? ""), next = String(form.get("next") ?? "/workspace");
  const safe = /^\/workspace[\w/-]*(\?q=[\w%.~+*'()!-]*)?$/.test(next) ? next : "/workspace";
  try {
    const [health, people] = await Promise.all([backend("/health"), backend("/identities")]);
    if (!health.ok || !people.ok || (await health.json()).data_source !== "fake") redirect("/login");
    const identities: Identity[] = await people.json();
    const identity = identities.find((i) => i.id === id);
    if (!identity) redirect("/login");
    const current = await backend("/workspace/me", undefined, identity.id);
    if (!current.ok) redirect("/login");
    await createSession(await current.json() as Identity);
  } catch (error) { if (error && typeof error === "object" && "digest" in error) throw error; redirect("/login"); }
  redirect(safe);
}
