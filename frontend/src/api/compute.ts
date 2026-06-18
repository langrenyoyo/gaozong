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
  ComputePackageListResponse,
  ComputeRechargeOrderRequest,
  ComputeRechargeOrderResponse,
  ComputeSummaryResponse,
  ComputeTransactionListResponse,
  ComputeTransactionQuery,
} from "./types";

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
