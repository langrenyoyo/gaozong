// Phase 10 Task 6 前端算力合同（静态门禁）。
// 断言：API 两个冻结管理路径、商户流水只允许 7 个公开字段（不含内部计量与诊断字段）、
// 超管六能力比例编辑，且算力前端源码不出现错误路径 /api/compute/admin/markup-ratios、
// internal token 或 9100/9205 直连，不得持有内部令牌或直连内部服务。
// 管理员上浮配置类型继续保留；禁止项只扫算力代码（compute API + 两个页面），不管 pre-existing 的非算力文件。
// 用法：node scripts/check-phase10-compute-contract.mjs  退出码 0 = 通过。

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const srcRoot = resolve(scriptDir, '..', 'src');

function readFile(rel) {
  return readFileSync(resolve(srcRoot, rel), 'utf8');
}

function readInterface(source, name) {
  const match = source.match(new RegExp(`export interface ${name} \\{([\\s\\S]*?)\\n\\}`));
  if (!match) throw new Error(`types.ts 缺少 ${name} 接口`);
  return match[1];
}

const computeApi = readFile('api/compute.ts');
const typesTs = readFile('api/types.ts');
const superConfig = readFile('features/compute/pages/SuperComputeConfig.tsx');
const computeCenter = readFile('features/compute/pages/ComputeCenter.tsx');

// 管理员算力配置统一入口涉及的源码（Task 4 扩展读取范围）
const app = readFile('App.tsx');
const newcarRedirect = readFile('newcarRedirect.ts');
const sideNav = readFile('components/SideNav.tsx');
const capabilities = readFile('features/capabilities.ts');
const routes = readFile('features/routes.ts');
const computeRoutes = readFile('features/compute/routes.ts');
const indexPage = readFile('pages/Index.tsx');
const legacyRoutes = routes;

// 算力前端源码（禁止项只扫这一组，避免误伤 pre-existing 非算力文件）
const computeSources = [
  { path: 'api/compute.ts', content: computeApi },
  { path: 'api/types.ts', content: typesTs },
  { path: 'features/compute/pages/SuperComputeConfig.tsx', content: superConfig },
  { path: 'features/compute/pages/ComputeCenter.tsx', content: computeCenter },
];

// 1. API 层存在两个冻结的 9000 管理路径
if (!computeApi.includes('fetchAdminComputeMarkupRatios')) {
  throw new Error('compute.ts 缺少 fetchAdminComputeMarkupRatios（读取六能力比例）');
}
if (!computeApi.includes('updateAdminComputeMarkupRatio')) {
  throw new Error('compute.ts 缺少 updateAdminComputeMarkupRatio（编辑单行比例）');
}
if (!computeApi.includes('/admin/compute/markup-ratios')) {
  throw new Error('compute.ts 未调用冻结路径 /admin/compute/markup-ratios');
}

// 2. 商户流水只允许 7 个公开字段，不得暴露内部计量与诊断字段
const merchantTransactionType = readInterface(typesTs, 'ComputeTransaction');
const PUBLIC_FIELDS = [
  'id',
  'type',
  'type_label',
  'business_scene',
  'points_change',
  'balance_after',
  'created_at',
];

// 提取 ComputeTransaction 接口正文中的全部声明字段（形如 `name:` 或 `name?:`）
const declaredFields = [
  ...merchantTransactionType.matchAll(/^\s*([A-Za-z_][A-Za-z0-9_]*)\??:/gm),
].map((match) => match[1]);

const missingFields = PUBLIC_FIELDS.filter(
  (field) => !declaredFields.includes(field),
);
const extraFields = declaredFields.filter(
  (field) => !PUBLIC_FIELDS.includes(field),
);
if (missingFields.length || extraFields.length) {
  throw new Error(
    `ComputeTransaction 字段必须精确等于 7 个公开字段；缺少：${
      missingFields.join(',') || '无'
    }；多余：${extraFields.join(',') || '无'}`,
  );
}

// 私有字段：内部计量与诊断字段，既不得声明在接口，也不得被 ComputeCenter 读取
const PRIVATE_FIELDS = [
  'merchant_id',
  'tenant_id',
  'transaction_type',
  'delta_tokens',
  'balance_after_tokens',
  'source',
  'remark',
  'model',
  'agent_id',
  'conversation_id',
  'actual_tokens',
  'capability_key',
  'markup_basis_points',
  'usage_measurement_method',
  'prompt_tokens',
  'completion_tokens',
  'cached_tokens',
  'llm_call_stage',
];
for (const field of PRIVATE_FIELDS) {
  if (merchantTransactionType.includes(`${field}:`)) {
    throw new Error(`ComputeTransaction 不得暴露内部字段：${field}`);
  }
}

