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

const SWITCH_TO_NEWCAR_ERROR = "切换到 NewCar 失败，请稍后重试。";
const AUTH_REQUEST_TIMEOUT_MS = 10_000;

export async function switchToInternalSystem(): Promise<string> {
  const token = getExternalToken();
  if (!NEWCAR_AUTH_BASE_URL || !token) {
    throw new Error(SWITCH_TO_NEWCAR_ERROR);
  }

  let response: Response;
  try {
    const baseUrl = NEWCAR_AUTH_BASE_URL.replace(/\/+$/, "");
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    headers.Authorization = `Bearer ${token}`;
    response = await fetch(`${baseUrl}/api/external-auth/switch-to-internal`, {
      method: "POST",
      headers,
      body: JSON.stringify({}),
      signal: AbortSignal.timeout(AUTH_REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new Error(SWITCH_TO_NEWCAR_ERROR);
  }

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error("登录已过期，无法切换到 NewCar。");
    }
    if (response.status === 403) {
      throw new Error("当前账号暂无切换到 NewCar 的权限。");
    }
    throw new Error(SWITCH_TO_NEWCAR_ERROR);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(SWITCH_TO_NEWCAR_ERROR);
  }

  const value =
    payload && typeof payload === "object"
      ? (payload as { redirect_url?: unknown }).redirect_url
      : null;
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(SWITCH_TO_NEWCAR_ERROR);
  }

  let redirectUrl: URL;
  try {
    redirectUrl = new URL(value);
  } catch {
    throw new Error(SWITCH_TO_NEWCAR_ERROR);
  }
  if (redirectUrl.protocol !== "http:" && redirectUrl.protocol !== "https:") {
    throw new Error(SWITCH_TO_NEWCAR_ERROR);
  }
  return redirectUrl.toString();
}

export async function logoutAutoWechat(token: string | null): Promise<void> {
  const baseUrl = (API_BASE_URL || "").replace(/\/+$/, "");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  try {
    const response = await fetch(`${baseUrl}/auth/logout`, {
      method: "POST",
      headers,
      body: JSON.stringify({}),
      signal: AbortSignal.timeout(AUTH_REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error("退出失败，请重试");
    }
  } catch {
    throw new Error("退出失败，请重试");
  }
}

/** 商户改密结果：成功时 relogin_required 提示前端进入重登录状态。 */
export interface ChangeExternalPasswordResult {
  ok: boolean;
  relogin_required?: boolean;
  revoked_session_scope?: string;
}

/**
 * 改密错误类别：
 * - business：400/403 业务失败，保留登录态、恢复 401 跳转、弹窗内重试。
 * - relogin：401 token 已失效，清本地持久状态进入重登录状态页。
 * - unknown：超时、网络、5xx、异常 JSON、2xx 但响应不符成功白名单；清本地持久状态、卸载受保护页、要求重新登录。
 */
export type ChangeExternalPasswordOutcome =
  | { status: "success"; result: ChangeExternalPasswordResult }
  | { status: "business"; code: string; message: string }
  | { status: "relogin"; message: string }
  | { status: "unknown"; message: string };

/** 商户改密代理调用：只发送两个密码字段到 9000 门面，不接受用户 ID，不直连 NewCar，不输出请求体。 */
export async function changeExternalPassword(
  oldPassword: string,
  newPassword: string,
): Promise<ChangeExternalPasswordOutcome> {
  const baseUrl = (API_BASE_URL || "").replace(/\/+$/, "");
  const token = getExternalToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl}/auth/password`, {
      method: "POST",
      headers,
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      signal: AbortSignal.timeout(AUTH_REQUEST_TIMEOUT_MS),
    });
  } catch {
    // 超时/网络中断：结果未知。
    return { status: "unknown", message: "修改密码失败，请重新登录" };
  }

  let payload: unknown = null;
  let jsonParseFailed = false;
  try {
    payload = await response.json();
  } catch {
    jsonParseFailed = true;
  }

  if (response.status === 401) {
    return { status: "relogin", message: "登录已过期，请重新登录" };
  }

  if (response.status === 400 || response.status === 403) {
    const code = readApiErrorCodeFromPayload(payload);
    return { status: "business", code: code || "", message: passwordBusinessMessage(code) };
  }

  // 5xx 或其他非 2xx、或 2xx 但响应异常：结果未知。
  if (!response.ok || jsonParseFailed || typeof payload !== "object" || payload === null) {
    return { status: "unknown", message: "修改密码失败，请重新登录" };
  }

  // 成功必须严格匹配白名单：ok===true && relogin_required===true && revoked_session_scope==="all"。
  const data = payload as Partial<ChangeExternalPasswordResult>;
  const isStrictSuccess =
    data.ok === true && data.relogin_required === true && data.revoked_session_scope === "all";
  if (!isStrictSuccess) {
    // 2xx 但响应不符白名单：结果未知，不当作成功。
    return { status: "unknown", message: "修改密码失败，请重新登录" };
  }

  return { status: "success", result: { ok: true, relogin_required: true, revoked_session_scope: "all" } };
}

function readApiErrorCodeFromPayload(payload: unknown): string | null {
  const detail = (payload as { detail?: { code?: unknown } })?.detail;
  if (detail && typeof detail === "object") {
    const code = (detail as { code?: unknown }).code;
    return typeof code === "string" ? code : null;
  }
  return null;
}

function passwordBusinessMessage(code: string | null): string {
  switch (code) {
    case "OLD_PASSWORD_INVALID":
      return "原密码不正确，请重试";
    case "PASSWORD_TOO_SHORT":
      return "新密码至少 8 位";
    case "PASSWORD_UNCHANGED":
      return "新密码不能与原密码相同";
    case "ACCOUNT_DISABLED":
    case "ACCOUNT_TYPE_NOT_ALLOWED":
    case "PERMISSION_DENIED":
      return "当前账号暂无修改密码权限，请联系管理员。";
    default:
      return "修改密码失败，请重试";
  }
}

/** 管理员当前浏览器退出：浏览器直调 NewCar，携带 Cookie 与 Bearer，返回可信 redirect_url。 */
export async function logoutCurrentBrowserOnNewCar(token: string): Promise<string> {
  if (!NEWCAR_AUTH_BASE_URL || !token) {
    throw new Error("退出失败，请重试");
  }

  let response: Response;
  try {
    const baseUrl = NEWCAR_AUTH_BASE_URL.replace(/\/+$/, "");
    response = await fetch(`${baseUrl}/api/external-auth/logout-current-browser`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({}),
      credentials: "include",
      signal: AbortSignal.timeout(AUTH_REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new Error("退出失败，请重试");
  }

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error("登录已过期，请重新登录");
    }
    throw new Error("退出失败，请重试");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("退出失败，请重试");
  }

  const value =
    payload && typeof payload === "object"
      ? (payload as { redirect_url?: unknown }).redirect_url
      : null;
  if (typeof value !== "string" || !value.trim()) {
    throw new Error("退出失败，请重试");
  }

  let redirectUrl: URL;
  try {
    redirectUrl = new URL(value);
  } catch {
    throw new Error("退出失败，请重试");
  }
  if (redirectUrl.protocol !== "http:" && redirectUrl.protocol !== "https:") {
    throw new Error("退出失败，请重试");
  }
  return redirectUrl.toString();
}
