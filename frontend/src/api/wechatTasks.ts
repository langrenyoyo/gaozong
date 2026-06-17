/**
 * 微信任务队列 API（P0-5A）
 *
 * 对应 auto_wechat 路由：
 *   POST /wechat-tasks            → 创建微信任务
 *   GET  /wechat-tasks/pending    → 查询 pending 任务列表
 *   GET  /wechat-tasks/{task_id}  → 查询任务详情
 *
 * 通过主系统 baseURL（VITE_AUTO_WECHAT_API_BASE_URL）调用，
 * 不走本机 Agent（127.0.0.1:19000）。
 */

import apiClient from "./client";
import type { WechatTask, WechatTaskCreateRequest } from "./types";

/** 创建微信任务（P0-FE-MAIN-1） */
export async function createWechatTask(payload: WechatTaskCreateRequest): Promise<WechatTask> {
  return apiClient.post("/wechat-tasks", payload);
}

/** 查询 pending 状态的微信任务列表 */
export async function fetchPendingWechatTasks(
  params?: { limit?: number; task_type?: string },
): Promise<WechatTask[]> {
  return apiClient.get("/wechat-tasks/pending", { params });
}

/** 查询单条微信任务详情 */
export async function fetchWechatTask(taskId: number): Promise<WechatTask> {
  return apiClient.get(`/wechat-tasks/${taskId}`);
}
