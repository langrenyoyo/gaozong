// Phase 12 Task 9 AI 剪辑 9000 API 客户端。
// 冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §11。
//
// 复用 apiClient（9000），统一鉴权 auto_wechat:ai_edit；不持有 internal token、
// 不直连 9100 或向量库、不接受前端自报 merchant_id（由 9000 可信上下文注入）。

import apiClient from "../../api/client";
import type {
  AiEditJob,
  AiEditJobCreateRequest,
  AiEditListResponse,
  AiEditMaterial,
  AiEditTemplate,
  LasJobCreateRequest,
  LasJobStatus,
} from "./types";

/** apiClient 已把 AxiosResponse 解成 { success, data, message }，这里只取一层 data。 */
function unwrap<T>(resp: { data?: T }): T {
  return resp.data as T;
}

/** 列模板（商户只读）。 */
export async function fetchAiEditTemplates(): Promise<AiEditListResponse<AiEditTemplate>> {
  return unwrap(await apiClient.get("/ai-edit/templates"));
}

/** 获取本机 Local Agent token（FIX2-1：浏览器调 19000 的鉴权通道，9000 下发）。 */
export async function fetchAiEditAgentToken(): Promise<{ token: string; merchant_id: string }> {
  return unwrap(await apiClient.get("/ai-edit/agent-token"));
}

/** 列素材（私有 + 平台公共，商户隔离）。 */
export async function fetchAiEditMaterials(): Promise<AiEditListResponse<AiEditMaterial>> {
  return unwrap(await apiClient.get("/ai-edit/materials"));
}

/** TOS 上传素材产物（预签名 URL + 过期时间）。 */
export interface TosUploadResult {
  material_id: string;
  tos_key: string;
  tos_presigned_url: string;
  tos_presigned_expires_at: string;
  source_sha256: string;
  display_name: string;
}

/** 上传素材到 TOS 生成预签名 URL（喂给 LAS 混剪）。 */
export async function uploadMaterialToTos(file: File, category?: string): Promise<TosUploadResult> {
  const form = new FormData();
  form.append("file", file);
  if (category) form.append("category", category);
  return unwrap(await apiClient.post("/ai-edit/materials/upload-tos", form, {
    headers: { "Content-Type": "multipart/form-data" },
  }));
}

/** 删除素材（软删除，商户隔离）。 */
export async function deleteMaterial(materialId: string): Promise<void> {
  await apiClient.delete(`/ai-edit/materials/${encodeURIComponent(materialId)}`);
}

/** 重新分析素材（方舟多模态）。 */
export async function reanalyzeMaterial(materialId: string): Promise<void> {
  await apiClient.post(`/ai-edit/materials/${encodeURIComponent(materialId)}/analyze`);
}

/** 创建任务（9000 注入 merchant_id，前端不自报）。 */
export async function createAiEditJob(payload: AiEditJobCreateRequest): Promise<AiEditJob> {
  return unwrap(await apiClient.post("/ai-edit/jobs", payload));
}

/** 查询任务详情。 */
export async function fetchAiEditJob(jobId: string): Promise<AiEditJob> {
  return unwrap(await apiClient.get(`/ai-edit/jobs/${encodeURIComponent(jobId)}`));
}

/** 取消任务。 */
export async function cancelAiEditJob(jobId: string): Promise<AiEditJob> {
  return unwrap(await apiClient.post(`/ai-edit/jobs/${encodeURIComponent(jobId)}/cancel`));
}

/** 重试任务（推进 attempt）。 */
export async function retryAiEditJob(jobId: string): Promise<AiEditJob> {
  return unwrap(await apiClient.post(`/ai-edit/jobs/${encodeURIComponent(jobId)}/retry`));
}

export type {
  AiEditJob,
  AiEditJobCreateRequest,
  AiEditJobMaterialItem,
  AiEditJobStatus,
  AiEditListResponse,
  AiEditMaterial,
  AiEditTemplate,
  LasJobCreateRequest,
  LasJobStatus,
} from "./types";

// ===== LAS speech_auto 云端混剪（2026-07-31 重做）=====

/** 提交 LAS 混剪任务，返回任务初始状态（含 job_id）。 */
export async function createLasJob(payload: LasJobCreateRequest): Promise<LasJobStatus> {
  return unwrap(await apiClient.post("/ai-edit/las/jobs", payload));
}

/** 查询 LAS 混剪任务状态 + 产物。 */
export async function getLasJob(jobId: number): Promise<LasJobStatus> {
  return unwrap(await apiClient.get(`/ai-edit/las/jobs/${jobId}`));
}

/** LAS 任务列表响应。 */
export interface LasJobListData {
  page: number;
  page_size: number;
  total: number;
  items: LasJobStatus[];
}

/** 查询 LAS 混剪任务列表（分页 + 状态筛选 + 标题搜索）。 */
export async function listLasJobs(params: { status?: string; page?: number; page_size?: number; keyword?: string } = {}): Promise<LasJobListData> {
  return unwrap(await apiClient.get("/ai-edit/las/jobs", { params }));
}

/** 获取播放最终归档视频的短期预签名 URL（带 Authorization header fetch）。 */
export async function fetchPlayUrl(jobId: number): Promise<string> {
  const r = await apiClient.get(`/ai-edit/las/jobs/${jobId}/video/play`);
  return unwrap(r).url;
}

/** 获取一次性下载链接（带 token query 参数，浏览器原生 <a href> 下载带进度条）。 */
export async function fetchDownloadLink(jobId: number): Promise<{ download_url: string; filename: string }> {
  const r = await apiClient.get(`/ai-edit/las/jobs/${jobId}/video/download-link`);
  return unwrap(r);
}

/** 删除任务（软删除 + 清理自有 TOS 归档视频，幂等）。 */
export async function deleteLasJob(jobId: number): Promise<{ deleted: boolean; status: string }> {
  return unwrap(await apiClient.delete(`/ai-edit/las/jobs/${jobId}`));
}
