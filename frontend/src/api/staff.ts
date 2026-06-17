/**
 * 销售人员 API
 *
 * 对应 auto_wechat 路由：
 *   GET  /staff      → 销售列表
 *   POST /staff      → 新增销售
 */

import apiClient from "./client";
import type { Staff } from "./types";

/** 获取销售列表，可按状态过滤 */
export async function fetchStaffList(status?: string): Promise<Staff[]> {
  const params = status ? { status } : {};
  return apiClient.get("/staff", { params });
}

/** 新增销售人员 */
export async function createStaff(payload: {
  name: string;
  wechat_nickname?: string;
  wechat_id?: string;
  phone?: string;
}): Promise<Staff> {
  return apiClient.post("/staff", payload);
}
