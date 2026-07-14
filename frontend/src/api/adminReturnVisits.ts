import apiClient from "./client";

// Phase 9 Task 9：回访配置与运行审计 API client。
// 类型严格对齐后端 Task 8 响应（app/routers/admin_return_visits.py）；
// 禁止 any；JSON 审计字段用 Record<string, unknown>。

export interface ReturnVisitPrompt {
  prompt_key: string;
  name: string;
  scope: string;
  template_text: string;
  fallback_message: string;
  confidence_threshold: number;
  enabled: boolean;
  sort_order: number;
  updated_at?: string | null;
}

export interface ReturnVisitPromptUpdateRequest {
  template_text: string;
  fallback_message: string;
  confidence_threshold: number;
  enabled: boolean;
  reason: string;
}

/** 运行记录列表项：后端不返回 trigger_text / customer_open_id / generated_content / final_content / error_message。 */
export interface ReturnVisitRunListItem {
  run_id: number;
  merchant_id?: string | null;
  lead_id?: number | null;
  staff_id?: number | null;
  prompt_key?: string | null;
  trigger_source?: string | null;
  judgement_source?: string | null;
  judgement_result?: string | null;
  send_status?: string | null;
  send_id?: string | null;
  confidence?: number | null;
  model?: string | null;
  last_failure_stage?: string | null;
  account_open_id_masked?: string | null;
  conversation_short_id_masked?: string | null;
  attempt_count?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** 运行记录详情：列表项 + customer_open_id（掩码）+ 生成/最终话术摘要 + 风险码 + 门禁结果。 */
export interface ReturnVisitRunDetail extends ReturnVisitRunListItem {
  customer_open_id_masked?: string | null;
  generated_content_summary?: string | null;
  final_content_summary?: string | null;
  reply_check_id?: number | null;
  dispatch_notification_id?: number | null;
  risk_flags: string[];
  gate_results: Record<string, unknown>;
  manual_takeover: boolean;
}

export interface ReturnVisitRunsQuery {
  send_status?: string;
  prompt_key?: string;
  judgement_source?: string;
  page?: number;
  page_size?: number;
}

export interface ReturnVisitRunsStats {
  total: number;
  recent_24h: number;
  by_send_status: Record<string, number>;
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

interface PagedListResponse<T> {
  page: number;
  page_size: number;
  total: number;
  items: T[];
}

export async function getReturnVisitPrompts(): Promise<ApiResponse<ListResponse<ReturnVisitPrompt>>> {
  return apiClient.get("/admin/return-visit/prompts");
}

export async function updateReturnVisitPrompt(
  promptKey: string,
  payload: ReturnVisitPromptUpdateRequest,
): Promise<ApiResponse<ReturnVisitPrompt>> {
  return apiClient.put(`/admin/return-visit/prompts/${encodeURIComponent(promptKey)}`, payload);
}

export async function listReturnVisitRuns(
  params: ReturnVisitRunsQuery = {},
): Promise<ApiResponse<PagedListResponse<ReturnVisitRunListItem>>> {
  return apiClient.get("/admin/return-visit/runs", { params });
}

export async function getReturnVisitRunsStats(): Promise<ApiResponse<ReturnVisitRunsStats>> {
  return apiClient.get("/admin/return-visit/runs/stats");
}

export async function getReturnVisitRun(runId: number): Promise<ApiResponse<ReturnVisitRunDetail>> {
  return apiClient.get(`/admin/return-visit/runs/${runId}`);
}
