import { clearExternalToken } from "./authToken";

export const NEWCAR_LOGIN_URL = import.meta.env.VITE_NEWCAR_LOGIN_URL as string | undefined;
export const NEWCAR_REDIRECT_PATH_KEY = "newcar_redirect_path";

const NEWCAR_REDIRECTING_KEY = "newcar_redirecting";
const NEWCAR_REDIRECTING_TTL_MS = 5000;

function currentPath(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function isHandlingNewCarCode(): boolean {
  const url = new URL(window.location.href);
  return Boolean(url.searchParams.get("code")) && url.searchParams.get("source") === "new_car_project";
}

export function redirectToNewCarLogin(): boolean {
  if (!NEWCAR_LOGIN_URL || isHandlingNewCarCode()) {
    return false;
  }

  const redirectingAt = sessionStorage.getItem(NEWCAR_REDIRECTING_KEY);
  const redirectingAgeMs = Date.now() - Number(redirectingAt);
  if (redirectingAt && Number.isFinite(redirectingAgeMs) && redirectingAgeMs >= 0 && redirectingAgeMs < NEWCAR_REDIRECTING_TTL_MS) {
    return false;
  }

  const loginUrl = new URL(NEWCAR_LOGIN_URL);
  sessionStorage.setItem(NEWCAR_REDIRECT_PATH_KEY, currentPath());
  sessionStorage.setItem(NEWCAR_REDIRECTING_KEY, Date.now().toString());
  clearExternalToken();
  window.location.replace(loginUrl.toString());
  return true;
}

export function restoreSavedRedirectPathAfterLogin(): void {
  sessionStorage.removeItem(NEWCAR_REDIRECTING_KEY);

  const savedPath = sessionStorage.getItem(NEWCAR_REDIRECT_PATH_KEY);
  sessionStorage.removeItem(NEWCAR_REDIRECT_PATH_KEY);
  if (!savedPath || savedPath === currentPath()) {
    return;
  }

  window.history.replaceState({}, "", savedPath);
}
