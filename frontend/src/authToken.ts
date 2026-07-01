export const EXTERNAL_TOKEN_KEY = "external_token";

export function getExternalToken(): string | null {
  return sessionStorage.getItem(EXTERNAL_TOKEN_KEY);
}

export function setExternalToken(token: string): void {
  sessionStorage.setItem(EXTERNAL_TOKEN_KEY, token);
}

export function clearExternalToken(): void {
  sessionStorage.removeItem(EXTERNAL_TOKEN_KEY);
}
