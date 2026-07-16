/**
 * 微信任务队列 API。
 *
 * 浏览器任务列表走 NewCar 用户接口：GET /wechat-tasks。
 * Local Agent 拉取待执行任务保留机器接口：GET /wechat-tasks/pending。
 */

import apiClient from "./client";
import type {
  WechatTask,
  WechatTaskHistoryItem,
  WechatTaskHistoryParams,
  WechatTaskHistoryResponse,
} from "./types";

function historyItemToWechatTask(item: WechatTaskHistoryItem): WechatTask {
  return {
    id: item.id,
    task_type: item.task_type,
    lead_id: item.lead_id,
    staff_id: item.staff_id,
    reply_check_id: null,
    target_nickname: item.target_nickname,
    message: null,
    mode: item.mode,
    status: item.status,
    failure_stage: item.failure_stage,
    raw_result: null,
    agent_hostname: null,
    agent_pid: null,
    pasted_at: null,
    sent_at: item.sent_at,
    created_at: item.created_at,
    updated_at: item.updated_at,
  };
}

/** 浏览器 pending 列表：走 NewCar 用户接口 GET /wechat-tasks?status=pending。 */
export async function fetchBrowserPendingWechatTasks(
  params?: { limit?: number; task_type?: string },
): Promise<WechatTask[]> {
  const history = await fetchWechatTaskHistory({
    page: 1,
    page_size: params?.limit ?? 20,
    status: "pending",
    task_type: params?.task_type,
  });
  return history.items.map(historyItemToWechatTask);
}

/** Local Agent 拉任务专用：保留 GET /wechat-tasks/pending 机器接口语义。 */
export async function fetchPendingWechatTasks(
  params?: { limit?: number; task_type?: string },
): Promise<WechatTask[]> {
  return apiClient.get("/wechat-tasks/pending", { params });
}

/** 分页查询微信任务历史列表，列表只返回 raw_result 摘要。 */
export async function fetchWechatTaskHistory(
  params?: WechatTaskHistoryParams,
): Promise<WechatTaskHistoryResponse> {
  return apiClient.get("/wechat-tasks", { params });
}

/** 查询单条微信任务详情。 */
export async function fetchWechatTask(taskId: number): Promise<WechatTask> {
  return apiClient.get(`/wechat-tasks/${taskId}`);
}

export const fetchWechatTaskDetail = fetchWechatTask;
