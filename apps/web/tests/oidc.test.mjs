import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash, webcrypto } from "node:crypto";
import ts from "typescript";
import * as jose from "jose";

globalThis.crypto ??= webcrypto;
const source = await readFile(new URL("../lib/oidc.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const { publicKey, privateKey } = await jose.generateKeyPair("RS256");
const jwk = await jose.exportJWK(publicKey);
jwk.kid = "test-key";
const localKeys = jose.createLocalJWKSet({ keys: [jwk] });
const signingSecret = "test-session-secret-with-at-least-32-characters";

async function fixture(overrides = {}) {
  Object.assign(process.env, { BUTLER_MODE: "enterprise", BUTLER_PUBLIC_URL: "https://butler.example", BUTLER_OIDC_ISSUER: "https://issuer.example", BUTLER_OIDC_CLIENT_ID: "butler-client", BUTLER_OIDC_CLIENT_SECRET: "test-client-secret" });
  const jar = new Map(), provisions = [], sessions = [];
  let exchange;
  const modules = {
    "server-only": {}, "node:crypto": await import("node:crypto"),
    jose: { ...jose, createRemoteJWKSet: () => localKeys },
    "next/headers": { cookies: async () => ({ get: (key) => jar.has(key) ? { value: jar.get(key) } : undefined, set: (key, value) => jar.set(key, value), delete: (key) => jar.delete(key) }) },
    "./deployment": { enterprise: true, missingLoginConfiguration: () => [], sessionSecret: () => signingSecret },
    "./session": { createSession: async (identity) => sessions.push(identity) },
    "./backend": { backend: async (path, init) => { provisions.push({ path, body: JSON.parse(init.body) }); return Response.json({ id: "member-id", role: "employee", groups: [] }); } },
  };
  const fetchMock = async (url, init) => {
    if (String(url).includes("openid-configuration")) return Response.json({ issuer: overrides.discoveryIssuer || "https://issuer.example", authorization_endpoint: "https://issuer.example/authorize", token_endpoint: "https://issuer.example/token", jwks_uri: "https://issuer.example/jwks" });
    exchange = init;
    const { payload } = await jose.jwtVerify(jar.get("butler_oidc_flow"), new TextEncoder().encode(signingSecret));
    let token = await new jose.SignJWT({ nonce: overrides.nonce || payload.nonce, name: "Test User" }).setProtectedHeader({ alg: "RS256", kid: "test-key" }).setIssuer(overrides.issuer || "https://issuer.example").setAudience(overrides.audience || "butler-client").setSubject("subject-123").setIssuedAt().setExpirationTime("5m").sign(privateKey);
    if (overrides.invalidSignature) token = `${token.slice(0, -6)}AAAAAA`;
    return Response.json({ id_token: token });
  };
  // finishLogin consumes the flow cookie before the token request. Keep the
  // original signed flow in the mock transport, as the provider would know nonce.
  let originalFlow;
  const wrappedFetch = async (url, init) => {
    if (init?.method === "POST") jar.set("butler_oidc_flow", originalFlow);
    const result = await fetchMock(url, init);
    if (init?.method === "POST") jar.delete("butler_oidc_flow");
    return result;
  };
  const module = { exports: {} };
  new Function("require", "module", "exports", "fetch", compiled)((name) => {
    if (!(name in modules)) throw new Error(`Unexpected module ${name}`);
    return modules[name];
  }, module, module.exports, wrappedFetch);
  const api = module.exports;
  const authorization = await api.startLogin();
  originalFlow = jar.get("butler_oidc_flow");
  const callback = new URL("https://butler.example/auth/callback");
  callback.search = new URLSearchParams({ code: "one-time-code", state: authorization.searchParams.get("state") });
  return { api, jar, provisions, sessions, authorization, callback, exchange: () => exchange, originalFlow };
}

test("authorization code flow uses state, nonce, PKCE and verified subject provisioning", async () => {
  const f = await fixture();
  assert.equal(f.authorization.searchParams.get("code_challenge_method"), "S256");
  const { payload } = await jose.jwtVerify(f.originalFlow, new TextEncoder().encode(signingSecret));
  assert.equal(f.authorization.searchParams.get("code_challenge"), createHash("sha256").update(payload.verifier).digest("base64url"));
  assert.equal(await f.api.finishLogin(f.callback), "https://butler.example");
  assert.equal(f.exchange().body.get("code_verifier"), payload.verifier);
  assert.deepEqual(f.provisions[0].body, { issuer: "https://issuer.example", subject: "subject-123", name: "Test User" });
  assert.equal(f.sessions.length, 1);
  assert.equal(f.jar.has("butler_oidc_flow"), false);
  await assert.rejects(() => f.api.finishLogin(f.callback));
});

for (const [name, overrides] of Object.entries({ nonce: { nonce: "wrong" }, issuer: { issuer: "https://wrong.example" }, audience: { audience: "other-client" }, signature: { invalidSignature: true } })) {
  test(`rejects invalid ${name} before creating an account or session`, async () => {
    const f = await fixture(overrides);
    await assert.rejects(() => f.api.finishLogin(f.callback));
    assert.equal(f.provisions.length, 0);
    assert.equal(f.sessions.length, 0);
  });
}

test("rejects wrong state and discovery issuer", async () => {
  const f = await fixture();
  f.callback.searchParams.set("state", "wrong-state");
  await assert.rejects(() => f.api.finishLogin(f.callback));
  assert.equal(f.provisions.length, 0);
  await assert.rejects(() => fixture({ discoveryIssuer: "https://wrong.example" }));
});
