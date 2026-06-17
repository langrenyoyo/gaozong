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

export async function fetchDouyinLiveCheckStatus(): Promise<DouyinLiveCheckStatusResponse> {
  return apiClient.get("/integrations/douyin/live-check/status");
}

export async function fetchDouyinLiveCheckAccounts(): Promise<DouyinLiveCheckAccountsResponse> {
  return apiClient.get("/integrations/douyin/live-check/accounts");
}
