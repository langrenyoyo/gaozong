/**
 * Douyin on-site live-check API.
 *
 * Read-only/observe-only endpoints:
 *   GET /integrations/douyin/live-check/auth-url
 *   GET /integrations/douyin/live-check/status
 *   GET /integrations/douyin/live-check/accounts
 */

import apiClient from "./client";
import type {
  DouyinLiveCheckAccountsResponse,
  DouyinLiveCheckAuthUrlResponse,
  DouyinLiveCheckStatusResponse,
} from "./types";

export async function fetchDouyinLiveCheckAuthUrl(): Promise<DouyinLiveCheckAuthUrlResponse> {
  return apiClient.get("/integrations/douyin/live-check/auth-url");
}

export async function fetchDouyinLiveCheckStatus(state?: string): Promise<DouyinLiveCheckStatusResponse> {
  return apiClient.get("/integrations/douyin/live-check/status", {
    params: state ? { state } : undefined,
  });
}

export async function fetchDouyinLiveCheckAccounts(): Promise<DouyinLiveCheckAccountsResponse> {
  return apiClient.get("/integrations/douyin/live-check/accounts");
}

export interface BindAuthorizedOpenIdResult {
  action: string;
  account_open_id: string;
  merchant_id: string;
  bind_status: number;
  account_name: string | null;
  avatar_url: string | null;
  updated_at: string | null;
}

/**
 * 把授权成功的抖音号绑定到当前登录商户。
 *
 * merchant_id 由后端 RequestContext 提供，前端只传 open_id，不传 merchant_id。
 */
export async function bindAuthorizedOpenId(openId: string): Promise<{
  success: boolean;
  data: BindAuthorizedOpenIdResult;
  message: string;
}> {
  return apiClient.post("/integrations/douyin/live-check/accounts/bind-authorized-open-id", {
    open_id: openId,
  });
}
