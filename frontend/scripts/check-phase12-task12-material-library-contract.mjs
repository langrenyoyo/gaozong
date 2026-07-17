// Phase 12 Task 12 素材库真实闭环前端合同（静态门禁）。
// 执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
// Task 12-1 Step 4。
//
// 断言不可变区域与 Task 12-9 待新增组件引用：
// - 全局导航、AI小高剪辑 标题栏、ModuleTabs 不变。
// - 状态文案不得出现 "pending...处理中" 这类把 pending 当展示态的错误文案。
// - 三个标签页：私有素材 / 平台公共 / 回收站。
// - 引用 MaterialDetail / ImportQueue 组件（Task 12-9 创建，当前缺失 → 红灯）。
//
// 用法：node frontend/scripts/check-phase12-task12-material-library-contract.mjs  退出码 0 = 通过。

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

const materialLib = readFile('features/ai-edit/pages/MaterialLibrary.tsx');

// 1. 不可变区域：全局导航、标题栏、ModuleTabs
if (!/<ModuleTabs/.test(materialLib)) {
  throw new Error('MaterialLibrary.tsx 必须保留 <ModuleTabs>，不得修改全局模块切换');
}
if (!/AI小高剪辑/.test(materialLib)) {
  throw new Error('MaterialLibrary.tsx 必须保留 AI小高剪辑 标题栏');
}

// 2. 状态文案：pending 不得与"处理中"组合成把内部状态当展示态的错误文案
if (/pending[^\n]{0,20}处理中/.test(materialLib)) {
  throw new Error('MaterialLibrary.tsx 不得把 pending 状态渲染为"处理中"展示文案');
}

// 3. 三个标签页（真实入口在 features/ai-edit/pages/MaterialLibrary.tsx）
if (!/私有素材/.test(materialLib)) {
  throw new Error('MaterialLibrary.tsx 缺少"私有素材"标签页');
}
if (!/平台公共/.test(materialLib)) {
  throw new Error('MaterialLibrary.tsx 缺少"平台公共"标签页');
}
if (!/回收站/.test(materialLib)) {
  throw new Error('MaterialLibrary.tsx 缺少"回收站"标签页');
}

// 4. Task 12-9 待新增组件引用（当前缺失 → 红灯）
if (!/MaterialDetail/.test(materialLib)) {
  throw new Error('MaterialLibrary.tsx 必须引用 MaterialDetail 组件（Task 12-9 新增）');
}
if (!/ImportQueue/.test(materialLib)) {
  throw new Error('MaterialLibrary.tsx 必须引用 ImportQueue 组件（Task 12-9 新增）');
}

// 5. 组件文件本身存在性（Task 12-9 创建，当前缺失）
for (const comp of ['MaterialDetail.tsx', 'ImportQueue.tsx', 'MaterialFilters.tsx',
                    'MaterialGrid.tsx', 'MaterialTimeline.tsx']) {
  const full = resolve(srcRoot, 'features/ai-edit/components', comp);
  if (!existsSync(full)) {
    throw new Error(`组件缺失：features/ai-edit/components/${comp}（Task 12-9 新增）`);
  }
}

console.log('Phase 12 Task 12 素材库前端合同：PASS');
