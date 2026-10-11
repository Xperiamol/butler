import { startLogin } from "@/lib/oidc";
import { localLogin } from "@/lib/deployment";

export async function GET(request: Request) {
  if (localLogin) return Response.redirect(new URL("/login", process.env.BUTLER_PUBLIC_URL || request.url));
  try { return Response.redirect(await startLogin()); }
  catch { return Response.redirect(new URL("/login?error=configuration", process.env.BUTLER_PUBLIC_URL || request.url)); }
}
