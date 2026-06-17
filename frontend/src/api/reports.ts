/**
 * 报表 API
 *
 * 对应 auto_wechat 路由：
 *   GET /reports/summary → 汇总报表
 */

import apiClient from "./client";
import type { ReportSummary } from "./types";

/** 获取汇总报表 */
export async function fetchSummary(): Promise<ReportSummary> {
  return apiClient.get("/reports/summary");
}
