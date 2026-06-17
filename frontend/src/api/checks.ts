/**
 * 回复检测 API
 *
 * 对应 auto_wechat 路由：
 *   GET /checks → 检测记录列表
 */

import apiClient from "./client";
import type { CheckRecord } from "./types";

/** 获取检测记录列表，可按状态过滤 */
export async function fetchChecks(status?: string): Promise<CheckRecord[]> {
  const params = status ? { status } : {};
  return apiClient.get("/checks", { params });
}
