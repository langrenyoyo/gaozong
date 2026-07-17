import { clearExternalToken } from "./authToken";

export const NEWCAR_LOGIN_URL = import.meta.env.VITE_NEWCAR_LOGIN_URL as string | undefined;
export const DEFAULT_POST_LOGIN_PATH = "/";
export const NEWCAR_REDIRECT_PATH_KEY = "newcar_redirect_path";
export const NEWCAR_REDIRECT_PATH_SAVED_AT_KEY = "newcar_redirect_path_saved_at";
export const NEWCAR_REDIRECT_PATH_TTL_MS = 10 * 60 * 1000;

const NEWCAR_REDIRECTING_KEY = "newcar_redirecting";
const NEWCAR_REDIRECTING_TTL_MS = 5000;
const NEWCAR_AUTH_REDIRECTING_EVENT = "newcar-auth-redirecting";
const DEFAULT_REDIRECT_DELAY_MS = 600;
const DEFAULT_REDIRECT_MESSAGE = "正在前往统一登录，请稍候…";

const ALLOWED_REDIRECT_PATH_PREFIXES = [
  "/admin/autoreply-rollout",
  "/admin/return-visits",
  "/admin/ai-reply-records",
  "/admin/compute-config",
  "/douyin-cs",
  "/leads",
  "/compute",
  "/agents",
  "/wechat-assistant",
];

interface RedirectToNewCarLoginOptions {
  message?: string;
  delayMs?: number;
  saveCurrentPath?: boolean;
}

function currentPath(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function isHandlingNewCarCode(): boolean {
  const url = new URL(window.location.href);
  return Boolean(url.searchParams.get("code")) && url.searchParams.get("source") === "new_car_project";
}

function isAllowedRedirectPath(path: string | null): path is string {
  if (!path?.trim() || !path.startsWith("/") || path.startsWith("//")) {
    return false;
  }

  let url: URL;
  try {
    url = new URL(path, window.location.origin);
  } catch {
    return false;
  }

  if (url.origin !== window.location.origin || url.pathname === "/login" || url.pathname === "/auth/callback") {
    return false;
  }

  return ALLOWED_REDIRECT_PATH_PREFIXES.some((prefix) => url.pathname === prefix || url.pathname.startsWith(`${prefix}/`));
}

function clearSavedRedirectPath(): void {
  sessionStorage.removeItem(NEWCAR_REDIRECT_PATH_KEY);
  sessionStorage.removeItem(NEWCAR_REDIRECT_PATH_SAVED_AT_KEY);
}

export function clearNewCarRedirectState(): void {
  clearSavedRedirectPath();
  sessionStorage.removeItem(NEWCAR_REDIRECTING_KEY);
}

function resolveSavedRedirectPath(): string | null {
  const savedPath = sessionStorage.getItem(NEWCAR_REDIRECT_PATH_KEY);
  const savedAt = sessionStorage.getItem(NEWCAR_REDIRECT_PATH_SAVED_AT_KEY);
  const savedAgeMs = Date.now() - Number(savedAt);

  if (!savedPath) {
    return null;
  }

  if (!savedAt || !Number.isFinite(savedAgeMs) || savedAgeMs < 0 || savedAgeMs > NEWCAR_REDIRECT_PATH_TTL_MS) {
    console.warn("NewCar redirect path expired, fallback to permission-based default page.");
    clearSavedRedirectPath();
    return null;
  }

  if (!isAllowedRedirectPath(savedPath)) {
    console.warn("NewCar redirect path rejected by allowlist, fallback to permission-based default page.");
    clearSavedRedirectPath();
    return null;
  }

  return savedPath;
}

function emitRedirectNotice(message: string): void {
  window.dispatchEvent(new CustomEvent(NEWCAR_AUTH_REDIRECTING_EVENT, { detail: message }));
}

export function addNewCarRedirectNoticeListener(listener: (message: string) => void): () => void {
  const handler = (event: Event) => listener((event as CustomEvent<string>).detail || DEFAULT_REDIRECT_MESSAGE);
  window.addEventListener(NEWCAR_AUTH_REDIRECTING_EVENT, handler);
  return () => window.removeEventListener(NEWCAR_AUTH_REDIRECTING_EVENT, handler);
}

export function redirectToNewCarLogin(options: RedirectToNewCarLoginOptions = {}): boolean {
  if (!NEWCAR_LOGIN_URL || isHandlingNewCarCode()) {
    return false;
  }

  const redirectingAt = sessionStorage.getItem(NEWCAR_REDIRECTING_KEY);
  const redirectingAgeMs = Date.now() - Number(redirectingAt);
  if (redirectingAt && Number.isFinite(redirectingAgeMs) && redirectingAgeMs >= 0 && redirectingAgeMs < NEWCAR_REDIRECTING_TTL_MS) {
    return false;
  }

  const loginUrl = new URL(NEWCAR_LOGIN_URL);
  const now = Date.now().toString();
  if (options.saveCurrentPath !== false) {
    sessionStorage.setItem(NEWCAR_REDIRECT_PATH_KEY, currentPath());
    sessionStorage.setItem(NEWCAR_REDIRECT_PATH_SAVED_AT_KEY, now);
  }
  sessionStorage.setItem(NEWCAR_REDIRECTING_KEY, now);
  clearExternalToken();
  emitRedirectNotice(options.message || DEFAULT_REDIRECT_MESSAGE);
  window.setTimeout(() => {
    window.location.replace(loginUrl.toString());
  }, options.delayMs ?? DEFAULT_REDIRECT_DELAY_MS);
  return true;
}

export function consumeSavedRedirectPathAfterLogin(): string | null {
  sessionStorage.removeItem(NEWCAR_REDIRECTING_KEY);
  const targetPath = resolveSavedRedirectPath();
  clearSavedRedirectPath();
  return targetPath;
}
