/**
 * 销售人员 API
 *
 * 对应 auto_wechat 路由：
 *   GET    /staff
 *   POST   /staff
 *   PUT    /staff/{staff_id}
 *   POST   /staff/{staff_id}/enable
 *   POST   /staff/{staff_id}/disable
 *   DELETE /staff/{staff_id}
 */

import apiClient from "./client";
import type { Staff } from "./types";

export type StaffStatusFilter = "active" | "disabled" | "deleted" | "all";

export interface StaffListParams {
  status?: StaffStatusFilter;
  keyword?: string;
  include_deleted?: boolean;
}

export interface StaffPayload {
  name: string;
  wechat_nickname?: string;
  wechat_id?: string;
  phone?: string;
  status?: "active" | "disabled" | "deleted";
}

/** 获取销售列表，可按状态和关键词过滤 */
export async function fetchStaffList(params?: StaffListParams | string): Promise<Staff[]> {
  const normalizedParams = typeof params === "string" ? { status: params } : params;
  return apiClient.get("/staff", { params: normalizedParams });
}

/** 新增销售人员 */
export async function createStaff(payload: StaffPayload): Promise<Staff> {
  return apiClient.post("/staff", payload);
}

/** 编辑销售人员 */
export async function updateStaff(staffId: number, payload: StaffPayload): Promise<Staff> {
  return apiClient.put(`/staff/${staffId}`, payload);
}

/** 启用销售人员 */
export async function enableStaff(staffId: number): Promise<Staff> {
  return apiClient.post(`/staff/${staffId}/enable`);
}

/** 停用销售人员 */
export async function disableStaff(staffId: number): Promise<Staff> {
  return apiClient.post(`/staff/${staffId}/disable`);
}

/** 软删除销售人员 */
export async function deleteStaff(staffId: number): Promise<Staff> {
  return apiClient.delete(`/staff/${staffId}`);
}
