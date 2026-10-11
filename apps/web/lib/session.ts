import "server-only";
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import type { Identity } from "./api";
import { backend } from "./backend";
import { enterprise, localLogin, sessionSecret } from "./deployment";

const COOKIE = "butler_demo_session";
const AGE = 8 * 60 * 60;
// Local demo sessions survive hot reload; deployment should supply a stable secret.
const runtime = globalThis as typeof globalThis & { butlerSessionSecret?: string };
const secret = () => sessionSecret() || (runtime.butlerSessionSecret ??= randomBytes(32).toString("hex"));
const sign = (value: string) => createHmac("sha256", secret()).update(value).digest("base64url");

export async function createSession(identity: Identity) {
  const payload = Buffer.from(JSON.stringify({ identity: { id: identity.id }, version: identity.session_version ?? 0, auth: localLogin ? "local" : "oidc", mode: enterprise ? "enterprise" : "demo", expires: Date.now() + AGE * 1000 })).toString("base64url");
  (await cookies()).set(COOKIE, `${payload}.${sign(payload)}`, {
    httpOnly: true, sameSite: "lax", secure: enterprise || process.env.NODE_ENV === "production", path: "/", maxAge: AGE,
  });
}

export const readSession = cache(async (): Promise<Identity | null> => {
  const value = (await cookies()).get(COOKIE)?.value;
  if (!value) return null;
  try {
    const [payload, signature, extra] = value.split(".");
    if (!payload || !signature || extra) return null;
    const actual = Buffer.from(signature, "base64url");
    const expected = Buffer.from(sign(payload), "base64url");
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return null;
    const data = JSON.parse(Buffer.from(payload, "base64url").toString());
    if (typeof data.expires !== "number" || data.expires <= Date.now() || typeof data.identity?.id !== "string" || data.mode !== (enterprise ? "enterprise" : "demo")) return null;
    if ((enterprise || data.auth !== undefined) && data.auth !== (localLogin ? "local" : "oidc")) return null;
    // Roles and groups come from the database on every request, including revocation.
    const response = await backend("/workspace/me", undefined, data.identity.id);
    if (!response.ok) return null;
    const fresh = await response.json() as Identity;
    return (data.version ?? 0) === (fresh.session_version ?? 0) ? fresh : null;
  } catch { return null; }
});

export async function requireSession() {
  const identity = await readSession();
  if (!identity) redirect("/login");
  return identity;
}

export async function clearSession() { (await cookies()).delete(COOKIE); }
