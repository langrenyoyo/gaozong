import axios from "axios";
import apiClient from "../../api/client";
import { listDouyinAccounts } from "../douyin-cs/api";

export { listDouyinAccounts };

export {
  createKnowledgeCategory,
  getKnowledgeCategories,
} from "../agents/api";
export type { KnowledgeCategory } from "../agents/types";
export type { DouyinAccountItem } from "../douyin-cs/types";

const KNOWLEDGE_RAG_API_BASE_URL =
  import.meta.env.VITE_DOUYIN_AI_CS_API_BASE_URL || "http://127.0.0.1:9100";

const knowledgeRagClient = axios.create({
  baseURL: KNOWLEDGE_RAG_API_BASE_URL,
  timeout: 10000,
  headers: {
    "Content-Type": "application/json",
  },
});

export interface CreateRagDocumentRequest {
  account_open_id: string;
  title: string;
  content: string;
  category_key?: string;
  category?: string;
  brand?: string | null;
  vehicle_name?: string | null;
}

export interface CreateRagDocumentResponse {
  document_id: number;
  status: string;
}

export interface TrainRagRequest {
  account_open_id: string;
  category_key?: string;
  force_rebuild?: boolean;
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

function extractErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (error.response) return `HTTP ${error.response.status}`;
    if (error.request) return "服务未连接";
    return error.message || "请求未能发出";
  }
  if (error instanceof Error && error.message) return error.message;
  return "未知错误";
}

export async function createRagDocument(
  payload: CreateRagDocumentRequest,
): Promise<CreateRagDocumentResponse> {
  try {
    const response = (await apiClient.post(
      "/integrations/douyin-ai-cs/rag/documents",
      payload,
    )) as unknown as {
      success?: boolean;
      data: CreateRagDocumentResponse;
      message?: string;
    };
    return response.data;
  } catch (error) {
    throw new Error(`9000 RAG 文档代理请求失败：${extractErrorMessage(error)}`);
  }
}

export async function trainRag(payload: TrainRagRequest): Promise<TrainRagResponse> {
  try {
    const response = (await apiClient.post(
      "/integrations/douyin-ai-cs/rag/train",
      payload,
    )) as unknown as {
      success?: boolean;
      data: TrainRagResponse;
      message?: string;
    };
    return response.data;
  } catch (error) {
    throw new Error(`9000 RAG 训练代理请求失败：${extractErrorMessage(error)}`);
  }
}

export async function searchRag(payload: SearchRagRequest): Promise<SearchRagResponse> {
  try {
    const response = await knowledgeRagClient.post<SearchRagResponse>("/rag/search", payload);
    return response.data;
  } catch (error) {
    throw new Error(`RAG 搜索请求失败：${extractErrorMessage(error)}`);
  }
}
export type * from "./types";
