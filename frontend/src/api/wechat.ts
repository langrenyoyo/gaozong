/**
 * 微信调试 API
 *
 * 对应 auto_wechat 路由：
 *   GET  /feedback/debug/current-chat            → 当前聊天窗口探测
 *   POST /feedback/debug/activate-wechat-window  → 激活微信窗口并移动到右上角
 */

import apiClient from "./client";

export interface WechatDebugResult {
  success: boolean;
  wechat_found: boolean;
  title: string | null;
  message_list_found: boolean;
  input_box_found: boolean;
  error?: string;
}

/** 探测当前微信窗口状态 */
export async function fetchWechatDebug(): Promise<WechatDebugResult> {
  return apiClient.get("/feedback/debug/current-chat");
}

/** 将微信窗口激活置顶并移动到右上角 */
export async function activateWechatWindow(): Promise<{
  success: boolean;
  message: string;
  hwnd?: number;
  rect?: { left: number; top: number; right: number; bottom: number };
  screen?: { width: number; height: number };
}> {
  return apiClient.post("/feedback/debug/activate-wechat-window");
}
