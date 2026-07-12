/**
 * Phase 8 日报前端合同检查（Task 8 Step 5）。
 *
 * 断言：
 * - 日报路由和能力入口存在；
 * - 五个 tab（报表任务/待归因线索/数据完整度/广告日数据/展厅价位）存在；
 * - 两条固定事实提示存在（重算口径 + 样例未验收）；
 * - 待归因线索使用服务端分页；
 * - 下载从响应头取文件名；
 * - 日报相关文件无 file_storage_key、服务器绝对路径、internal token、“已发送”；
 * - 广告日数据 type 不含广告 ID 明细输入。
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const read = (rel) => readFileSync(resolve(root, rel), "utf8");

const failures = [];
const assertContains = (text, needle, msg) => {
  if (!text.includes(needle)) failures.push(`缺少：${msg}（未找到 "${needle}"）`);
};
const assertNotContains = (text, needle, msg) => {
  if (text.includes(needle)) failures.push(`禁区命中：${msg}（出现 "${needle}"）`);
};

const dailyReportsApi = read("src/api/dailyReports.ts");
const types = read("src/api/types.ts");
const page = read("src/features/wechat-assistant/pages/DailyReports.tsx");
const routes = read("src/features/wechat-assistant/routes.ts");
const caps = read("src/features/capabilities.ts");

// 1. 路由与能力入口
assertContains(routes, "/wechat-assistant/daily-reports", "日报路由");
assertContains(caps, "wechat-daily-reports", "日报 nav id");

// 2. 五个 tab
for (const label of ["报表任务", "待归因线索", "数据完整度", "广告日数据", "展厅价位"]) {
  assertContains(page, label, `tab：${label}`);
}

// 3. 两条固定事实提示
assertContains(page, "历史重生成按当前归因和当前跟进状态重算", "重算口径提示");
assertContains(page, "字段顺序已按需求冻结，样例视觉尚未验收", "样例未验收提示");

// 4. 待归因分页
assertContains(page, "fetchLeadAttributions", "待归因分页 API");
assertContains(page, "page_size", "分页参数");

// 5. 下载走响应头文件名
assertContains(dailyReportsApi, "content-disposition", "下载响应头文件名");

// 6. 禁区词扫描（日报相关文件集合）
const allDaily = [dailyReportsApi, types, page, routes, caps].join("\n");
for (const word of [
  "file_storage_key",
  "generation_token",
  "DAILY_REPORT_STORAGE",
  "/data/daily_reports",
  "已发送",
]) {
  assertNotContains(allDaily, word, word);
}

// 7. 广告日数据不含广告 ID 明细输入
const adBlock = /interface DailyAdMetricUpsert \{[\s\S]*?\}/.exec(types);
if (!adBlock) {
  failures.push("未找到 DailyAdMetricUpsert type");
} else if (adBlock[0].includes("ad_id") || adBlock[0].includes("material_id")) {
  failures.push("DailyAdMetricUpsert 不应含广告 ID/素材 ID 明细输入");
}

if (failures.length > 0) {
  console.error("Phase 8 日报合同检查失败：");
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log("Phase 8 日报合同检查通过 ✅");
