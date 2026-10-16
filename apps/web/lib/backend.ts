import "server-only";

const origin = process.env.BUTLER_API || "http://127.0.0.1:8000";

export function backend(path: string, init?: RequestInit, identity?: string) {
  const headers = new Headers(init?.headers);
  if (process.env.BUTLER_INTERNAL_TOKEN) headers.set("authorization", `Bearer ${process.env.BUTLER_INTERNAL_TOKEN}`);
  if (identity) headers.set("x-butler-identity", identity);
  return fetch(`${origin}${path}`, { ...init, headers, cache: "no-store", signal: AbortSignal.timeout(path === "/workspace/ask" || path === "/workspace/lab/compare" ? 180000 : 15000) });
}
