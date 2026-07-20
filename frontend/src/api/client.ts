/**
 * API 客户端基础配置。
 *
 * 统一管理后端请求的 baseURL、超时、Authorization 注入和响应解包。
 */

import axios from "axios";
import { clearExternalToken, getExternalToken } from "../authToken";
import { redirectToNewCarLogin } from "../newcarRedirect";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_AUTO_WECHAT_API_BASE_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:9000" : undefined);

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
});

let newCarAuthRedirectSuppressed = false;

export function setNewCarAuthRedirectSuppressed(suppressed: boolean): void {
  newCarAuthRedirectSuppressed = suppressed;
}

export function getApiErrorCode(error: unknown): string | null {
  const data = (error as { response?: { data?: unknown } })?.response?.data;
  if (!data || typeof data !== "object") {
    return null;
  }

  const detail = (data as { detail?: unknown }).detail;
  if (detail && typeof detail === "object") {
    const code = (detail as { code?: unknown }).code;
    return typeof code === "string" ? code : null;
  }

  const code = (data as { code?: unknown }).code;
  return typeof code === "string" ? code : null;
}

export function isLocalAgentAuthErrorCode(code: string | null): boolean {
  return Boolean(
    code &&
      (code.startsWith("LOCAL_AGENT_") ||
        [
          "LOCAL_AGENT_TOKEN_MISSING",
          "LOCAL_AGENT_TOKEN_INVALID",
          "LOCAL_AGENT_TOKEN_REQUIRED",
          "LOCAL_AGENT_TOKEN_REVOKED",
        ].includes(code)),
  );
}

function isNonLoginAuthErrorCode(code: string | null): boolean {
  return code === "PERMISSION_DENIED" || code === "EXTERNAL_MERCHANT_NOT_BOUND";
}

function isNewCarLoginAuthErrorCode(code: string | null): boolean {
  return code === "TOKEN_MISSING" || code === "TOKEN_EXPIRED" || code === "TOKEN_INVALID";
}

function shouldRedirectToNewCarLogin(error: unknown): boolean {
  if ((error as { response?: { status?: number } })?.response?.status !== 401) {
    return false;
  }

  const code = getApiErrorCode(error);
  if (isNewCarLoginAuthErrorCode(code)) {
    return true;
  }

  return !isLocalAgentAuthErrorCode(code) && !isNonLoginAuthErrorCode(code);
}

apiClient.interceptors.request.use((config) => {
  const token = getExternalToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (!newCarAuthRedirectSuppressed && shouldRedirectToNewCarLogin(error)) {
      clearExternalToken();
      if (!redirectToNewCarLogin({ message: "登录已过期，正在重新登录…" })) {
        window.dispatchEvent(new Event("external-auth-expired"));
      }
    }
    return Promise.reject(error);
  },
);

export default apiClient;
