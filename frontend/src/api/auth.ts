import apiClient from "./client";

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
    if (typeof record.message === "string" && record.message) {
      return record.message;
    }
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
      throw new Error("登录 code 已使用、过期或无效，请重新登录");
    }
    if (response.status === 403) {
      throw new Error("账号缺少 auto_wechat:use 权限，无法进入系统");
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
