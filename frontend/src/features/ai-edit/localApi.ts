// Phase 12 Task 9 AI 剪辑 Local API 客户端（127.0.0.1:19000）。
// 冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §11。
//
// 直连浏览器所在电脑的 127.0.0.1:19000（小高AI微信助手），不走 VITE_API_BASE_URL。
// 复用本机 Agent token 处理方式（与 localWechatAgent.ts 一致）；不经过 9000 客户端。
// merchant_id 由 Local Agent token 映射，前端不自报。

import { LOCAL_AGENT_BASE_URL } from "../../api/localWechatAgent";
import type { LocalAiEditStatus } from "./types";

/** Local AI 剪辑基址（显式声明，便于合同脚本静态校验）。 */
export const LOCAL_AI_EDIT_BASE_URL = "http://127.0.0.1:19000";

/** Local Agent 导入结果（不含绝对路径 / merchant_id）。 */
export interface LocalAiEditMaterial {
  material_id: string;
  relative_path: string;
  sha256: string;
  size_bytes: number;
}

/** Local Agent 列素材项。 */
export interface LocalAiEditMaterialItem {
  material_id: string;
  relative_path: string;
  sha256: string;
  size_bytes: number;
  deleted_at: string | null;
}

interface LocalAgentEnvelope<T> {
  success: boolean;
  data: T;
  message: string;
}

async function requestLocal<T>(path: string, init?: RequestInit): Promise<T> {
  const base = LOCAL_AGENT_BASE_URL || LOCAL_AI_EDIT_BASE_URL;
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    try {
      const body = await response.json();
      const detail = body?.detail;
      if (detail && typeof detail === "object" && typeof detail.code === "string") {
        code = detail.code;
      }
    } catch {
      // 非 JSON 响应，保留 HTTP 状态码
    }
    throw new Error(`本机 AI 剪辑 Agent 请求失败：${code}`);
  }
  const body = (await response.json()) as LocalAgentEnvelope<T>;
  return body.data;
}

/** 列本机素材（按当前 token 商户隔离）。 */
export async function fetchLocalMaterials(): Promise<{
  total: number;
  items: LocalAiEditMaterialItem[];
}> {
  return requestLocal("/agent/ai-edit/materials", { method: "GET" });
}

/** 流式导入素材（原始字节流，避免 base64 全量内存）。 */
export async function importLocalMaterial(
  file: File,
  materialId: string,
): Promise<LocalAiEditMaterial> {
  const base = LOCAL_AGENT_BASE_URL || LOCAL_AI_EDIT_BASE_URL;
  const params = new URLSearchParams({
    material_id: materialId,
    expected_size: String(file.size),
  });
  const response = await fetch(
    `${base}/agent/ai-edit/materials/import-stream?${params.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    },
  );
  if (!response.ok) {
    throw new Error(`本机素材导入失败：HTTP_${response.status}`);
  }
  const body = (await response.json()) as LocalAgentEnvelope<LocalAiEditMaterial>;
  return body.data;
}

/** 删除本机素材（进 7 天回收站）。 */
export async function deleteLocalMaterial(materialId: string): Promise<void> {
  await requestLocal(`/agent/ai-edit/materials/${encodeURIComponent(materialId)}`, {
    method: "DELETE",
  });
}

/** 创建任务（由 Local Agent 生成 manifest + 启动 Worker）。 */
export async function createLocalJob(payload: {
  job_id: string;
  template_key: string;
  materials: { material_id: string; role: string }[];
}): Promise<{ job_id: string; status: string }> {
  return requestLocal("/agent/ai-edit/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** 取消任务（终止 Worker 进程树）。 */
export async function cancelLocalJob(jobId: string): Promise<{ job_id: string; status: string }> {
  return requestLocal(`/agent/ai-edit/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

/** 查询任务状态（商户隔离）。 */
export async function fetchLocalJob(jobId: string): Promise<Record<string, unknown>> {
  return requestLocal(`/agent/ai-edit/jobs/${encodeURIComponent(jobId)}`, { method: "GET" });
}

/** 本机队列状态（按当前 token 商户过滤）。 */
export async function fetchLocalAiEditStatus(): Promise<LocalAiEditStatus> {
  return requestLocal("/agent/ai-edit/status", { method: "GET" });
}
