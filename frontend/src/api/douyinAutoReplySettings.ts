import apiClient from "./client";
import type {
  DouyinAutoReplySettingItem,
  DouyinAutoReplySettingResponse,
  DouyinAutoReplySettingsListResponse,
  DouyinAutoReplySettingUpdateRequest,
} from "./types";

type ApiResponse<T> = {
  success?: boolean;
  data: T;
  message?: string;
};

function safeArray(value: string[] | null | undefined): string[] {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
}

function buildUpdatePayload(
  payload: DouyinAutoReplySettingUpdateRequest,
): DouyinAutoReplySettingUpdateRequest {
  return {
    enabled: Boolean(payload.enabled),
    dry_run_enabled: Boolean(payload.dry_run_enabled),
    send_enabled: Boolean(payload.send_enabled),
    min_confidence: Number(payload.min_confidence),
    require_rag: Boolean(payload.require_rag),
    require_rag_sources: Boolean(payload.require_rag_sources),
    allowed_intents: safeArray(payload.allowed_intents),
    blocked_risk_flags: safeArray(payload.blocked_risk_flags),
    max_replies_per_conversation_per_hour: Number(payload.max_replies_per_conversation_per_hour),
    max_replies_per_account_per_hour: Number(payload.max_replies_per_account_per_hour),
  };
}

export async function getDouyinAutoReplySettings(): Promise<DouyinAutoReplySettingItem[]> {
  const response = (await apiClient.get(
    "/douyin-autoreply/settings",
  )) as unknown as DouyinAutoReplySettingsListResponse;
  return response.data?.items || [];
}

export async function getDouyinAutoReplySetting(
  accountOpenId: string,
): Promise<DouyinAutoReplySettingItem> {
  const response = (await apiClient.get(
    `/douyin-autoreply/settings/${encodeURIComponent(accountOpenId)}`,
  )) as unknown as DouyinAutoReplySettingResponse;
  return response.data;
}

export async function updateDouyinAutoReplySetting(
  accountOpenId: string,
  payload: DouyinAutoReplySettingUpdateRequest,
): Promise<DouyinAutoReplySettingItem> {
  const response = (await apiClient.put(
    `/douyin-autoreply/settings/${encodeURIComponent(accountOpenId)}`,
    buildUpdatePayload(payload),
  )) as unknown as ApiResponse<DouyinAutoReplySettingItem>;
  return response.data;
}
