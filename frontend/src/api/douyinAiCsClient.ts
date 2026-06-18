import axios, { AxiosError } from "axios";
import apiClient from "./client";

export const DOUYIN_AI_CS_API_BASE_URL =
  import.meta.env.VITE_DOUYIN_AI_CS_API_BASE_URL || "http://127.0.0.1:9100";

const douyinAiCsClient = axios.create({
  baseURL: DOUYIN_AI_CS_API_BASE_URL,
  timeout: 10000,
  headers: {
    "Content-Type": "application/json",
  },
});

export interface DouyinAiCsHealthResponse {
  status: string;
  service?: string;
  version?: string;
  port?: number;
}

export interface DouyinAccountItem {
  id: number;
  tenant_id: string;
  account_name: string;
  account_open_id: string;
  status: string;
  avatar?: string | null;
  unread_count?: number;
  last_active_at?: string | null;
  source?: string | null;
  is_authorized?: boolean;
  has_events?: boolean;
}

export interface DouyinAccountListResponse {
  items: DouyinAccountItem[];
}

export interface DouyinAgentItem {
  agent_id: string;
  agent_name: string;
  agent_category: string;
  reply_style: string;
  business_scope: string;
  is_default: boolean;
  is_active: boolean;
}

export interface DouyinAgentListResponse {
  items: DouyinAgentItem[];
  default_agent_id?: string | null;
}

export interface DouyinConversationItem {
  id: string | number;
  account_id: string | number;
  conversation_id?: string | number;
  conversation_key?: string;
  conversation_short_id?: string | null;
  account_open_id?: string;
  open_id: string;
  nickname: string;
  avatar?: string | null;
  last_message: string;
  last_message_at: string;
  unread_count: number;
  lead_status?: string | null;
}

export interface DouyinConversationListResponse {
  items: DouyinConversationItem[];
}

export interface DouyinMessageItem {
  id: string | number;
  conversation_id: string | number;
  conversation_key?: string;
  conversation_short_id?: string | null;
  direction: "inbound" | "outbound" | "system" | string;
  sender_type?: "customer" | "staff" | "system" | string;
  content: string;
  message_type?: string | null;
  media_type?: "image" | "video" | string | null;
  resource_url?: string | null;
  source_url?: string | null;
  downloadable_resource?: boolean;
  resource_missing_reason?: string | null;
  created_at: string;
  raw_event_id?: number;
  server_message_id?: string | null;
}

export interface DouyinMessageListResponse {
  items: DouyinMessageItem[];
}

export interface DouyinUserProfileResponse {
  conversation_id: number;
  budget_min?: number | null;
  budget_max?: number | null;
  brand_preference?: string | null;
  vehicle_preference?: string | null;
  purchase_intent_level: string;
  lead_capture_suggested: boolean;
}

export interface CreateRagDocumentRequest {
  tenant_id: string;
  merchant_id: string;
  douyin_account_id: number;
  title: string;
  content: string;
  source_type?: string;
  category?: string;
  brand?: string | null;
  vehicle_name?: string | null;
}

export interface CreateRagDocumentResponse {
  document_id: number;
  status: string;
}

export interface TrainRagRequest {
  tenant_id: string;
  merchant_id: string;
  douyin_account_id: number;
}

export interface TrainRagResponse {
  training_run_id: number;
  status: string;
  document_count: number;
  chunk_count: number;
  error?: string | null;
}

export interface SearchRagRequest {
  tenant_id: string;
  merchant_id: string;
  douyin_account_id: number;
  query: string;
  top_k?: number;
}

export interface RagSearchItem {
  chunk_id: number;
  document_id: number;
  title: string;
  chunk_text: string;
  score: number;
}

export interface SearchRagResponse {
  items: RagSearchItem[];
}

export interface ReplySuggestionRequest {
  tenant_id: string;
  merchant_id?: string;
  account_id: number;
  douyin_account_id?: number;
  agent_id?: string;
  latest_message: string;
  max_history_messages?: number;
}

export interface ReplySourceChunk {
  chunk_id: number;
  document_id: number;
  title: string;
  score: number;
}

export interface ReplySuggestionResponse {
  reply_text: string;
  match_level: string;
  target_brand?: string | null;
  target_category?: string | null;
  target_vehicle_name?: string | null;
  lead_capture_required: boolean;
  manual_required: boolean;
  auto_send: boolean;
  llm_used?: boolean;
  rag_used?: boolean;
  source_chunks?: ReplySourceChunk[];
  warnings?: string[];
  agent_id?: string | null;
  agent_name?: string | null;
  agent_category?: string | null;
}

export interface SendDouyinManualMessageRequest {
  conversation_short_id: string;
  customer_open_id?: string;
  content: string;
  scene?: "im_reply_msg";
  manual_confirmed: true;
  operator_id?: string;
}

export interface SendDouyinManualMessageResponse {
  success: boolean;
  data: {
    send_id?: number;
    status?: string;
    upstream_msg_id?: string | null;
    auto_send: boolean;
    manual_confirmed: boolean;
    [key: string]: unknown;
  };
}

export interface DownloadDouyinResourceRequest {
  conversation_short_id: string;
  server_message_id?: string;
  open_id?: string;
  media_type?: "image" | "video";
  url?: string;
}

export interface DownloadDouyinResourceResponse {
  success: boolean;
  data: {
    resource_status?: string;
    media_type?: "image" | "video" | string;
    download_url?: string | null;
    conversation_short_id?: string;
    server_message_id?: string | null;
    [key: string]: unknown;
  };
  message?: string;
}

function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return getAxiosErrorMessage(error);
  }
  if (error instanceof SyntaxError) {
    return "返回 JSON 解析失败";
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "未知错误";
}

