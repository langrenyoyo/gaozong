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
  tenant_id?: string | null;
  merchant_id?: string | null;
  account_name: string;
  account_open_id: string;
  open_id?: string;
  main_account_id?: string | null;
  status: string;
  avatar?: string | null;
  avatar_url?: string | null;
  unread_count?: number;
  last_active_at?: string | null;
  source?: string | null;
  is_authorized?: boolean;
  has_events?: boolean;
  bind_status?: number;
  authorization_status?: string | null;
  bound_agent_id?: string | null;
  bound_agent_name?: string | null;
  bound_agent_status?: string | null;
  binding_status?: string | null;
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

export interface DouyinAuthorizedAccountListResponse {
  success?: boolean;
  data: {
    items: DouyinAccountItem[];
    total: number;
  };
  message?: string;
}

export interface DouyinAccountAgentBindingResponse {
  success?: boolean;
  data: {
    id?: number;
    account_open_id: string;
    bound_agent_id?: string | null;
    binding_status?: string | null;
    is_default?: boolean;
    updated_at?: string;
    unbound_at?: string;
  };
  message?: string;
}

export interface DouyinAccountAuthorizationResponse {
  success?: boolean;
  data: {
    account_open_id: string;
    authorization_status?: string;
    binding_status?: string;
    invalidated_binding_count?: number;
    upstream_cancel_supported?: boolean;
  };
  message?: string;
}

