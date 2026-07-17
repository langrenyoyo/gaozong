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
for (const field of PUBLIC_FIELDS) {
  if (!merchantTransactionType.includes(`${field}:`)) {
    throw new Error(`ComputeTransaction 缺少商户公开字段：${field}`);
  }
}

const PRIVATE_FIELDS = [
  'merchant_id',
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

console.log('Phase 10 算力前端合同：PASS');