function getAxiosErrorMessage(error: AxiosError): string {
  if (error.response) {
    const detail = extractResponseDetail(error.response.data);
    return `HTTP ${error.response.status}${detail ? `：${detail}` : ""}`;
  }
  if (error.request) {
    return "无法连接 9100 服务，请确认抖音AI客服已启动";
  }
  return error.message || "请求未能发出";
}

function extractResponseDetail(data: unknown): string {
  if (!data) {
    return "";
  }
  if (typeof data === "string") {
    return data;
  }
  if (typeof data === "object" && "detail" in data) {
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg?: unknown }).msg || "");
          }
          return "";
        })
        .filter(Boolean)
        .join("；");
    }
    if (detail && typeof detail === "object") {
      const detailRecord = detail as {
        safe_message?: unknown;
        upstream_msg?: unknown;
        detail?: unknown;
      };
      if (typeof detailRecord.safe_message === "string") {
        return detailRecord.safe_message;
      }
      if (typeof detailRecord.upstream_msg === "string") {
        return detailRecord.upstream_msg;
      }
      if (typeof detailRecord.detail === "string") {
        return detailRecord.detail;
      }
    }
  }
  return "";
}

async function requestDouyinAiCs<T>(request: Promise<{ data: T }>): Promise<T> {
  try {
    const response = await request;
    return response.data;
  } catch (error) {
    throw new Error(`9100 抖音AI客服接口请求失败：${getErrorMessage(error)}`);
  }
}

export async function getDouyinAiCsHealth(): Promise<DouyinAiCsHealthResponse> {
  return requestDouyinAiCs(douyinAiCsClient.get<DouyinAiCsHealthResponse>("/health"));
}

export async function getDouyinAiCsReady(): Promise<DouyinAiCsHealthResponse> {
  return requestDouyinAiCs(douyinAiCsClient.get<DouyinAiCsHealthResponse>("/ready"));
}

export async function getDouyinAiCsVersion(): Promise<DouyinAiCsHealthResponse> {
  return requestDouyinAiCs(douyinAiCsClient.get<DouyinAiCsHealthResponse>("/version"));
}

export async function getDouyinAccounts(): Promise<DouyinAccountListResponse> {
  return requestDouyinAiCs(douyinAiCsClient.get<DouyinAccountListResponse>("/douyin/accounts"));
}

export async function getDouyinAccountAgents(
  accountId: string | number,
  params?: { tenant_id?: string; merchant_id?: string },
): Promise<DouyinAgentListResponse> {
  return requestDouyinAiCs(
    douyinAiCsClient.get<DouyinAgentListResponse>(
      `/douyin/accounts/${encodeURIComponent(String(accountId))}/agents`,
      { params },
    ),
  );
}

export async function getDouyinAccountConversations(
  accountId: string | number,
  params?: { account_open_id?: string },
): Promise<DouyinConversationListResponse> {
  return apiClient.get(
    `/integrations/douyin/accounts/${encodeURIComponent(String(accountId))}/conversations`,
    { params },
  ) as unknown as Promise<DouyinConversationListResponse>;
}

export async function getDouyinConversationMessages(
  conversationId: string | number,
  params?: { account_open_id?: string },
): Promise<DouyinMessageListResponse> {
  return apiClient.get(
    "/integrations/douyin/conversation-messages",
    {
      params: {
        conversation_key: String(conversationId),
        account_open_id: params?.account_open_id,
      },
    },
  ) as unknown as Promise<DouyinMessageListResponse>;
}

export async function sendDouyinManualMessage(
  payload: SendDouyinManualMessageRequest,
): Promise<SendDouyinManualMessageResponse> {
  try {
    return (await apiClient.post(
      "/integrations/douyin/live-check/messages/send",
      payload,
    )) as unknown as SendDouyinManualMessageResponse;
  } catch (error) {
    throw new Error(`抖音私信发送失败：${getErrorMessage(error)}`);
  }
}

export async function downloadDouyinResource(
  payload: DownloadDouyinResourceRequest,
): Promise<DownloadDouyinResourceResponse> {
  try {
    return (await apiClient.post(
      "/integrations/douyin/live-check/resources/download",
      payload,
    )) as unknown as DownloadDouyinResourceResponse;
  } catch (error) {
    throw new Error(`抖音资源下载失败：${getErrorMessage(error)}`);
  }
}

export async function getDouyinConversationProfile(
  conversationId: string | number,
): Promise<DouyinUserProfileResponse> {
  return requestDouyinAiCs(
    douyinAiCsClient.get<DouyinUserProfileResponse>(
      `/douyin/conversations/${encodeURIComponent(String(conversationId))}/profile`,
    ),
  );
}

export async function createRagDocument(
  payload: CreateRagDocumentRequest,
): Promise<CreateRagDocumentResponse> {
  return requestDouyinAiCs(
    douyinAiCsClient.post<CreateRagDocumentResponse>("/rag/documents", payload),
  );
}

export async function trainRag(payload: TrainRagRequest): Promise<TrainRagResponse> {
  return requestDouyinAiCs(douyinAiCsClient.post<TrainRagResponse>("/rag/train", payload));
}

export async function searchRag(payload: SearchRagRequest): Promise<SearchRagResponse> {
  return requestDouyinAiCs(douyinAiCsClient.post<SearchRagResponse>("/rag/search", payload));
}

export async function getReplySuggestion(
  conversationId: string | number,
  payload: ReplySuggestionRequest,
): Promise<ReplySuggestionResponse> {
  return requestDouyinAiCs(
    douyinAiCsClient.post<ReplySuggestionResponse>(
      `/douyin/conversations/${encodeURIComponent(String(conversationId))}/reply-suggestion`,
      payload,
    ),
  );
}
