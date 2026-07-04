import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src');
const requiredFiles = [
  'api/adminAutoreplyRollout.ts',
  'pages/AdminAutoreplyRolloutPage.tsx',
];

for (const file of requiredFiles) {
  const path = resolve(root, file);
  if (!existsSync(path)) {
    throw new Error(`缺少文件：${file}`);
  }
}

const api = readFileSync(resolve(root, 'api/adminAutoreplyRollout.ts'), 'utf8');
const page = readFileSync(resolve(root, 'pages/AdminAutoreplyRolloutPage.tsx'), 'utf8');
const sideNav = readFileSync(resolve(root, 'components/SideNav.tsx'), 'utf8');
const app = readFileSync(resolve(root, 'App.tsx'), 'utf8');
const capabilities = readFileSync(resolve(root, 'features/capabilities.ts'), 'utf8');

const requiredApiNames = [
  'getAutoreplyRolloutSummary',
  'updateAutoreplyRolloutGlobal',
  'listAutoreplyRolloutAccounts',
  'updateAutoreplyRolloutAccount',
  'listAutoreplyWhitelist',
  'addAutoreplyWhitelist',
  'deleteAutoreplyWhitelist',
  'listAutoreplyRuns',
];
for (const name of requiredApiNames) {
  if (!api.includes(name)) throw new Error(`API client 缺少：${name}`);
}

const requiredPageTexts = [
  '自动回复灰度与发送控制',
  '系统级真实发送熔断中，前端配置不会触发真实发送。',
  '确认开启全量自动回复',
  '一键暂停真实发送',
  '无权限访问',
];
for (const text of requiredPageTexts) {
  if (!page.includes(text)) throw new Error(`页面缺少文案：${text}`);
}

for (const forbidden of ['force_send', 'bypass', 'ignore_gate', 'set_final_auto_send', 'raw_response_json']) {
  if (page.includes(forbidden)) throw new Error(`页面包含禁止字段：${forbidden}`);
}

if (!sideNav.includes('admin-autoreply-rollout')) {
  throw new Error('侧栏缺少自动回复灰度入口');
}
if (!sideNav.includes('PERMISSIONS.adminAutoreply') || !capabilities.includes('auto_wechat:admin:autoreply')) {
  throw new Error('侧栏缺少自动回复灰度专属权限码');
}
if (!capabilities.includes('hasAdminPermission')) {
  throw new Error('权限工具缺少 hasAdminPermission');
}
if (!app.includes('/admin/autoreply-rollout')) {
  throw new Error('路由缺少 /admin/autoreply-rollout');
}
