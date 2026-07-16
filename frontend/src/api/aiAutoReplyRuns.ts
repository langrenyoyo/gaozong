import apiClient from "./client";
import type {
  AiAutoReplyRunDetail,
  AiAutoReplyRunDetailResponse,
  AiAutoReplyRunListData,
  AiAutoReplyRunListResponse,
  AiAutoReplyRunQueryParams,
} from "./types";

function appendString(params: URLSearchParams, key: string, value?: string | number | null) {
  if (value === undefined || value === null) return;
  const text = String(value).trim();
  if (text) params.set(key, text);
}

function buildRunQueryParams(query: AiAutoReplyRunQueryParams = {}): URLSearchParams {
  const params = new URLSearchParams();
  appendString(params, "page", query.page);
  appendString(params, "page_size", query.page_size);
  appendString(params, "account_open_id", query.account_open_id);
  appendString(params, "conversation_short_id", query.conversation_short_id);
  appendString(params, "customer_open_id", query.customer_open_id);
  appendString(params, "agent_id", query.agent_id);
  appendString(params, "account_name", query.account_name);
  appendString(params, "customer_name", query.customer_name);
  appendString(params, "agent_name", query.agent_name);
  appendString(params, "status", query.status);
  appendString(params, "created_from", query.created_from);
  appendString(params, "created_to", query.created_to);
  appendString(params, "keyword", query.keyword);
  return params;
}

export async function getAiAutoReplyRuns(
  query: AiAutoReplyRunQueryParams = {},
): Promise<AiAutoReplyRunListData> {
  const params = buildRunQueryParams(query);
  const response = (await apiClient.get("/ai-auto-reply-runs", {
    params,
  })) as unknown as AiAutoReplyRunListResponse;
  return response.data;
}

export async function getAiAutoReplyRunDetail(runId: number | string): Promise<AiAutoReplyRunDetail> {
  const response = (await apiClient.get(
    `/ai-auto-reply-runs/${encodeURIComponent(String(runId))}`,
  )) as unknown as AiAutoReplyRunDetailResponse;
  return response.data;
}