export interface DouyinAccountDeleteResponse {
  success?: boolean;
  data: {
    account_open_id: string;
    account_status?: string;
    binding_status?: string;
    deleted_binding_count?: number;
  };
  message?: string;
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
  tags?: string[];
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

export interface DouyinConversationProfile {
  conversation_id: string;
  conversation_key?: string;
  conversation_short_id?: string | null;
  account_open_id?: string | null;
  open_id?: string | null;
  nickname?: string | null;
  avatar?: string | null;
  online_status?: "online" | "offline" | "unknown" | string | null;
  source_channel?: string | null;
  intent_car?: string | null;
  car_year?: string | null;
  budget?: string | null;
  city?: string | null;
  tags?: string[];
  tag_labels?: string[];
  lead_score?: number | null;
  trace?: {
    event_key?: string | null;
    conversation_short_id?: string | null;
    server_message_id?: string | null;
    source?: string | null;
    created_at?: string | null;
  } | null;
  lead?: {
    id?: number;
    status?: string | null;
    customer_contact?: string | null;
    assigned_staff_id?: number | null;
  } | null;
}

export interface DouyinConversationProfileResponse {
  success?: boolean;
  data: DouyinConversationProfile;
  message?: string;
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

export interface UploadDouyinImageRequest {
  file_name: string;
  image_base64: string;
  open_id?: string;
}

export interface UploadDouyinImageResponse {
  success?: boolean;
  data?: {
    upload_status?: string;
    image_id?: string;
    width?: number;
    height?: number;
    md5?: string;
    file_name?: string;
    [key: string]: unknown;
  };
  message?: string;
  detail?: string | { safe_message?: string; error_code?: string };
  error?: { safe_message?: string; message?: string };
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

function getAutoWechatProxyErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (error.response) {
      const detail = extractResponseDetail(error.response.data);
      return `HTTP ${error.response.status}${detail ? `：${detail}` : ""}`;
    }
    if (error.request) {
      return "无法连接 9000 主服务，请确认 auto_wechat 后端已启动";
    }
    return error.message || "请求未能发出";
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "未知错误";
}

function businessErrorMessage(code: string): string {
  const messages: Record<string, string> = {
    AGENT_NOT_FOUND: "智能体不存在，请重新选择。",
    AGENT_MERCHANT_DENIED: "该智能体不属于当前商户，不能绑定。",
    AGENT_NOT_ACTIVE: "该智能体未启用，请先启用后再绑定。",
    AGENT_BINDING_NOT_FOUND: "未找到可解绑的智能体绑定。",
    DOUYIN_ACCOUNT_NOT_FOUND: "抖音企业号不存在或已被删除。",
    DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED: "该抖音企业号不属于当前商户。",
    DOUYIN_ACCOUNT_NOT_AUTHORIZED: "该抖音企业号未授权或授权已失效。",
    DOUYIN_ACCOUNT_DELETED: "该抖音企业号已删除。",
    DOUYIN_AGENT_BINDING_DENIED: "抖音企业号与智能体绑定校验失败。",
    MERCHANT_CONTEXT_MISSING: "缺少可信商户上下文，请重新登录后再试。",
  };
  return messages[code] || code;
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
        code?: unknown;
        message?: unknown;
        safe_message?: unknown;
        upstream_msg?: unknown;
        detail?: unknown;
      };
      if (typeof detailRecord.code === "string") {
        const message =
          typeof detailRecord.message === "string"
            ? detailRecord.message
            : businessErrorMessage(detailRecord.code);
        return `${businessErrorMessage(detailRecord.code)}${message ? `（${message}）` : ""}`;
      }
      if (typeof detailRecord.message === "string") {
        return detailRecord.message;
      }
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
  if (typeof data === "object" && "error" in data) {
    const error = (data as { error?: unknown }).error;
    if (error && typeof error === "object") {
      const errorRecord = error as { safe_message?: unknown; message?: unknown };
      if (typeof errorRecord.safe_message === "string") {
        return errorRecord.safe_message;
      }
      if (typeof errorRecord.message === "string") {
        return errorRecord.message;
      }
    }
  }
  return "";
}

function normalizeDouyinAccount(item: DouyinAccountItem): DouyinAccountItem {
  const avatar = item.avatar || item.avatar_url || null;
  const authorizationStatus =
    item.authorization_status || (item.bind_status === 1 || item.is_authorized ? "authorized" : "unauthorized");
  return {
    ...item,
    account_open_id: item.account_open_id || item.open_id || "",
    status: item.status || authorizationStatus,
    avatar,
    avatar_url: item.avatar_url || avatar,
    unread_count: Number.isFinite(Number(item.unread_count)) ? Number(item.unread_count) : 0,
    is_authorized: authorizationStatus === "authorized",
    authorization_status: authorizationStatus,
  };
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

export async function listDouyinAccounts(): Promise<DouyinAccountListResponse> {
  try {
    const response = (await apiClient.get(
      "/integrations/douyin/accounts",
    )) as unknown as DouyinAuthorizedAccountListResponse;
    return {
      items: (response.data?.items || []).map(normalizeDouyinAccount),
    };
  } catch (error) {
    throw new Error(`抖音企业号列表加载失败：${getAutoWechatProxyErrorMessage(error)}`);
  }
}

export async function bindAgentToDouyinAccount(
  accountOpenId: string,
  agentId: string,
): Promise<DouyinAccountAgentBindingResponse> {
  try {
    return (await apiClient.put(
      `/integrations/douyin/accounts/${encodeURIComponent(accountOpenId)}/agent-binding`,
      { agent_id: agentId },
    )) as unknown as DouyinAccountAgentBindingResponse;
  } catch (error) {
    throw new Error(`保存企业号智能体绑定失败：${getAutoWechatProxyErrorMessage(error)}`);
  }
}

export async function unbindAgentFromDouyinAccount(
  accountOpenId: string,
): Promise<DouyinAccountAgentBindingResponse> {
  try {
    return (await apiClient.delete(
      `/integrations/douyin/accounts/${encodeURIComponent(accountOpenId)}/agent-binding`,
    )) as unknown as DouyinAccountAgentBindingResponse;
  } catch (error) {
    throw new Error(`解绑企业号智能体失败：${getAutoWechatProxyErrorMessage(error)}`);
  }
}

export async function cancelDouyinAccountAuthorization(
  accountOpenId: string,
): Promise<DouyinAccountAuthorizationResponse> {
  try {
    return (await apiClient.post(
      `/integrations/douyin/accounts/${encodeURIComponent(accountOpenId)}/cancel-authorization`,
    )) as unknown as DouyinAccountAuthorizationResponse;
  } catch (error) {
    throw new Error(`取消抖音企业号授权失败：${getAutoWechatProxyErrorMessage(error)}`);
  }
}

export async function deleteDouyinAccount(
  accountOpenId: string,
): Promise<DouyinAccountDeleteResponse> {
  try {
    return (await apiClient.delete(
      `/integrations/douyin/accounts/${encodeURIComponent(accountOpenId)}`,
    )) as unknown as DouyinAccountDeleteResponse;
  } catch (error) {
    throw new Error(`删除抖音企业号失败：${getAutoWechatProxyErrorMessage(error)}`);
  }
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

export async function getDouyinConversationProfileFrom9000(
  accountId: string | number,
  conversationKey: string | number,
  params?: { account_open_id?: string },
): Promise<DouyinConversationProfile> {
  try {
    const response = (await apiClient.get(
      `/integrations/douyin/accounts/${encodeURIComponent(String(accountId))}/conversations/${encodeURIComponent(
        String(conversationKey),
      )}/profile`,
      { params },
    )) as unknown as DouyinConversationProfileResponse;
    return response.data;
  } catch (error) {
    throw new Error(`抖音客户画像加载失败：${getAutoWechatProxyErrorMessage(error)}`);
  }
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

export async function uploadDouyinImage(
  payload: UploadDouyinImageRequest,
): Promise<UploadDouyinImageResponse> {
  try {
    return (await apiClient.post(
      "/integrations/douyin/live-check/resources/upload-image",
      payload,
    )) as unknown as UploadDouyinImageResponse;
  } catch (error) {
    throw new Error(`抖音图片上传失败：${getErrorMessage(error)}`);
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

export async function getTrustedReplySuggestion(
  conversationId: string | number,
  payload: ReplySuggestionRequest,
): Promise<ReplySuggestionResponse> {
  try {
    return (await apiClient.post(
      `/integrations/douyin-ai-cs/conversations/${encodeURIComponent(
        String(conversationId),
      )}/reply-suggestion`,
      payload,
    )) as unknown as ReplySuggestionResponse;
  } catch (error) {
    throw new Error(`9000 抖音AI客服代理接口请求失败：${getAutoWechatProxyErrorMessage(error)}`);
  }
}
