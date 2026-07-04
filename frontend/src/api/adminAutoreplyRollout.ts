import apiClient from "./client";

export interface AdminRolloutSummary {
  env_fuse: {
    auto_reply_env_enabled: boolean;
    real_send_env_enabled: boolean;
    allow_full_rollout_env: boolean;
    env_account_whitelist_configured: boolean;
    env_customer_whitelist_configured: boolean;
    env_conversation_whitelist_configured: boolean;
  };
  db_config: {
    scope: string;
    merchant_id?: string | null;
    auto_reply_enabled: boolean;
    real_send_enabled: boolean;
    allow_full_rollout: boolean;
    config_exists: boolean;
  };
  counts: {
    account_whitelist_count: number;
    customer_whitelist_count: number;
    conversation_whitelist_count: number;
    enabled_account_count: number;
    send_enabled_account_count: number;
  };
  recent_stats: {
    dry_run_count: number;
    real_send_candidate_count: number;
    sent_count: number;
    blocked_count: number;
  };
  safety: {
    real_send_effectively_possible: boolean;
    reason_if_not_possible?: string | null;
  };
}

export interface AdminRolloutAccount {
  merchant_id: string;
  account_open_id?: string;
  account_open_id_masked?: string | null;
  account_name?: string | null;
  enabled: boolean;
  send_enabled: boolean;
  bound_agent_id?: string | null;
  bound_agent_name?: string | null;
  db_account_whitelist_hit: boolean;
  today_dry_run_count: number;
  today_sent_count: number;
  today_blocked_count: number;
  last_blocked_reason?: string | null;
  updated_at?: string | null;
}

export interface AdminWhitelistEntry {
  id: number;
  entry_type: "account" | "customer" | "conversation";
  merchant_id: string;
  account_open_id_masked?: string | null;
  value_masked?: string | null;
  enabled: boolean;
  reason?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  disabled_by?: string | null;
  disabled_at?: string | null;
}

export interface AdminAutoreplyRun {
  run_id: number;
  merchant_id?: string | null;
  account_open_id_masked?: string | null;
  conversation_short_id_masked?: string | null;
  customer_open_id_masked?: string | null;
  mode?: string | null;
  status?: string | null;
  final_auto_send?: boolean | null;
  send_gate_passed?: boolean | null;
  blocked_reason?: string | null;
  fallback_reason?: string | null;
  rag_used: boolean;
  rag_sources_count: number;
  db_rollout?: Record<string, unknown>;
  env_rollout?: Record<string, unknown>;
  created_at?: string | null;
  latest_message_summary?: string | null;
  would_send_content_summary?: string | null;
}

export interface AdminRolloutGlobalUpdateRequest {
  auto_reply_enabled: boolean;
  real_send_enabled: boolean;
  allow_full_rollout: boolean;
  reason: string;
}

export interface AdminRolloutAccountUpdateRequest {
  enabled?: boolean;
  send_enabled?: boolean;
  reason: string;
}

export interface AdminWhitelistCreateRequest {
  entry_type: "account" | "customer" | "conversation";
  merchant_id: string;
  account_open_id?: string;
  value: string;
  reason: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  message: string;
}

interface ListResponse<T> {
  total: number;
  items: T[];
}

export interface AdminRunsQuery {
  page?: number;
  page_size?: number;
  merchant_id?: string;
  account_open_id?: string;
  mode?: string;
  status?: string;
  blocked_reason?: string;
}

export async function getAutoreplyRolloutSummary(): Promise<ApiResponse<AdminRolloutSummary>> {
  return apiClient.get("/admin/autoreply/rollout/summary");
}

export async function updateAutoreplyRolloutGlobal(
  payload: AdminRolloutGlobalUpdateRequest,
): Promise<ApiResponse<AdminRolloutSummary>> {
  return apiClient.post("/admin/autoreply/rollout/global", payload);
}

export async function listAutoreplyRolloutAccounts(): Promise<ApiResponse<ListResponse<AdminRolloutAccount>>> {
  return apiClient.get("/admin/autoreply/rollout/accounts");
}

export async function updateAutoreplyRolloutAccount(
  accountOpenId: string,
  payload: AdminRolloutAccountUpdateRequest,
): Promise<ApiResponse<AdminRolloutAccount>> {
  return apiClient.post(`/admin/autoreply/rollout/accounts/${encodeURIComponent(accountOpenId)}`, payload);
}

export async function listAutoreplyWhitelist(): Promise<ApiResponse<ListResponse<AdminWhitelistEntry>>> {
  return apiClient.get("/admin/autoreply/rollout/whitelist");
}

export async function addAutoreplyWhitelist(
  payload: AdminWhitelistCreateRequest,
): Promise<ApiResponse<AdminWhitelistEntry>> {
  return apiClient.post("/admin/autoreply/rollout/whitelist", payload);
}

export async function deleteAutoreplyWhitelist(
  entryId: number,
  reason: string,
): Promise<ApiResponse<AdminWhitelistEntry>> {
  return apiClient.delete(`/admin/autoreply/rollout/whitelist/${entryId}`, { params: { reason } });
}

export async function listAutoreplyRuns(
  params: AdminRunsQuery = {},
): Promise<ApiResponse<{ page: number; page_size: number; total: number; items: AdminAutoreplyRun[] }>> {
  return apiClient.get("/admin/autoreply/runs", { params });
}
