/**
 * 自动化控制 API
 *
 * 对应 auto_wechat 路由：
 *   GET  /automation/status          → 查询自动化状态
 *   POST /automation/emergency-stop  → 紧急停止所有自动化
 *   POST /automation/resume          → 恢复自动化
 */

import apiClient from "./client";
import type { AutomationStatus } from "./types";

/** 查询自动化状态 */
export async function fetchAutomationStatus(): Promise<AutomationStatus> {
  return apiClient.get("/automation/status");
}

/** 紧急停止所有自动化 */
export async function emergencyStopAutomation(
  reason: string = "manual stop",
): Promise<{ success: boolean; message: string }> {
  return apiClient.post("/automation/emergency-stop", { reason });
}

/** 恢复自动化 */
export async function resumeAutomation(): Promise<{
  success: boolean;
  message: string;
}> {
  return apiClient.post("/automation/resume");
}
