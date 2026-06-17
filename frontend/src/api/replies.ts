/**
 * 回复检测 API
 *
 * 对应 auto_wechat 路由：
 *   POST /replies/current-wechat-detect → 检测当前微信窗口销售回复
 */

import apiClient from "./client";
import type { WechatDetectResponse } from "./types";

interface DetectParams {
  leadId: number;
  staffId: number;
  maxMessages?: number;
  confirmCurrentChat?: boolean;
}

/** 检测当前微信窗口中销售是否已回复 */
export async function detectWechatReply(
  params: DetectParams,
): Promise<WechatDetectResponse> {
  return apiClient.post("/replies/current-wechat-detect", {
    lead_id: params.leadId,
    staff_id: params.staffId,
    max_messages: params.maxMessages ?? 20,
    confirm_current_chat: params.confirmCurrentChat ?? true,
  });
}
