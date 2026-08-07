/**
 * 联系方式失效标记 API（任务 1.4）
 *
 * 对应 auto_wechat 路由：
 *   POST /admin/contact-invalid/mark — 管理员手动标记线索联系方式失效
 */

import apiClient from "./client";

export interface MarkContactInvalidPayload {
  lead_id: number;
  merchant_id: string;
  account_open_id: string;
  customer_open_id: string;
  reason: "空号" | "打不通" | "号码错误" | "停机" | "其他";
}

export interface MarkContactInvalidResponse {
  success: boolean;
  data: {
    lead_id: number;
    invalid_version: number | null;
    already_invalid: boolean;
    followup_task_id: number | null;
    followup_triggered: boolean;
  };
}

/** 管理员手动标记线索联系方式失效，触发空号追问链路（块3） */
export async function markContactInvalid(
  payload: MarkContactInvalidPayload,
): Promise<MarkContactInvalidResponse> {
  return apiClient.post("/admin/contact-invalid/mark", payload);
}
