import axios, { AxiosError } from "axios";

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
