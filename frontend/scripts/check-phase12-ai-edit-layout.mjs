// Phase 12 Task 10 Playwright 桌面/移动布局检查。
// 执行包 Task 10 Step 5：检查素材库与剪辑工作台桌面/移动端布局，不注入假素材。
//
// 拦截 9000 API：/auth/me 返回 mock 商户（含 auto_wechat:ai_edit）；/ai-edit/* 返回空列表。
// 访问 /ai-edit/materials + /ai-edit/editor，桌面(1280x800) + 移动(375x667) 截图，
// 断言关键 h1 渲染 + 无白屏。不连接真实 9000/9100/宝塔。
//
// 用法：node frontend/scripts/check-phase12-ai-edit-layout.mjs [dev_server_origin]
// 默认 http://127.0.0.1:5173

import { createRequire } from 'node:module';
import { mkdirSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

// playwright 非前端本地依赖；直接 require npx 缓存中已下载的库，免全局安装。
const _candidates = [
  'C:/Users/A/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright',
  'C:/Users/A/AppData/Local/npm-cache/_npx/420ff84f11983ee5/node_modules/playwright',
];
const _pwPath = _candidates.find((p) => existsSync(resolve(p, 'package.json')));
if (!_pwPath) throw new Error('未找到 playwright 库（请先 npx playwright --version 触发缓存）');
const _require = createRequire(import.meta.url);
const { chromium } = _require(_pwPath);

const ORIGIN = process.argv[2] || 'http://127.0.0.1:5173';
const SHOT_DIR = resolve(process.env.TEMP || '/tmp', 'phase12-ai-edit-layout-shots');
mkdirSync(SHOT_DIR, { recursive: true });

const MOCK_USER = {
  user_id: 'u1', username: 'mock-merchant', display_name: '模拟商户',
  auth_mode: 'mock', source_system: 'mock',
  merchant_id: 'm1', merchant_ids: ['m1'],
  permission_codes: ['auto_wechat:use', 'auto_wechat:ai_edit'],
  super_admin: false,
};

function routeMock(route) {
  const url = route.request().url();
  // 只拦截 9000 后端 API；5173 dev server 的页面/JS/CSS 资源原样放行
  if (!url.includes('127.0.0.1:9000') && !url.includes(':9000')) {
    return route.continue();
  }
  if (url.includes('/auth/me')) {
    return route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, data: MOCK_USER, message: 'success' }) });
  }
  // FIX2-1：浏览器获取 Local Agent token
  if (url.includes('/ai-edit/agent-token')) {
    return route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { token: 'mock-agent-token', merchant_id: 'm1' }, message: 'success' }) });
  }
  if (url.includes('/ai-edit/')) {
    return route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { total: 0, items: [] }, message: 'success' }) });
  }
  return route.continue();
}

const CASES = [
  { path: '/ai-edit/materials', expect: 'AI小高剪辑', name: 'materials' },
  { path: '/ai-edit/editor', expect: 'AI小高剪辑', name: 'editor' },
];
const VIEWPORTS = [
  { label: 'desktop', width: 1280, height: 800 },
  { label: 'mobile', width: 375, height: 667 },
];

const failures = [];

const browser = await chromium.launch();
try {
  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await context.newPage();
    const consoleErrors = [];
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', (e) => consoleErrors.push('PAGEERROR: ' + e.message));
    await page.route('**/*', routeMock);
    for (const c of CASES) {
      consoleErrors.length = 0;
      await page.goto(`${ORIGIN}${c.path}`, { waitUntil: 'networkidle' });
      let h1 = '';
      try {
        await page.waitForSelector('h1', { timeout: 8000 });
        h1 = await page.locator('h1').first().innerText().catch(() => '');
      } catch {
        await page.screenshot({ path: resolve(SHOT_DIR, `${c.name}-${vp.label}-debug.png`), fullPage: true });
        const body = await page.locator('body').innerText().catch(() => '');
        failures.push(`${vp.label}/${c.name}: h1 未渲染；body="${body.slice(0, 160)}"；errors=${consoleErrors.slice(0, 3).join(' | ')}`);
        continue;
      }
      if (!h1.includes(c.expect)) {
        failures.push(`${vp.label}/${c.name}: h1="${h1}" 期望含"${c.expect}"`);
      }
      const body = await page.locator('body').innerText().catch(() => '');
      if (body.includes('素材加载失败') || body.includes('数据加载失败')) {
        failures.push(`${vp.label}/${c.name}: 标准单层 API 响应被错误处理；body="${body.slice(0, 220)}"`);
      }
      if (c.name === 'materials' && !body.includes('暂无素材')) {
        failures.push(`${vp.label}/${c.name}: 空素材响应未进入正常空态`);
      }
      await page.screenshot({ path: resolve(SHOT_DIR, `${c.name}-${vp.label}.png`), fullPage: true });
    }
    await context.close();
  }

  const batchContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const batchPage = await batchContext.newPage();
  const batchImports = [];
  let materialListRequests = 0;
  await batchPage.route('**/*', (route) => {
    const url = route.request().url();
    if (url.includes('127.0.0.1:19000/agent/ai-edit/materials/import-stream')) {
      const materialId = new URL(url).searchParams.get('material_id');
      batchImports.push(materialId);
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            material_id: materialId,
            relative_path: `materials/${materialId}.mp4`,
            sha256: 'a'.repeat(64),
            size_bytes: 3,
          },
          message: 'success',
        }),
      });
    }
    if ((url.includes('127.0.0.1:9000') || url.includes(':9000')) && url.includes('/ai-edit/materials')) {
      materialListRequests += 1;
    }
    return routeMock(route);
  });

  await batchPage.goto(`${ORIGIN}/ai-edit/materials`, { waitUntil: 'networkidle' });
  await batchPage.locator('input[type="file"]').setInputFiles([
    { name: 'batch-a.mp4', mimeType: 'video/mp4', buffer: Buffer.from('aaa') },
    { name: 'batch-b.mp4', mimeType: 'video/mp4', buffer: Buffer.from('bbb') },
  ]);
  try {
    await batchPage.getByText('批量导入完成：2 个').waitFor({ timeout: 8000 });
  } catch {
    failures.push('batch-import: 未显示双文件批量导入成功汇总');
  }
  if (batchImports.length !== 2) {
    failures.push(`batch-import: 期望 2 次流式导入，实际 ${batchImports.length}`);
  }
  if (new Set(batchImports).size !== 2) {
    failures.push('batch-import: material_id 未保持批次内唯一');
  }
  if (materialListRequests !== 2) {
    failures.push(`batch-import: 素材列表应初始读取一次、批次结束刷新一次，实际 ${materialListRequests}`);
  }
  await batchContext.close();
} finally {
  await browser.close();
}

if (failures.length > 0) {
  console.error('FAIL: Phase 12 AI 剪辑布局检查未通过：');
  for (const f of failures) console.error('  - ' + f);
  process.exit(1);
}
console.log(`PASS: Phase 12 AI 剪辑桌面/移动布局检查通过（截图: ${SHOT_DIR}）`);
