import { timingSafeEqual } from "node:crypto";

function isLocalDevelopmentRequest(request: Request) {
  if (process.env.NODE_ENV !== "development") return false;
  const hostname = new URL(request.url).hostname;
  return hostname === "localhost" || hostname === "127.0.0.1";
}

export function adminAccessConfigured(request: Request) {
  return (
    isLocalDevelopmentRequest(request) ||
    Boolean(process.env.PUSH_ANALYTICS_ADMIN_KEY)
  );
}

export function isAdminRequest(request: Request) {
  if (isLocalDevelopmentRequest(request)) return true;

  const configuredKey =
    process.env.PUSH_ANALYTICS_ADMIN_KEY ?? "";
  const providedKey = request.headers.get("x-push-admin-key") ?? "";

  if (!configuredKey || !providedKey) return false;

  const expected = Buffer.from(configuredKey);
  const actual = Buffer.from(providedKey);
  return (
    expected.length === actual.length &&
    timingSafeEqual(expected, actual)
  );
}
