import "server-only";

export const enterprise = process.env.BUTLER_MODE === "enterprise";
export const localLogin = (process.env.BUTLER_AUTH_MODE || "local") === "local";
export function missingLoginConfiguration() {
  return ["BUTLER_PUBLIC_URL", "BUTLER_SESSION_SECRET", "BUTLER_INTERNAL_TOKEN", ...(!localLogin ? ["BUTLER_OIDC_ISSUER", "BUTLER_OIDC_CLIENT_ID", "BUTLER_OIDC_CLIENT_SECRET"] : [])]
    .filter((key) => !process.env[key] || (["BUTLER_SESSION_SECRET", "BUTLER_INTERNAL_TOKEN"].includes(key) && process.env[key]!.length < 32));
}

export function sessionSecret(): string {
  const value = process.env.BUTLER_SESSION_SECRET;
  if (enterprise && (!value || value.length < 32)) throw new Error("BUTLER_SESSION_SECRET must have 32+ characters");
  return value || "";
}
