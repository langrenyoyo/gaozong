/**
 * 线索通知 API
 *
 * 对应 auto_wechat 路由：
 *   POST /lead-notifications/send-to-staff → 创建通知销售的微信任务
 *   GET  /lead-notifications/records       → 查询通知记录
 */

import apiClient from "./client";
import type {
  SendToStaffResponse,
  NotificationRecordsResponse,
} from "./types";

/** 创建通知销售的微信任务（9000 不直接操作微信） */
export async function sendLeadToStaff(
  leadId: number,
  autoSend: boolean = false,
): Promise<SendToStaffResponse> {
  return apiClient.post("/lead-notifications/send-to-staff", {
    lead_id: leadId,
    auto_send: autoSend,
  });
}

/** 查询通知记录 */
export async function fetchNotificationRecords(params?: {
  lead_id?: number;
  staff_id?: number;
  send_status?: string;
  limit?: number;
}): Promise<NotificationRecordsResponse> {
  return apiClient.get("/lead-notifications/records", { params });
}
