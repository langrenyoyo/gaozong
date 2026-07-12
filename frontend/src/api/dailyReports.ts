/**
 * 每日报表 API（Phase 8 Task 8）
 *
 * 对应 auto_wechat 路由：
 *   POST /daily-reports/generate            → 生成（默认集或单类）
 *   POST /daily-reports/{job_id}/regenerate → 重试单个任务
 *   GET  /daily-reports/                    → 任务列表
 *   GET  /daily-reports/{job_id}/download   → 安全下载（返回 blob + 响应头文件名）
 *   GET  /daily-reports/data/lead-attributions / PUT → 待归因线索
 *   GET  /daily-reports/data-completeness   → 数据完整度
 *   GET  /daily-reports/data/ad-metrics / PUT       → 广告日指标
 *   GET  /daily-reports/profile / PUT               → 展厅价位
 *
 * 下载使用 fetch 取响应头文件名（Content-Disposition），不把 token 放 URL query；
 * 前端不拼接内部存储键、绝对路径或生成令牌。
 */

import apiClient, { API_BASE_URL } from "./client";
import { getExternalToken } from "../authToken";
import type {
  DailyAdMetricListResponse,
  DailyAdMetricUpsert,
  DailyAdMetricUpsertResponse,
  DailyReportJobListResponse,
  DailyReportListQuery,
  GenerateDailyReportsRequest,
  GenerateDailyReportsResponse,
  LeadAttributionListQuery,
  LeadAttributionListResponse,
  LeadAttributionUpsertResponse,
  LeadReportAttributionUpsert,
  MerchantReportProfileOut,
  RegenerateDailyReportResponse,
  ReportDataCompletenessOut,
} from "./types";

function compactParams(
  params: object,
): Record<string, string | number | boolean> {
  const result: Record<string, string | number | boolean> = {};
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    result[key] = value as string | number | boolean;
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

/** 任务列表：按可信商户过滤 + 分页 + 日期/类型/状态筛选 */
export async function fetchDailyReports(
  params: DailyReportListQuery,
): Promise<DailyReportJobListResponse> {
  return apiClient.get("/daily-reports/", { params: compactParams(params) });
}

/** 解析 Content-Disposition 中的文件名（RFC 5987 filename* 优先，兼容 filename）。 */
function parseContentDispositionFilename(cd: string): string | null {
  if (!cd) return null;
  const star = /filename\*\s*=\s*([^;]+)/i.exec(cd);
  if (star) {
    const raw = star[1].trim().replace(/^["']|["']$/g, "");
    const utf8 = /UTF-8''(.+)/i.exec(raw);
    if (utf8) {
      try {
        return decodeURIComponent(utf8[1]);
      } catch {
        return utf8[1];
      }
    }
    return raw || null;
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(cd);
  return plain ? plain[1].trim() : null;
}

/**
 * 下载日报：使用 fetch 取响应头 Content-Disposition 的文件名；
 * token 走 Authorization 头，不放进 URL query；失败抛出 axios 兼容结构供 getApiErrorCode 解析。
 */
export async function downloadDailyReport(
  jobId: number,
): Promise<{ blob: Blob; filename: string }> {
  const base = API_BASE_URL || "";
  const resp = await fetch(`${base}/daily-reports/${jobId}/download`, {
    headers: buildAuthHeaders(),
  });
  if (!resp.ok) {
    let data: unknown = null;
    try {
      data = await resp.json();
    } catch {
      data = null;
    }
    throw { response: { status: resp.status, data } };
  }
  const cd = resp.headers.get("content-disposition") || "";
  const filename = parseContentDispositionFilename(cd) || `daily_report_${jobId}.xlsx`;
  const blob = await resp.blob();
  return { blob, filename };
}

function buildAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getExternalToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

// ----- 数据配置：归因 -----

export async function fetchLeadAttributions(
  params: LeadAttributionListQuery,
): Promise<LeadAttributionListResponse> {
  return apiClient.get("/daily-reports/data/lead-attributions", {
    params: compactParams(params),
  });
}

export async function upsertLeadAttributions(
  items: LeadReportAttributionUpsert[],
): Promise<LeadAttributionUpsertResponse> {
  return apiClient.put("/daily-reports/data/lead-attributions", { items });
}

// ----- 数据配置：完整度 -----

export async function fetchReportCompleteness(
  reportDay: string,
): Promise<ReportDataCompletenessOut> {
  return apiClient.get("/daily-reports/data-completeness", {
    params: { report_day: reportDay },
  });
}

// ----- 数据配置：广告日指标 -----

export async function fetchDailyAdMetrics(
  metricDay: string,
): Promise<DailyAdMetricListResponse> {
  return apiClient.get("/daily-reports/data/ad-metrics", {
    params: { metric_day: metricDay },
  });
}

export async function upsertDailyAdMetrics(
  items: DailyAdMetricUpsert[],
): Promise<DailyAdMetricUpsertResponse> {
  return apiClient.put("/daily-reports/data/ad-metrics", { items });
}

// ----- 数据配置：展厅价位 -----

export async function fetchMerchantReportProfile(): Promise<MerchantReportProfileOut> {
  return apiClient.get("/daily-reports/profile");
}

export async function upsertMerchantReportProfile(payload: {
  showroom_price_min_yuan: string | null;
  showroom_price_max_yuan: string | null;
}): Promise<MerchantReportProfileOut> {
  return apiClient.put("/daily-reports/profile", payload);
}
