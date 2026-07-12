/**
 * 每日报表 API
 *
 * 对应 auto_wechat Phase 8 Task 7 路由：
 *   POST /daily-reports/generate          → 生成（默认集或单类）
 *   POST /daily-reports/{job_id}/regenerate → 重试单个任务
 *   GET  /daily-reports/                  → 列表（按可信商户过滤）
 *   GET  /daily-reports/{job_id}/download  → 安全下载（返回 blob）
 *
 * 前端不拼接 storage_key、绝对路径或 token；下载文件名来自列表项 file_name。
 */

import apiClient from "./client";
import type {
  DailyReportJobListResponse,
  DailyReportListQuery,
  GenerateDailyReportsRequest,
  GenerateDailyReportsResponse,
  RegenerateDailyReportResponse,
} from "./types";

function compactParams(params: DailyReportListQuery): Record<string, string | number> {
  const result: Record<string, string | number> = {};
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    result[key] = value;
  });
  return result;
}

/** 生成日报：report_type 缺省生成默认集 */
export async function generateDailyReports(
  payload: GenerateDailyReportsRequest,
): Promise<GenerateDailyReportsResponse> {
  return apiClient.post("/daily-reports/generate", payload);
}

/** 重试单个日报任务；活跃生成中后端返回 409 */
export async function regenerateDailyReport(
  jobId: number,
): Promise<RegenerateDailyReportResponse> {
  return apiClient.post(`/daily-reports/${jobId}/regenerate`);
}

/** 列表：按可信商户过滤 + 分页 + 日期/类型/状态筛选 */
export async function fetchDailyReports(
  params: DailyReportListQuery,
): Promise<DailyReportJobListResponse> {
  return apiClient.get("/daily-reports/", { params: compactParams(params) });
}

/**
 * 下载日报：返回 blob，文件名由调用方从 DailyReportJobItem.file_name 取得。
 * 前端不接触存储路径/storage_key；后端按 job_id + 可信商户查找并校验完整性。
 */
export async function downloadDailyReport(jobId: number): Promise<Blob> {
  return apiClient.get(`/daily-reports/${jobId}/download`, {
    responseType: "blob",
  });
}
