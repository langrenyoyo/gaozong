/**
 * 线索通知 API
 *
 * 对应 auto_wechat 路由：
 *   POST /lead-notifications/send-to-staff → 发送线索给销售
 *   GET  /lead-notifications/records       → 查询通知记录
 */

import apiClient from "./client";
import type {
  SendToStaffResponse,
  NotificationRecordsResponse,
} from "./types";

/** 发送线索给销售（自动搜索 + 发送 + 设置自动检测） */
export async function sendLeadToStaff(
  leadId: number,
  autoSend: boolean = true,
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
