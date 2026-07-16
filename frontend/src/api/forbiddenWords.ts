import apiClient from "./client";

// 违禁词库（一期全局固定 3 类 seed + 超管扩展）
export interface ForbiddenWordLibrary {
  id: number;
  library_key: string;
  name: string;
  description?: string | null;
  scope?: string | null;
  enabled: boolean;
  sort_order: number;
}

// 违禁词条（脱敏展示字段，不含敏感原始词库内部信息）
export interface ForbiddenWord {
  id: number;
  library_id: number;
  library_key: string;
  word: string;
  safe_word: string;
  severity?: string | null;
  enabled: boolean;
  hit_count: number;
}

export interface ForbiddenWordListData {
  total: number;
  items: ForbiddenWord[];
}

export interface ForbiddenWordQueryParams {
  library_key?: string;
  enabled?: boolean | null;
  keyword?: string;
}

export interface ForbiddenWordCreatePayload {
  library_key: string;
  word: string;
  safe_word: string;
  severity?: string | null;
  enabled?: boolean;
}

export interface ForbiddenWordUpdatePayload {
  word?: string;
  safe_word?: string;
  severity?: string | null;
  enabled?: boolean;
}

interface ApiResponse<T> {
  success?: boolean;
  data: T;
  message?: string;
}

function buildQueryParams(query: ForbiddenWordQueryParams = {}): URLSearchParams {
  const params = new URLSearchParams();
  if (query.library_key) params.set("library_key", query.library_key);
  if (typeof query.enabled === "boolean") params.set("enabled", String(query.enabled));
  if (query.keyword) params.set("keyword", query.keyword);
  return params;
}

export async function getForbiddenWordLibraries(): Promise<ForbiddenWordLibrary[]> {
  const response = (await apiClient.get("/admin/forbidden-word-libraries")) as unknown as ApiResponse<{
    total: number;
    items: ForbiddenWordLibrary[];
  }>;
  return response.data.items || [];
}

export async function getForbiddenWords(
  query: ForbiddenWordQueryParams = {},
): Promise<ForbiddenWordListData> {
  const params = buildQueryParams(query);
  const response = (await apiClient.get("/admin/forbidden-words", { params })) as unknown as ApiResponse<ForbiddenWordListData>;
  return response.data;
}

export async function createForbiddenWord(
  payload: ForbiddenWordCreatePayload,
): Promise<ForbiddenWord> {
  const response = (await apiClient.post("/admin/forbidden-words", payload)) as unknown as ApiResponse<ForbiddenWord>;
  return response.data;
}

export async function updateForbiddenWord(
  id: number,
  payload: ForbiddenWordUpdatePayload,
): Promise<ForbiddenWord> {
  const response = (await apiClient.put(`/admin/forbidden-words/${encodeURIComponent(String(id))}`, payload)) as unknown as ApiResponse<ForbiddenWord>;
  return response.data;
}

export async function toggleForbiddenWord(id: number, enabled: boolean): Promise<ForbiddenWord> {
  const response = (await apiClient.post(
    `/admin/forbidden-words/${encodeURIComponent(String(id))}/toggle`,
    { enabled },
  )) as unknown as ApiResponse<ForbiddenWord>;
  return response.data;
}
