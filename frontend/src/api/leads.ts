/**
 * 线索 API
 *
 * 对应 auto_wechat 路由：
 *   GET  /leads              → 线索列表
 *   GET  /leads/{id}         → 单条线索
 *   POST /leads              → 创建线索
 *   POST /leads/{id}/assign  → 分配销售
 */

import apiClient from "./client";
import type { Lead } from "./types";

/** 获取线索列表，可按状态过滤 */
export async function fetchLeads(status?: string): Promise<Lead[]> {
  const params = status ? { status } : {};
  return apiClient.get("/leads", { params });
}

/** 获取单条线索 */
export async function fetchLead(id: number): Promise<Lead> {
  return apiClient.get(`/leads/${id}`);
}

/** 创建线索（P0-FE-MAIN-2A：测试用） */
export async function createLead(payload: {
  source?: string;
  customer_name?: string;
  content?: string;
  source_id?: string;
}): Promise<Lead> {
  return apiClient.post("/leads", payload);
}

/** 分配线索给销售 */
export async function assignLead(leadId: number, staffId: number): Promise<Lead> {
  return apiClient.post(`/leads/${leadId}/assign`, { staff_id: staffId });
}
