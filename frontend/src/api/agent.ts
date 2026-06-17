/**
 * Agent status API.
 *
 * Corresponds to auto_wechat:
 *   GET /agent/status -> read-only Local Agent safety status
 */

import apiClient from "./client";
import type { AgentStatusResponse } from "./types";

/** Fetch read-only Agent status for guarding high-risk WeChat actions. */
export async function fetchAgentStatus(): Promise<AgentStatusResponse> {
  return apiClient.get("/agent/status");
}
