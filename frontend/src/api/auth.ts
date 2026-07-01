import apiClient from "./client";

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

export async function exchangeExternalCode(code: string): Promise<AuthContextData> {
  const response = await apiClient.get<unknown, ApiResponse<AuthContextData>>("/auth/callback", {
    params: { code },
  });
  return response.data;
}

export async function fetchCurrentAuthUser(): Promise<AuthContextData> {
  const response = await apiClient.get<unknown, ApiResponse<AuthContextData>>("/auth/me");
  return response.data;
}
