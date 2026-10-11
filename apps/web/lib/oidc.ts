import "server-only";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { createRemoteJWKSet, jwtVerify, SignJWT } from "jose";
import { cookies } from "next/headers";
import { backend } from "./backend";
import { enterprise, missingLoginConfiguration, sessionSecret } from "./deployment";
import { createSession } from "./session";
import type { Identity } from "./api";

const FLOW_COOKIE = "butler_oidc_flow";
const secureUrl = (value: string) => {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.hash) throw new Error("OIDC requires HTTPS");
  return url;
};

async function configuration() {
  if (!enterprise || missingLoginConfiguration().length) throw new Error("OIDC is not configured");
  const issuer = process.env.BUTLER_OIDC_ISSUER!;
  secureUrl(issuer);
  const origin = secureUrl(process.env.BUTLER_PUBLIC_URL!).origin;
  const response = await fetch(`${issuer.replace(/\/$/, "")}/.well-known/openid-configuration`, { cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error("OIDC discovery failed");
  const data = await response.json();
  if (data.issuer !== issuer) throw new Error("OIDC issuer mismatch");
  for (const key of ["authorization_endpoint", "token_endpoint", "jwks_uri"]) secureUrl(data[key]);
  return { issuer, origin, clientId: process.env.BUTLER_OIDC_CLIENT_ID!, secret: process.env.BUTLER_OIDC_CLIENT_SECRET!, ...data };
}

export async function startLogin() {
  const config = await configuration();
  const state = randomBytes(32).toString("base64url"), nonce = randomBytes(32).toString("base64url"), verifier = randomBytes(32).toString("base64url");
  const flow = await new SignJWT({ state, nonce, verifier }).setProtectedHeader({ alg: "HS256" }).setIssuedAt().setExpirationTime("10m")
    .sign(new TextEncoder().encode(sessionSecret()));
  (await cookies()).set(FLOW_COOKIE, flow, { httpOnly: true, secure: true, sameSite: "lax", path: "/auth", maxAge: 600 });
  const url = new URL(config.authorization_endpoint);
  url.search = new URLSearchParams({ client_id: config.clientId, response_type: "code", scope: "openid profile",
    redirect_uri: `${config.origin}/auth/callback`, state, nonce,
    code_challenge: createHash("sha256").update(verifier).digest("base64url"), code_challenge_method: "S256" }).toString();
  return url;
}

export async function finishLogin(url: URL) {
  const jar = await cookies(), flow = jar.get(FLOW_COOKIE)?.value;
  jar.delete(FLOW_COOKIE);
  if (!flow || url.searchParams.has("error")) throw new Error("Login was interrupted");
  const { payload } = await jwtVerify(flow, new TextEncoder().encode(sessionSecret()), { algorithms: ["HS256"] });
  const supplied = url.searchParams.get("state"), code = url.searchParams.get("code");
  if (typeof payload.state !== "string" || typeof payload.nonce !== "string" || typeof payload.verifier !== "string" || !supplied || !code) throw new Error("Invalid login flow");
  const a = Buffer.from(supplied), b = Buffer.from(payload.state);
  if (a.length !== b.length || !timingSafeEqual(a, b)) throw new Error("State mismatch");
  const config = await configuration();
  const body = new URLSearchParams({ grant_type: "authorization_code", code, redirect_uri: `${config.origin}/auth/callback`, code_verifier: payload.verifier });
  const headers: Record<string, string> = { "content-type": "application/x-www-form-urlencoded" };
  if (process.env.BUTLER_OIDC_CLIENT_AUTH_METHOD === "client_secret_post") {
    body.set("client_id", config.clientId); body.set("client_secret", config.secret);
  } else {
    const formEncode = (value: string) => new URLSearchParams([["", value]]).toString().slice(1);
    headers.authorization = `Basic ${Buffer.from(`${formEncode(config.clientId)}:${formEncode(config.secret)}`).toString("base64")}`;
  }
  const response = await fetch(config.token_endpoint, { method: "POST", headers, body, cache: "no-store", signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error("Token exchange failed");
  const token = await response.json();
  const { payload: claims } = await jwtVerify(token.id_token, createRemoteJWKSet(new URL(config.jwks_uri)), {
    issuer: config.issuer, audience: config.clientId, algorithms: ["RS256", "PS256", "ES256"], requiredClaims: ["sub", "iat", "exp", "nonce"], maxTokenAge: "10m",
  });
  if (claims.nonce !== payload.nonce || typeof claims.sub !== "string" || !claims.sub || (claims.azp !== undefined && claims.azp !== config.clientId) ||
      (Array.isArray(claims.aud) && claims.aud.length > 1 && claims.azp !== config.clientId)) throw new Error("Invalid ID token");
  const provision = await backend("/workspace/provision", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ issuer: config.issuer, subject: claims.sub, name: typeof claims.name === "string" && claims.name.trim() ? claims.name.trim().slice(0, 100) : claims.sub.slice(0, 100) }) });
  if (!provision.ok) throw new Error("Account is unavailable");
  await createSession(await provision.json() as Identity);
  return config.origin;
}
