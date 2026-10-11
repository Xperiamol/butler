import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import * as crypto from "node:crypto";
import ts from "typescript";

const compiled = ts.transpileModule(await readFile(new URL("../lib/session.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function fixture() {
  let cookie, fresh = { id: "local-user", name: "User", role: "employee", groups: [], session_version: 1 }, available = true;
  const module = { exports: {} }, modules = {
    "server-only": {}, "node:crypto": crypto, react: { cache: (fn) => fn },
    "next/headers": { cookies: async () => ({ get: () => cookie ? { value: cookie } : undefined, set: (_key, value) => { cookie = value; }, delete: () => { cookie = undefined; } }) },
    "next/navigation": { redirect: () => { throw new Error("redirect"); } },
    "./deployment": { enterprise: true, localLogin: true, sessionSecret: () => "test-secret-32-characters-long-for-session" },
    "./backend": { backend: async () => available ? Response.json(fresh) : new Response(null, { status: 401 }) },
  };
  new Function("require", "module", "exports", compiled)((key) => modules[key], module, module.exports);
  return { api: module.exports, user: fresh, update: (value) => { fresh = { ...fresh, ...value }; }, disable: () => { available = false; }, tamper: () => { cookie += "x"; } };
}

test("password reset invalidates signed sessions; new login sees current roles", async () => {
  const f = fixture();
  await f.api.createSession(f.user);
  assert.equal((await f.api.readSession()).id, f.user.id);
  f.update({ role: "auditor" });
  assert.equal((await f.api.readSession()).role, "auditor");
  f.update({ session_version: 2 });
  assert.equal(await f.api.readSession(), null);
  await f.api.createSession({ ...f.user, session_version: 2 });
  assert.equal((await f.api.readSession()).session_version, 2);
  f.disable();
  assert.equal(await f.api.readSession(), null);
});

test("session signature tampering is rejected", async () => {
  const f = fixture(); await f.api.createSession(f.user); f.tamper();
  assert.equal(await f.api.readSession(), null);
});
