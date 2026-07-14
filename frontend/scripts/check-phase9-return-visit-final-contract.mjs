// Phase 9 Task 10 前端最终合同（静态门禁）。
// 互补 Task 9 的 contract：trigger_text 零回显、无发送写端点、审计字段类型、中文映射完整。
// 用法：node scripts/check-phase9-return-visit-final-contract.mjs  退出码 0 = 通过。

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src');

const api = readFileSync(resolve(root, 'api/adminReturnVisits.ts'), 'utf8');
const page = readFileSync(resolve(root, 'pages/AdminReturnVisitsPage.tsx'), 'utf8');

// 1. trigger_text 不得出现在 API 类型或页面（客户回复原文零回显合同）
if (api.includes('trigger_text')) {
  throw new Error('API 类型含 trigger_text（禁止回显客户回复原文）');
}
if (page.includes('trigger_text')) {
  throw new Error('页面引用 trigger_text（禁止回显客户回复原文）');
}

// 1b. trigger_message_fp 必须在 API 类型与页面详情（F8：指纹非原文，列表与详情须返回）
if (!api.includes('trigger_message_fp')) {
  throw new Error('API 类型缺少 trigger_message_fp（F8：列表与详情须返回触发指纹）');
}
if (!page.includes('触发指纹')) {
  throw new Error('页面详情抽屉缺少"触发指纹"展示（F8）');
}

// 1c. 禁止旧漂移路径（C11：冻结连字符 /admin/return-visit-prompts|runs）
for (const bad of ['/admin/return-visit/prompts', '/admin/return-visit/runs']) {
  if (api.includes(bad)) throw new Error(`API 含旧漂移路径：${bad}（应为连字符）`);
}

// 2. API 不得定义发送/重试类 POST 端点（本阶段无写发送命令）
if (api.includes('apiClient.post')) {
  throw new Error('API 含 apiClient.post（回访管理端不应有 POST 写发送端点）');
}
for (const bad of ['/send', '/retry', '/requeue', '/resend']) {
  if (api.includes(bad)) throw new Error(`API 含发送/重试路径：${bad}`);
}

// 3. 审计 JSON 字段类型严格（gate_results 用 Record<string, unknown>，risk_flags 用 string[]）
if (!api.includes('gate_results: Record<string, unknown>')) {
  throw new Error('API 类型 gate_results 必须为 Record<string, unknown>（禁 any）');
}
if (!api.includes('risk_flags: string[]')) {
  throw new Error('API 类型 risk_flags 必须为 string[]');
}

// 4. 三键场景完整
for (const key of [
  'retain_contact_conversion',
  'finance_plan_followup',
  'silent_customer_wakeup',
]) {
  if (!page.includes(key)) throw new Error(`页面缺少场景 key：${key}`);
}

// 5. 状态 / 判定来源 / 风险码稳定中文映射
for (const text of [
  '待判定',
  '已发送',
  '已阻断',
  '大模型',
  '关键词兜底',
  '模型拒答',
  '提示词注入',
]) {
  if (!page.includes(text)) throw new Error(`页面缺少中文映射：${text}`);
}

// 6. 两 tab + 编辑/详情抽屉
for (const text of ['提示词配置', '运行记录']) {
  if (!page.includes(text)) throw new Error(`页面缺少 tab：${text}`);
}

// 7. 置信阈值边界 0.5 / 1.0（与后端 PUT 校验一致）
if (!page.includes('0.5') || !page.includes('1.0')) {
  throw new Error('页面缺少置信阈值边界 0.5/1.0');
}

// 8. 页面无发送/重试命令按钮（操作类；状态展示"已发送"不算命令）
for (const bad of ['立即发送', '重试', 'retry', 'resend', 'force_send', 'bypass', 'trigger-now']) {
  if (page.includes(bad)) throw new Error(`页面含禁止的发送/重试命令：${bad}`);
}

console.log('Phase 9 回访前端最终合同检查通过 ✓');
