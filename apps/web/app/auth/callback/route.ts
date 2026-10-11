import { finishLogin } from "@/lib/oidc";
import { localLogin } from "@/lib/deployment";

export async function GET(request: Request) {
  if (localLogin) return Response.redirect(new URL("/login", process.env.BUTLER_PUBLIC_URL || request.url));
  try { return Response.redirect(new URL("/workspace/overview", await finishLogin(new URL(request.url)))); }
  catch { return Response.redirect(new URL("/login?error=signin", process.env.BUTLER_PUBLIC_URL || request.url)); }
}
