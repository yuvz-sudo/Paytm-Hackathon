export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : detail?.error || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
  get code(): string | null { return typeof this.detail === "object" ? this.detail?.error ?? null : null; }
  get consentScope(): string | null {
    return this.status === 403 && this.detail?.error === "consent_off" ? this.detail.scope : null;
  }
}

// ---- credentials: a real login session (token) or the demo-merchant switcher (header, dev only)
let token: string | null = localStorage.getItem("token");
let demoId: number | null = localStorage.getItem("demoId") ? Number(localStorage.getItem("demoId")) : null;
export const hasCredentials = () => !!token || demoId !== null;
export const isDemoMode = () => !token && demoId !== null;
export const getMerchantId = () => demoId ?? 0;
export function setToken(t: string) { token = t; demoId = null; localStorage.setItem("token", t); localStorage.removeItem("demoId"); }
export function setDemo(id: number) { token = null; demoId = id; localStorage.removeItem("token"); localStorage.setItem("demoId", String(id)); }
export function clearAuth() { token = null; demoId = null; localStorage.removeItem("token"); localStorage.removeItem("demoId"); localStorage.removeItem("tab"); }
export const setMerchantId = setDemo;

// App listens so any 401 / unfinished sign-up routes the user to the right screen
export const authEvents = new EventTarget();

export function authHeaders(): Record<string, string> {
  if (token) return { Authorization: `Bearer ${token}` };
  if (demoId !== null) return { "X-Merchant-Id": String(demoId) };
  return {};
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  else if (demoId !== null) headers["X-Merchant-Id"] = String(demoId);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method: opts.method || "GET", headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new ApiError(res.status, data.detail ?? data);
    if (res.status === 401 && !path.startsWith("/auth/")) authEvents.dispatchEvent(new Event("unauthorized"));
    if (res.status === 403 && err.code === "onboarding_required") authEvents.dispatchEvent(new Event("onboarding"));
    throw err;
  }
  return data as T;
}

export const inr = (n: number | null | undefined) =>
  n == null ? "—" : "₹" + Math.round(n).toLocaleString("en-IN");
