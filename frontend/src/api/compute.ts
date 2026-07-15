/**
 * 小高算力 API（P1-COMPUTE-FE-1）。
 *
 * 对应 auto_wechat 商户侧路由：
 *   GET  /compute/summary         → 余额 + 今日/昨日/累计消耗
 *   GET  /compute/transactions     → Token 明细分页
 *   GET  /compute/packages         → 启用套餐列表
 *   POST /compute/recharge-orders  → 创建充值订单（一期 mock，不接真实支付）
 *
 * 后端统一返回 { success, data, message }，client.ts 响应拦截器已返回 response.data，
 * 因此封装函数返回完整 Response 类型，调用方通过 .data 取实际载荷。
 */

import apiClient from "./client";
import type {
  ComputeCapabilityKey,
  ComputeMarkupRatioListResponse,
  ComputeMarkupRatioResponse,
  ComputeMarkupRatioUpdateRequest,
  ComputePackage,
  ComputePackageListResponse,
  ComputeRechargeOrderRequest,
  ComputeRechargeOrderResponse,
  ComputeSummaryResponse,
  ComputeTransactionListResponse,
  ComputeTransactionQuery,
} from "./types";

/** 管理员创建算力套餐请求（POST /admin/compute/packages）。 */
export interface ComputePackageCreateRequest {
  name: string;
  price_yuan: number;
  token_amount: number;
  enabled?: boolean;
}

/** 管理员更新算力套餐请求（PUT /admin/compute/packages/{id}）。 */
export interface ComputePackageUpdateRequest {
  name?: string;
  price_yuan?: number;
  token_amount?: number;
  enabled?: boolean;
}

/** 管理员套餐详情响应（POST/PUT /admin/compute/packages）。 */
export interface ComputePackageResponse {
  success: boolean;
  data: ComputePackage;
  message: string;
}

/** 管理员给商户充值 Token 请求。 */
export interface ComputeAdminRechargeRequest {
  tokens: number;
  remark?: string;
}

/** 管理员给商户发放套餐请求。 */
export interface ComputeGrantPackageRequest {
  package_id: number;
}

/** 过滤空值参数，避免发送 undefined/null/空字符串。 */
function compactParams(
  params: ComputeTransactionQuery,
): Record<string, string | number> {
  const result: Record<string, string | number> = {};
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    result[key] = value;
  });
  return result;
}

/** 获取算力余额与今日/昨日/累计消耗（GET /compute/summary）。 */
export async function fetchComputeSummary(): Promise<ComputeSummaryResponse> {
  return apiClient.get("/compute/summary");
}

/** 获取 Token 明细分页列表（GET /compute/transactions）。 */
export async function fetchComputeTransactions(
  params: ComputeTransactionQuery = {},
): Promise<ComputeTransactionListResponse> {
  return apiClient.get("/compute/transactions", {
    params: compactParams(params),
  });
}

/** 获取启用套餐列表（GET /compute/packages）。 */
export async function fetchComputePackages(): Promise<ComputePackageListResponse> {
  return apiClient.get("/compute/packages");
}

/** 创建充值订单（POST /compute/recharge-orders，一期 mock，不接真实支付）。 */
export async function createComputeRechargeOrder(
  payload: ComputeRechargeOrderRequest,
): Promise<ComputeRechargeOrderResponse> {
  return apiClient.post("/compute/recharge-orders", payload);
}

/** 管理员获取全部套餐（GET /admin/compute/packages，包含禁用套餐）。 */
export async function fetchAdminComputePackages(): Promise<ComputePackageListResponse> {
  return apiClient.get("/admin/compute/packages");
}

/** 管理员创建套餐（POST /admin/compute/packages）。 */
export async function createAdminComputePackage(
  payload: ComputePackageCreateRequest,
): Promise<ComputePackageResponse> {
  return apiClient.post("/admin/compute/packages", payload);
}

/** 管理员更新套餐（PUT /admin/compute/packages/{package_id}）。 */
export async function updateAdminComputePackage(
  packageId: number,
  payload: ComputePackageUpdateRequest,
): Promise<ComputePackageResponse> {
  return apiClient.put(`/admin/compute/packages/${packageId}`, payload);
}

/** 管理员给指定商户后台充值 Token（不代表真实支付）。 */
export async function rechargeMerchantCompute(
  merchantId: string,
  payload: ComputeAdminRechargeRequest,
): Promise<ComputeSummaryResponse> {
  return apiClient.post(`/admin/merchants/${encodeURIComponent(merchantId)}/compute/recharge`, payload);
}

/** 管理员给指定商户发放套餐（不代表真实支付）。 */
export async function grantMerchantComputePackage(
  merchantId: string,
  payload: ComputeGrantPackageRequest,
): Promise<ComputeSummaryResponse> {
  return apiClient.post(`/admin/merchants/${encodeURIComponent(merchantId)}/compute/grant-package`, payload);
}

/**
 * Phase 10 §0.2：读取六能力上浮比例（GET /admin/compute/markup-ratios）。
 *
 * 权限：auto_wechat:admin:compute_config / super_admin。前端不持有 internal token，
 * 不直连 9100/9205，只走 9000 管理路径。
 */
export async function fetchAdminComputeMarkupRatios(): Promise<ComputeMarkupRatioListResponse> {
  return apiClient.get("/admin/compute/markup-ratios");
}

/**
 * Phase 10 §0.2：更新单能力上浮比例与启用位（PUT /admin/compute/markup-ratios/{capability_key}）。
 *
 * markup_basis_points 由调用方用字符串算法转基点后传入（禁浮点）。超后端技术边界由后端返回稳定错误。
 */
export async function updateAdminComputeMarkupRatio(
  capabilityKey: ComputeCapabilityKey,
  payload: ComputeMarkupRatioUpdateRequest,
): Promise<ComputeMarkupRatioResponse> {
  return apiClient.put(`/admin/compute/markup-ratios/${capabilityKey}`, payload);
}
