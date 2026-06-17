/**
 * 微信自动检测目标 API
 *
 * 对应 auto_wechat 路由：
 *   POST /wechat-auto-detect/target → 设置检测目标
 *   GET  /wechat-auto-detect/status → 查询检测状态
 *   POST /wechat-auto-detect/clear  → 清除检测目标
 */

import apiClient from "./client";
import type { WechatAutoDetectStatus } from "./types";

/** 设置自动检测目标 */
export async function setWechatAutoDetectTarget(
  checkId: number,
): Promise<WechatAutoDetectStatus> {
  return apiClient.post("/wechat-auto-detect/target", { check_id: checkId });
}

/** 查询自动检测状态 */
export async function fetchWechatAutoDetectStatus(): Promise<WechatAutoDetectStatus> {
  return apiClient.get("/wechat-auto-detect/status");
}

/** 清除自动检测目标 */
export async function clearWechatAutoDetectTarget(): Promise<WechatAutoDetectStatus> {
  return apiClient.post("/wechat-auto-detect/clear");
}
