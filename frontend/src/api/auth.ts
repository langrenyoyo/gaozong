import apiClient, { API_BASE_URL } from "./client";
import { getExternalToken } from "../authToken";

export const NEWCAR_AUTH_BASE_URL =
  import.meta.env.VITE_NEWCAR_AUTH_BASE_URL || (import.meta.env.DEV ? "http://192.168.110.19:8790" : undefined);

export interface PermissionItem {
  code: string;
  name?: string;
  module?: string;
}

export interface AuthContextData {
  token?: string;
  user_id?: string;
  username?: string | null;
  display_name?: string | null;
  merchant_id?: string | null;
  merchant_ids?: string[];
  role_codes?: string[];
  permission_codes?: string[];
  permissions?: string[];
  permission_items?: PermissionItem[];
  super_admin?: boolean;
  source_system?: string;
  auth_mode?: string;
}

interface ApiResponse<T> {
  success?: boolean;
  data: T;
  message?: string;
}

function authErrorMessage(error: unknown): string {
  const response = (error as { response?: { data?: unknown; status?: number } })?.response;
  const data = response?.data as { detail?: unknown } | undefined;
  const detail = data?.detail;
  if (detail && typeof detail === "object") {
    const record = detail as { code?: unknown; message?: unknown };
    if (record.code === "EXTERNAL_MERCHANT_NOT_BOUND") {
      return "账号未绑定商户，请联系管理员。";
    }
    if (record.code === "PERMISSION_DENIED") {
      return "当前账号暂无访问该功能权限，请联系管理员开通。";
    }
    if (typeof record.message === "string" && record.message) {
      return record.message;
    }
  }
  if (response?.status === 403) {
    return "当前账号暂无访问该功能权限，请联系管理员开通。";
  }
  if (response?.status === 401) {
    return "登录已过期，请重新登录";
  }
  return "外部登录失败，请重新登录";
}

export async function exchangeExternalCode(code: string): Promise<AuthContextData> {
  if (!NEWCAR_AUTH_BASE_URL) {
    throw new Error("未配置 NewCarProject 登录服务地址，请联系管理员");
  }

  const response = await fetch(`${NEWCAR_AUTH_BASE_URL}/api/external-auth/exchange-code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code,
      platform: "auto_wechat",
      device_name: navigator.userAgent.slice(0, 80),
    }),
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error("登录凭证已失效，请重新登录。");
    }
    if (response.status === 403) {
      throw new Error("当前账号暂无访问该功能权限，请联系管理员开通。");
    }
    throw new Error("外部登录失败，请重新登录");
  }

  return (await response.json()) as AuthContextData;
}

export async function fetchCurrentAuthUser(): Promise<AuthContextData> {
  try {
    const response = await apiClient.get<unknown, ApiResponse<AuthContextData>>("/auth/me");
    return response.data;
  } catch (error) {
    throw new Error(authErrorMessage(error));
  }
}

export async function fetchCurrentAuthUserWithoutRedirect(): Promise<AuthContextData | null> {
  const baseUrl = API_BASE_URL || "";
  const headers: Record<string, string> = {};
  const token = getExternalToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  try {
    const response = await fetch(`${baseUrl}/auth/me`, { headers });
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as ApiResponse<AuthContextData>;
    return payload.data || null;
  } catch {
    return null;
  }
}