for (const access of PRIVATE_FIELDS.map((field) => `tx.${field}`)) {
  if (computeCenter.includes(access)) {
    throw new Error(`ComputeCenter 不得读取内部字段：${access}`);
  }
}
for (const heading of ['类型', '使用场景', '算力点数变动', '变动后余额', '时间']) {
  if (!computeCenter.includes(`>${heading}<`)) {
    throw new Error(`ComputeCenter 缺少商户流水列：${heading}`);
  }
}

// 2b. 冻结类型存在
if (!typesTs.includes('ComputeMarkupRatio')) {
  throw new Error('types.ts 缺少 ComputeMarkupRatio 类型');
}
if (!typesTs.includes('ComputeCapabilityKey')) {
  throw new Error('types.ts 缺少 ComputeCapabilityKey 类型');
}

// 3. 超管页读取、编辑六能力比例（不嵌套卡片的独立区）
if (!superConfig.includes('能力上浮')) {
  throw new Error('SuperComputeConfig 缺少"能力上浮比例"区');
}
for (const cap of ['douyin-cs', 'leads', 'agents', 'wechat-assistant', 'compute', 'knowledge']) {
  if (!superConfig.includes(cap)) {
    throw new Error(`SuperComputeConfig 缺少冻结能力：${cap}`);
  }
}

// 4. 算力前端源码禁止项扫描（只扫算力文件，避免误伤 pre-existing 非算力文件）
const FORBIDDEN = [
  { needle: '/api/compute/admin/markup-ratios', reason: '错误路径 /api/compute/admin/markup-ratios（应为 /admin/compute/markup-ratios）' },
  { needle: 'COMPUTE_INTERNAL_TOKEN', reason: '算力前端出现 internal token 字样（internal token 不得进前端）' },
  { needle: 'X-Internal-Token', reason: '算力前端出现 X-Internal-Token 头（internal token 不得进前端）' },
  { needle: '127.0.0.1:9100', reason: '算力前端直连 9100（须走 9000 代理）' },
  { needle: '127.0.0.1:9205', reason: '算力前端直连 9205（须走 9000 代理）' },
  { needle: 'localhost:9100', reason: '算力前端直连 9100（须走 9000 代理）' },
];
for (const { needle, reason } of FORBIDDEN) {
  for (const { path, content } of computeSources) {
    if (content.includes(needle)) {
      throw new Error(`${reason}，命中文件：${path}`);
    }
  }
}

// 5. 管理员算力配置统一入口静态合同（Task 4 红灯）
if (!app.includes('path: "/admin/compute-config"')) throw new Error('缺少管理员算力配置路由');
if (!app.includes('PERMISSIONS.adminComputeConfig')) throw new Error('管理员路由未绑定精确权限');
if (!sideNav.includes('id: "admin-compute-config"')) throw new Error('管理员侧栏缺少算力配置');
if (!indexPage.includes('superActiveNav === "admin-compute-config"')) throw new Error('Index 缺少管理员算力配置分发');
if (capabilities.includes('id: "compute-packages"')) throw new Error('普通算力导航仍包含套餐配置');
if (capabilities.includes('id: "compute-markup-ratios"')) throw new Error('普通算力导航仍包含计费比例');
if (!legacyRoutes.includes('{ from: "/compute/packages", to: "/admin/compute-config?view=packages" }')) throw new Error('套餐旧地址未兼容跳转');
if (!legacyRoutes.includes('{ from: "/compute/markup-ratios", to: "/admin/compute-config?view=ratios" }')) throw new Error('比例旧地址未兼容跳转');
for (const label of ['计费比例', '套餐管理', '商户发放']) {
  if (!superConfig.includes(label)) throw new Error(`算力配置缺少视图：${label}`);
}
if (superConfig.includes('<ModuleTabs')) throw new Error('算力配置仍使用路由式二级导航');
if (superConfig.includes('/admin/compute/markup-ratios')) throw new Error('页面显示内部接口路径');
if (superConfig.includes('seed')) throw new Error('页面显示内部初始化术语');

console.log('Phase 10 算力前端合同：PASS');
