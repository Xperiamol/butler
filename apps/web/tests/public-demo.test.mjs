import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

async function load(path, modules, fetchMock) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", "fetch", code)((key) => {
    if (!(key in modules)) throw new Error(`Unexpected module ${key}`);
    return modules[key];
  }, module, module.exports, fetchMock);
  return module.exports;
}

test("enterprise public demo has no fallback to the corporate API", async () => {
  process.env.BUTLER_API = "https://corporate-api.example";
  delete process.env.BUTLER_DEMO_API;
  let calls = 0;
  const demo = await load("../lib/public-demo.ts", { "server-only": {}, "./deployment": { enterprise: true } }, async () => { calls++; });
  assert.equal(demo.publicDemoEnabled, false);
  assert.equal((await demo.publicDemo("/eval")).status, 503);
  assert.equal(calls, 0);
});

test("enterprise demonstration only calls the isolated endpoint without enterprise credentials", async () => {
  process.env.BUTLER_API = "https://corporate-api.example";
  process.env.BUTLER_DEMO_API = "https://demo-api.example";
  process.env.BUTLER_INTERNAL_TOKEN = "must-not-be-forwarded";
  const calls = [];
  const demo = await load("../lib/public-demo.ts", { "server-only": {}, "./deployment": { enterprise: true } }, async (url, init) => { calls.push({ url, init }); return Response.json({ data_source: "fake" }); });
  const response = await demo.publicDemo("/eval");
  assert.equal(response.status, 200);
  assert.equal(calls[0].url, "https://demo-api.example/eval");
  assert.equal(new Headers(calls[0].init.headers).has("authorization"), false);
  assert.equal(new Headers(calls[0].init.headers).has("cookie"), false);
  assert.equal(new Headers(calls[0].init.headers).has("x-butler-identity"), false);
});

test("public compare validates demo identities and strips extra fields", async () => {
  const calls = [];
  const route = await load("../app/api/compare/route.ts", { "@/lib/public-demo": { publicDemo: async (path, init) => { calls.push(JSON.parse(init.body)); return Response.json({ ok: true }); } } });
  const post = (body) => route.POST(new Request("https://butler.example/api/compare", { method: "POST", body: JSON.stringify(body) }));
  assert.equal((await post({ identity_id: "enterprise-admin", question: "test" })).status, 400);
  assert.equal((await post({ identity_id: "ken", question: "test", session_id: "a".repeat(129) })).status, 400);
  assert.equal((await post({ identity_id: "ken", question: "test", corporate_secret: "never-forward" })).status, 200);
  assert.deepEqual(calls, [{ identity_id: "ken", question: "test" }]);
});
