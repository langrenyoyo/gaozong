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
} from "./types";

/** 响应统一解包：{ success, data, message } → data。 */
function unwrap<T>(resp: { data: { success?: boolean; data?: T; message?: string } }): T {
  return resp.data.data as T;
}

/** 列模板（商户只读）。 */
export async function fetchAiEditTemplates(): Promise<AiEditListResponse<AiEditTemplate>> {
  return unwrap(await apiClient.get("/ai-edit/templates"));
}

/** 列素材（私有 + 平台公共，商户隔离）。 */
export async function fetchAiEditMaterials(): Promise<AiEditListResponse<AiEditMaterial>> {
  return unwrap(await apiClient.get("/ai-edit/materials"));
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
} from "./types";
