import apiClient from "./client";

export interface AiReplyDecisionLogListItem {
  id: number;
  merchant_id: string;
  account_open_id?: string | null;
  conversation_id?: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  latest_message_summary?: string | null;
  reply_text_summary?: string | null;
  intent?: string | null;
  lead_level?: string | null;
  confidence?: number | null;
  manual_required: boolean;
  manual_required_reason?: string | null;
  risk_flags?: string[] | null;
  tags?: string[] | null;
  rag_used: boolean;
  llm_used: boolean;
  upstream_auto_send: boolean;
  final_auto_send: boolean;
  decision_version?: string | null;
  // Phase 4：发送流水字段，列表展示违禁词替换后的实发内容摘要与发送状态
  send_record_id?: number | null;
  sent_content_summary?: string | null;
  send_status?: string | null;
  send_source?: string | null;
  auto_send?: boolean;
  manual_confirmed?: boolean;
  upstream_msg_id?: string | null;
  sent_at?: string | null;
  // 发送流水创建时间，用于实发时间回退展示（sent_at 优先，其次本字段，最后 created_at）
  send_created_at?: string | null;
  model?: string | null;
  is_effective?: boolean | null;
  effectiveness_reason?: string | null;
  created_at?: string | null;
}

export interface AiReplyDecisionLogDetail extends AiReplyDecisionLogListItem {
  latest_message?: string | null;
  reply_text?: string | null;
  rag_sources?: AiReplyDecisionSource[] | null;
  source_chunks?: AiReplyDecisionSource[] | null;
  allowed_category_keys?: string[] | null;
  // 详情返回违禁词替换后的最终实发内容（脱敏后完整展示）
  sent_content?: string | null;
}

export interface AiReplyDecisionSource {
  chunk_id?: number | string | null;
  document_id?: number | string | null;
  title?: string | null;
  score?: number | null;
  [key: string]: unknown;
}

export interface AiReplyDecisionLogListData {
  page: number;
  page_size: number;
  total: number;
  items: AiReplyDecisionLogListItem[];
}

export interface AiReplyDecisionLogQueryParams {
  page?: number;
  page_size?: number;
  account_open_id?: string;
  conversation_id?: string;
  agent_id?: string | number;
  manual_required?: boolean | null;
  intent?: string;
  lead_level?: string;
  risk_flag?: string;
  rag_used?: boolean | null;
  llm_used?: boolean | null;
  date_from?: string;
  date_to?: string;
  keyword?: string;
  // Phase 4：超管可按商户筛选；新增发送状态与有效性筛选
  merchant_id?: string;
  send_status?: string;
  is_effective?: boolean | null;
}

// 超管人工标记 AI 实发回复有效性补丁
export interface AiReplyDecisionEffectivenessPatch {
  is_effective?: boolean | null;
  effectiveness_reason?: string | null;
}

interface ApiResponse<T> {
  success?: boolean;
  data: T;
  message?: string;
}

function appendString(params: URLSearchParams, key: string, value?: string | number | null) {
  if (value === undefined || value === null) return;
  const text = String(value).trim();
  if (text) params.set(key, text);
}

function appendBoolean(params: URLSearchParams, key: string, value?: boolean | null) {
  if (typeof value === "boolean") {
    params.set(key, String(value));
  }
}

function buildQueryParams(query: AiReplyDecisionLogQueryParams = {}): URLSearchParams {
  const params = new URLSearchParams();
  appendString(params, "page", query.page);
  appendString(params, "page_size", query.page_size);
  appendString(params, "account_open_id", query.account_open_id);
  appendString(params, "conversation_id", query.conversation_id);
  appendString(params, "agent_id", query.agent_id);
  appendBoolean(params, "manual_required", query.manual_required);
  appendString(params, "intent", query.intent);
  appendString(params, "lead_level", query.lead_level);
  appendString(params, "risk_flag", query.risk_flag);
  appendBoolean(params, "rag_used", query.rag_used);
  appendBoolean(params, "llm_used", query.llm_used);
  appendString(params, "date_from", query.date_from);
  appendString(params, "date_to", query.date_to);
  appendString(params, "keyword", query.keyword);
  appendString(params, "merchant_id", query.merchant_id);
  appendString(params, "send_status", query.send_status);
  appendBoolean(params, "is_effective", query.is_effective);
  return params;
}

export async function getAiReplyDecisionLogs(
  query: AiReplyDecisionLogQueryParams = {},
): Promise<AiReplyDecisionLogListData> {
  const params = buildQueryParams(query);
  const response = (await apiClient.get("/ai-reply-decision-logs", {
    params,
  })) as unknown as ApiResponse<AiReplyDecisionLogListData>;
  return response.data;
}

export async function getAiReplyDecisionLogDetail(id: number | string): Promise<AiReplyDecisionLogDetail> {
  const response = (await apiClient.get(
    `/ai-reply-decision-logs/${encodeURIComponent(String(id))}`,
  )) as unknown as ApiResponse<AiReplyDecisionLogDetail>;
  return response.data;
}

// 超管标记 AI 实发回复有效性，返回更新后的详情
export async function patchAiReplyDecisionLogEffectiveness(
  id: number | string,
  payload: AiReplyDecisionEffectivenessPatch,
): Promise<AiReplyDecisionLogDetail> {
  const response = (await apiClient.patch(
    `/ai-reply-decision-logs/${encodeURIComponent(String(id))}/effectiveness`,
    payload,
  )) as unknown as ApiResponse<AiReplyDecisionLogDetail>;
  return response.data;
}
