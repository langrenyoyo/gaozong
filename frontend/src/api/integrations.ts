/**
 * 外部系统集成 API
 *
 * 对应 auto_wechat 路由：
 *   POST /integrations/douyin/sync-leads → 同步 douyinAPI 线索
 */

import apiClient from "./client";
import type { DouyinSyncResponse } from "./types";

interface SyncParams {
  dryRun?: boolean;
  autoAssign?: boolean;
  autoNotify?: boolean;
}

/**
 * 同步 douyinAPI 测试环境线索
 *
 * - dryRun=true（默认）：只预览，不写库
 * - dryRun=false：实际写入，需二次确认
 * - autoNotify=true（P8-3）：分配后自动搜索销售微信并发送通知
 */
export async function syncDouyinLeads(
  params: SyncParams = {},
): Promise<DouyinSyncResponse> {
  const { dryRun = true, autoAssign = false, autoNotify = false } = params;
  return apiClient.post("/integrations/douyin/sync-leads", {
    dry_run: dryRun,
    auto_assign: autoAssign,
    auto_notify: autoNotify,
  });
}
