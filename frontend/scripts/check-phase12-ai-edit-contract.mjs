// Phase 12 Task 9 AI 剪辑前端合同（静态门禁）。
// 冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §12。
// 执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 9。
//
// 断言：
// - 两个页面进入 auto_wechat:ai_edit 导航（权限码绑定）。
// - 不出现一键过审入口、假素材、假任务、假统计。
// - 9000 API 与 127.0.0.1:19000 Local API 分开（apiClient vs localApi）。
// - 页面存在导入、分析、增稳、取消、重试、720P 草稿、1080P 成片、回收站状态。
// - 前端不持有 internal token、不直连 9100/Milvus、不接受前端自报 merchant_id。
//
// 用法：node frontend/scripts/check-phase12-ai-edit-contract.mjs  退出码 0 = 通过。

import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const srcRoot = resolve(scriptDir, '..', 'src');

function readFile(rel) {
  const full = resolve(srcRoot, rel);
  if (!existsSync(full)) {
    throw new Error(`文件缺失：${rel}（AI 剪辑前端尚未实现）`);
  }
  return readFileSync(full, 'utf8');
}

// 1. 功能目录与核心文件存在
const types = readFile('features/ai-edit/types.ts');
const api = readFile('features/ai-edit/api.ts');
const localApi = readFile('features/ai-edit/localApi.ts');
const routes = readFile('features/ai-edit/routes.ts');
const materialLib = readFile('features/ai-edit/pages/MaterialLibrary.tsx');
const videoEditor = readFile('features/ai-edit/pages/AiVideoEditor.tsx');

// 2. 两个页面进入 auto_wechat:ai_edit 导航
const capabilities = readFile('features/capabilities.ts');
if (!capabilities.includes('auto_wechat:ai_edit')) {
  throw new Error('capabilities.ts 缺少 auto_wechat:ai_edit 权限码');
}
// routes.ts 注册两个 ai-edit 路径
if (!routes.includes('/ai-edit/materials')) {
  throw new Error('routes.ts 缺少 /ai-edit/materials 路径');
}
if (!routes.includes('/ai-edit/editor')) {
  throw new Error('routes.ts 缺少 /ai-edit/editor 路径');
}
// features/routes.ts 引入 ai-edit routes
const featureRoutes = readFile('features/routes.ts');
if (!featureRoutes.includes('ai-edit/routes') && !featureRoutes.includes('aiEditRoutes')) {
  throw new Error('features/routes.ts 未注册 ai-edit 路由');
}

// 3. AiEditJobStatus 冻结枚举
const requiredStatuses = [
  '"queued"', '"running"', '"review_required"',
  '"cancel_requested"', '"cancelled"', '"failed"', '"succeeded"',
];
for (const s of requiredStatuses) {
  if (!types.includes(s)) {
    throw new Error(`types.ts 缺少 AiEditJobStatus 枚举值 ${s}`);
  }
}

// 4. 9000 API 与 127.0.0.1:19000 Local API 分开
if (!localApi.includes('127.0.0.1:19000') && !localApi.includes('LOCAL_AI_EDIT_BASE_URL')) {
  throw new Error('localApi.ts 未使用 127.0.0.1:19000 Local API 基址');
}
// localApi 不应使用 apiClient（9000 客户端）
if (localApi.includes('apiClient')) {
  throw new Error('localApi.ts 误用 apiClient（应直连 127.0.0.1:19000）');
}
// api.ts 应使用 apiClient（9000）
if (!api.includes('apiClient')) {
  throw new Error('api.ts 未使用 apiClient（9000 API）');
}
if (api.includes('resp.data.data')) {
  throw new Error('api.ts 重复解包 apiClient 响应，运行时会得到 undefined');
}
if (!api.includes('return resp.data as T')) {
  throw new Error('api.ts 未按 apiClient 响应拦截合同读取 envelope.data');
}

// 5. 页面存在关键能力（导入/分析/增稳/取消/重试/720P/1080P/回收站）
const pageBlob = materialLib + '\n' + videoEditor;
const requiredCapabilities = [
  '导入', '分析', '增稳', '取消', '重试', '720', '1080', '回收站',
];
const missing = requiredCapabilities.filter((c) => !pageBlob.includes(c));
if (missing.length > 0) {
  throw new Error(`页面缺少关键能力: ${missing.join('、')}`);
}

// 6. 禁止：一键过审入口、假素材、假任务、假统计
const forbiddenPatterns = [
  { pat: '一键过审', msg: '页面出现一键过审入口（已 CANCELLED_BY_CUSTOMER）' },
  { pat: 'mockMaterial', msg: '页面出现假素材 mockMaterial' },
  { pat: 'fakeJob', msg: '页面出现假任务 fakeJob' },
  { pat: 'mockStats', msg: '页面出现假统计 mockStats' },
];
const aiEditSources = [
  { path: 'features/ai-edit/pages/MaterialLibrary.tsx', content: materialLib },
  { path: 'features/ai-edit/pages/AiVideoEditor.tsx', content: videoEditor },
  { path: 'features/ai-edit/api.ts', content: api },
  { path: 'features/ai-edit/localApi.ts', content: localApi },
  { path: 'features/ai-edit/types.ts', content: types },
];
for (const { path, content } of aiEditSources) {
  for (const { pat, msg } of forbiddenPatterns) {
    if (content.includes(pat)) {
      throw new Error(`${path}: ${msg}`);
    }
  }
}

// 7. 禁止：前端持有 internal token / 直连 9100 / Milvus / 前端自报 merchant_id
for (const { path, content } of aiEditSources) {
  if (content.includes('COMPUTE_INTERNAL_TOKEN') || content.includes('XG_DOUYIN_AI_CS_SERVICE_TOKEN')) {
    throw new Error(`${path}: 前端持有 internal token（违反设计 §9）`);
  }
  if (/127\.0\.0\.1:9100|localhost:9100/.test(content)) {
    throw new Error(`${path}: 前端直连 9100（违反设计，9100 须由 9000 代理）`);
  }
  if (/milvus/i.test(content) && !content.includes('Milvus 是')) {
    throw new Error(`${path}: 前端直连 Milvus（违反设计 §9）`);
  }
  // 前端不得自报 merchant_id 作为可信字段（Local API 用 token 映射）
  if (/merchant_id:\s*["']m1["']|merchantId:\s*["']m1["']/.test(content) && path.includes('localApi')) {
    throw new Error(`${path}: Local API 前端自报 merchant_id（违反设计，须由 token 映射）`);
  }
}

console.log('✓ Phase 12 AI 剪辑前端合同通过');
process.exit(0);
