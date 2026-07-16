// Phase 12 Task 9 AI 剪辑 Local API 客户端（127.0.0.1:19000）。
// 冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §11。
//
// 直连浏览器所在电脑的 127.0.0.1:19000（小高AI微信助手），不走 VITE_API_BASE_URL。
// 复用本机 Agent token 处理方式（与 localWechatAgent.ts 一致）；不经过 9000 客户端。
// merchant_id 由 Local Agent token 映射，前端不自报。

import { LOCAL_AGENT_BASE_URL } from "../../api/localWechatAgent";
import { fetchAiEditAgentToken } from "./api";
import type { LocalAiEditStatus } from "./types";

/** Local AI 剪辑基址（显式声明，便于合同脚本静态校验）。 */
export const LOCAL_AI_EDIT_BASE_URL = "http://127.0.0.1:19000";

/** FIX2-1/FIX3-1：浏览器调 19000 的 token 获取/保存/发送。
 * 9000 下发当前商户的 Local Agent token，前端 sessionStorage 保存（会话级，绑定 merchant_id），
 * 请求带 X-Local-Agent-Token。不依赖关闭 19000 鉴权。
 * FIX3-1：缓存键含 merchant_id，A 退出 B 登录不会复用 A 的 token（不同键 + 退出清全部）。 */
const AGENT_TOKEN_STORAGE_PREFIX = "ai_edit_agent_token:";

function tokenStorageKey(merchantId: string): string {
  return `${AGENT_TOKEN_STORAGE_PREFIX}${merchantId}`;
}

interface CachedAgentToken {
  token: string;
  merchant_id: string;
}

/** 获取本机 Local Agent token：先 sessionStorage（绑定 merchantId），无则向 9000 申请。
 * FIX4-3：merchantId 必填，移除无值任取缓存的误用入口。 */
export async function ensureAgentToken(merchantId: string): Promise<string> {
  const cached = readCachedToken(merchantId);
  if (cached) return cached.token;
  // 清理其他商户的残留 token（A 退出 B 登录场景）
  clearAllAgentTokens();
  const resp = await fetchAiEditAgentToken();
  const cached: CachedAgentToken = { token: resp.token, merchant_id: resp.merchant_id };
  sessionStorage.setItem(tokenStorageKey(resp.merchant_id), JSON.stringify(cached));
  return resp.token;
}

function readCachedToken(merchantId: string): CachedAgentToken | null {
  const raw = sessionStorage.getItem(tokenStorageKey(merchantId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as CachedAgentToken;
    if (parsed.token && parsed.merchant_id === merchantId) return parsed;
  } catch {
    // 损坏则清
  }
  sessionStorage.removeItem(tokenStorageKey(merchantId));
  return null;
}

/** 清除当前商户缓存的 token（401 时重试获取）。FIX4-3：merchantId 必填。 */
export function clearAgentToken(merchantId: string): void {
  sessionStorage.removeItem(tokenStorageKey(merchantId));
}

/** 清除所有商户的 Local Agent token 缓存（退出登录时调用，FIX3-1）。 */
export function clearAllAgentTokens(): void {
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith(AGENT_TOKEN_STORAGE_PREFIX)) {
      sessionStorage.removeItem(key);
    }
  }
}

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

async function requestLocal<T>(path: string, init: RequestInit | undefined, merchantId: string): Promise<T> {
  const base = LOCAL_AGENT_BASE_URL || LOCAL_AI_EDIT_BASE_URL;
  // FIX2-1/FIX3-1：请求带 X-Local-Agent-Token（绑定 merchantId，防跨商户残留）
  const token = await ensureAgentToken(merchantId);
  const headers = {
    "Content-Type": "application/json",
    "X-Local-Agent-Token": token,
    ...(init?.headers || {}),
  };
  let response = await fetch(`${base}${path}`, { ...init, headers });
  // 401 清缓存重试一次（token 失效/轮换/商户切换）
  if (response.status === 401) {
    clearAgentToken(merchantId);
    const newToken = await ensureAgentToken(merchantId);
    response = await fetch(`${base}${path}`, {
      ...init,
      headers: { ...headers, "X-Local-Agent-Token": newToken },
    });
  }
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
export async function fetchLocalMaterials(merchantId: string): Promise<{
  total: number;
  items: LocalAiEditMaterialItem[];
}> {
  return requestLocal("/agent/ai-edit/materials", { method: "GET" }, merchantId);
}

/** 流式导入素材（原始字节流，避免 base64 全量内存）。 */
export async function importLocalMaterial(
  file: File,
  materialId: string,
  merchantId: string,
): Promise<LocalAiEditMaterial> {
  const base = LOCAL_AGENT_BASE_URL || LOCAL_AI_EDIT_BASE_URL;
  // FIX2-1/FIX3-1：带 X-Local-Agent-Token（绑定 merchantId）
  const token = await ensureAgentToken(merchantId);
  const params = new URLSearchParams({
    material_id: materialId,
    expected_size: String(file.size),
  });
  let response = await fetch(
    `${base}/agent/ai-edit/materials/import-stream?${params.toString()}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Local-Agent-Token": token,
      },
      body: file,
    },
  );
  if (response.status === 401) {
    clearAgentToken(merchantId);
    const newToken = await ensureAgentToken(merchantId);
    response = await fetch(
      `${base}/agent/ai-edit/materials/import-stream?${params.toString()}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Local-Agent-Token": newToken,
        },
        body: file,
      },
    );
  }
  if (!response.ok) {
    throw new Error(`本机素材导入失败：HTTP_${response.status}`);
  }
  const body = (await response.json()) as LocalAgentEnvelope<LocalAiEditMaterial>;
  return body.data;
}

/** 删除本机素材（进 7 天回收站）。 */
export async function deleteLocalMaterial(materialId: string, merchantId: string): Promise<void> {
  await requestLocal(`/agent/ai-edit/materials/${encodeURIComponent(materialId)}`, {
    method: "DELETE",
  }, merchantId);
}

/** 创建任务（由 Local Agent 生成 manifest + 启动 Worker）。 */
export async function createLocalJob(payload: {
  job_id: string;
  template_key: string;
  materials: {
    material_id: string;
    role: string;
    source_start?: number;
    source_end?: number;
  }[];
}, merchantId: string): Promise<{ job_id: string; status: string }> {
  return requestLocal("/agent/ai-edit/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  }, merchantId);
}

/** 取消任务（终止 Worker 进程树）。 */
export async function cancelLocalJob(jobId: string, merchantId: string): Promise<{ job_id: string; status: string }> {
  return requestLocal(`/agent/ai-edit/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  }, merchantId);
}

/** 重试任务（19000 协调：调 9000 agent-retry 推进 attempt + 重新入队）。 */
export async function retryLocalJob(
  jobId: string,
  merchantId: string,
): Promise<{ job_id: string; status: string; attempt_count: number }> {
  return requestLocal(`/agent/ai-edit/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
  }, merchantId);
}

/** 查询任务状态（商户隔离）。 */
export async function fetchLocalJob(jobId: string, merchantId: string): Promise<Record<string, unknown>> {
  return requestLocal(`/agent/ai-edit/jobs/${encodeURIComponent(jobId)}`, { method: "GET" }, merchantId);
}

/** 本机队列状态（按当前 token 商户过滤）。 */
export async function fetchLocalAiEditStatus(merchantId: string): Promise<LocalAiEditStatus> {
  return requestLocal("/agent/ai-edit/status", { method: "GET" }, merchantId);
}
