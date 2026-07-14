// Phase 9 Task 9 回访前端合同红灯检查。
// 验证：文件存在、API 函数/路径、权限码、route/nav/默认跳转/canAccessPath、newcarRedirect 白名单、
//       PUT reason 必填、置信阈值边界、禁 any、页面不含发送/重试命令。
// 用法：node scripts/check-phase9-return-visits-contract.mjs  退出码 0 = 通过。

import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src');

// 1. 必需文件存在
const requiredFiles = [
  'api/adminReturnVisits.ts',
  'pages/AdminReturnVisitsPage.tsx',
];
for (const file of requiredFiles) {
  if (!existsSync(resolve(root, file))) {
    throw new Error(`缺少文件：${file}`);
  }
}

const api = readFileSync(resolve(root, 'api/adminReturnVisits.ts'), 'utf8');
const page = readFileSync(resolve(root, 'pages/AdminReturnVisitsPage.tsx'), 'utf8');
const app = readFileSync(resolve(root, 'App.tsx'), 'utf8');
const sideNav = readFileSync(resolve(root, 'components/SideNav.tsx'), 'utf8');
const indexPage = readFileSync(resolve(root, 'pages/Index.tsx'), 'utf8');
const capabilities = readFileSync(resolve(root, 'features/capabilities.ts'), 'utf8');
const redirect = readFileSync(resolve(root, 'newcarRedirect.ts'), 'utf8');

// 2. API 函数齐全
const requiredApiNames = [
  'getReturnVisitPrompts',
  'updateReturnVisitPrompt',
  'listReturnVisitRuns',
  'getReturnVisitRunsStats',
  'getReturnVisitRun',
];
for (const name of requiredApiNames) {
  if (!api.includes(name)) throw new Error(`API client 缺少函数：${name}`);
}

// 3. API 路径齐全
for (const path of [
  '/admin/return-visit/prompts',
  '/admin/return-visit/runs',
  '/admin/return-visit/runs/stats',
]) {
  if (!api.includes(path)) throw new Error(`API 路径缺少：${path}`);
}

// 4. 禁 any（类型注解 / as any / <any>；注释里"禁止 any"不算）
const anyPattern = /(:\s*any\b|as\s+any\b|<any>)/;
if (anyPattern.test(api) || anyPattern.test(page)) {
  throw new Error('API 或页面使用了 any 类型（禁止，JSON 审计字段请用 Record<string, unknown>）');
}

// 5. 权限码登记
if (!capabilities.includes('adminReturnVisitPrompts')) {
  throw new Error('capabilities 缺少 adminReturnVisitPrompts 权限常量');
}
if (!capabilities.includes('auto_wechat:admin:return_visit_prompts')) {
  throw new Error('capabilities 缺少 auto_wechat:admin:return_visit_prompts 权限码');
}

// 6. App：route + 默认跳转 + canAccessPath 守卫
if (!app.includes('"/admin/return-visits"')) {
  throw new Error('App adminRoutes 缺少 /admin/return-visits');
}
if (!app.includes('PERMISSIONS.adminReturnVisitPrompts)) return "/admin/return-visits"')) {
  throw new Error('默认管理员跳转未指向 /admin/return-visits（仍指向 no-local-feature）');
}
if (!app.includes('pathname === "/admin/return-visits"')) {
  throw new Error('canAccessPath 缺少 /admin/return-visits 权限守卫');
}

// 7. SideNav：入口 + 图标 + 权限码
if (!sideNav.includes('"admin-return-visits"')) throw new Error('SideNav 缺少 admin-return-visits 入口');
if (!sideNav.includes('MessagesSquareIcon')) throw new Error('SideNav 缺少 MessagesSquareIcon 图标');
if (!sideNav.includes('PERMISSIONS.adminReturnVisitPrompts')) throw new Error('SideNav 缺少回访权限码');

// 8. Index：页面引用 + 渲染分支
if (!indexPage.includes('AdminReturnVisitsPage')) throw new Error('Index 缺少 AdminReturnVisitsPage 引用');
if (!indexPage.includes('superActiveNav === "admin-return-visits"')) {
  throw new Error('Index 缺少 admin-return-visits 渲染分支');
}

// 9. newcarRedirect 白名单
if (!redirect.includes('/admin/return-visits')) {
  throw new Error('newcarRedirect 白名单缺少 /admin/return-visits');
}

// 10. PUT reason 必填校验
if (!page.includes('变更原因必填')) throw new Error('页面缺少 PUT reason 必填校验');

// 11. 置信阈值边界 0.5 / 1.0
if (!page.includes('0.5') || !page.includes('1.0')) {
  throw new Error('页面缺少置信阈值边界（0.5 / 1.0）');
}

// 12. 页面不含发送/重试命令（仅查操作类命令词；状态展示"已发送"不算命令）
const forbiddenCommands = ['立即发送', '重试', 'retry', 'resend', 'force_send', 'bypass', 'trigger-now'];
for (const bad of forbiddenCommands) {
  if (page.includes(bad)) throw new Error(`页面包含禁止的发送/重试命令：${bad}`);
}

// 13. 两 tab + 编辑抽屉 + 只读详情
for (const text of ['提示词配置', '运行记录', '编辑', '详情']) {
  if (!page.includes(text)) throw new Error(`页面缺少必要文案：${text}`);
}

console.log('Phase 9 回访前端合同检查通过 ✓');
