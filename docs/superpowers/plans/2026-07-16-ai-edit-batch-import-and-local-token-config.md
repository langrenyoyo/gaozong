# AI 剪辑批量导入与本机令牌配置修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复本地 9000 无法按商户下发 Local Agent token 的配置问题，并让素材库支持一次多选视频、顺序流式导入和失败汇总。

**Architecture:** 保留现有前端→19000 单文件流式接口和 19000→9000 元数据同步链路，不新增批量后端协议。前端负责把 `FileList` 转为文件数组并顺序调用 `importLocalMaterial`，批次结束后只刷新一次素材列表；本地 token 配置只做脱敏校验，不提交 `.env.lan.local`。

**Tech Stack:** React 19、TypeScript 5.9、Sonner、Playwright、Vite、FastAPI 既有 Local Agent 鉴权配置。

---

## 文件结构

- Modify: `frontend/src/features/ai-edit/pages/MaterialLibrary.tsx`：多文件选择、顺序导入、进度和汇总提示。
- Modify: `frontend/scripts/check-phase12-ai-edit-contract.mjs`：批量导入静态合同红灯。
- Modify: `frontend/scripts/check-phase12-ai-edit-layout.mjs`：双文件导入运行时回归。
- Modify: `docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md`：原位更新本地导入和验收事实。
- Read only: `.env.lan.local`：验证目标商户映射存在，禁止暂存和提交。

### Task 1: 脱敏验证本地 token 配置

**Files:**
- Read only: `.env.lan.local`

- [ ] **Step 1: 验证目标商户前缀存在且不输出 token**

Run:

```powershell
$line = Get-Content .env.lan.local -Encoding UTF8 |
  Where-Object { $_ -match '^\s*LOCAL_AGENT_TOKENS\s*=' } |
  Select-Object -First 1
$raw = ($line -split '=', 2)[1].Trim()
if ($raw -notmatch '^m_nc_2bba00063cc13016:.+$') {
  throw 'LOCAL_AGENT_TOKENS 未包含目标商户映射'
}
'PASS: 目标商户 Local Agent token 映射已配置（token 未输出）'
```

Expected: 输出 `PASS`，不打印 token。

- [ ] **Step 2: 确认配置文件被 Git 忽略**

Run:

```powershell
git check-ignore -v .env.lan.local
```

Expected: 命中 `.gitignore`，后续任何 `git add` 都不包含该文件。

### Task 2: 先增加批量导入红灯门禁

**Files:**
- Modify: `frontend/scripts/check-phase12-ai-edit-contract.mjs`
- Modify: `frontend/scripts/check-phase12-ai-edit-layout.mjs`
- Test: `frontend/scripts/check-phase12-ai-edit-contract.mjs`
- Test: `frontend/scripts/check-phase12-ai-edit-layout.mjs`

- [ ] **Step 1: 在静态合同中要求多选和全量 FileList 处理**

在 `check-phase12-ai-edit-contract.mjs` 的页面能力检查后加入：

```js
if (!materialLib.includes('multiple')) {
  throw new Error('MaterialLibrary 文件选择框未启用多选');
}
if (/files\?\.\[0\]/.test(materialLib)) {
  throw new Error('MaterialLibrary 仍只处理 files[0]，批量导入会丢文件');
}
if (!materialLib.includes('Array.from(e.target.files || [])')) {
  throw new Error('MaterialLibrary 未把完整 FileList 转为批量文件数组');
}
if (!materialLib.includes('importProgress.current') || !materialLib.includes('importProgress.total')) {
  throw new Error('MaterialLibrary 缺少批量导入进度显示');
}
```

- [ ] **Step 2: 在 Playwright 脚本中增加双文件导入探针**

在既有桌面/移动布局循环后、`browser.close()` 前增加独立桌面页面。该页面拦截 19000 流式导入，并统计导入次数与 9000 素材列表读取次数：

```js
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
        data: { material_id: materialId, relative_path: `materials/${materialId}.mp4`, sha256: 'a'.repeat(64), size_bytes: 3 },
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
await batchPage.getByText('批量导入完成：2 个').waitFor({ timeout: 8000 });
if (batchImports.length !== 2) failures.push(`batch-import: 期望 2 次流式导入，实际 ${batchImports.length}`);
if (new Set(batchImports).size !== 2) failures.push('batch-import: material_id 未保持批次内唯一');
if (materialListRequests !== 2) failures.push(`batch-import: 素材列表应初始读取一次、批次结束刷新一次，实际 ${materialListRequests}`);
await batchContext.close();
```

- [ ] **Step 3: 运行红灯静态合同**

Run:

```powershell
cd frontend
node scripts/check-phase12-ai-edit-contract.mjs
```

Expected: FAIL，至少包含 `文件选择框未启用多选`。

- [ ] **Step 4: 运行红灯 Playwright 探针**

Run:

```powershell
cd frontend
node scripts/check-phase12-ai-edit-layout.mjs http://127.0.0.1:5173
```

Expected: FAIL，双文件选择后只发送一次导入请求，或找不到 `批量导入完成：2 个`。

### Task 3: 实现顺序批量导入

**Files:**
- Modify: `frontend/src/features/ai-edit/pages/MaterialLibrary.tsx`
- Test: `frontend/scripts/check-phase12-ai-edit-contract.mjs`
- Test: `frontend/scripts/check-phase12-ai-edit-layout.mjs`

- [ ] **Step 1: 用进度状态替换单一 importing 布尔值**

将：

```ts
const [importing, setImporting] = useState(false);
```

替换为：

```ts
const [importProgress, setImportProgress] = useState<{ current: number; total: number } | null>(null);
const importing = importProgress !== null;
```

- [ ] **Step 2: 将单文件回调改为顺序批量处理**

用以下实现替换 `onFileChange`：

```ts
const onFileChange = useCallback(
  async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (files.length === 0) return;

    const batchId = Date.now();
    const failed: { name: string; reason: string }[] = [];
    let succeeded = 0;
    setImportProgress({ current: 0, total: files.length });
    try {
      for (const [index, file] of files.entries()) {
        setImportProgress({ current: index + 1, total: files.length });
        const safeName = file.name.replace(/[^\w.-]/g, "_").slice(0, 32);
        const materialId = `mat_${batchId}_${index}_${safeName}`;
        try {
          await importLocalMaterial(file, materialId, merchantId);
          succeeded += 1;
        } catch (err) {
          failed.push({ name: file.name, reason: resolveError(err) });
        }
      }

      if (succeeded > 0) await load();
      if (failed.length === 0) {
        toast.success(`批量导入完成：${succeeded} 个`);
      } else {
        const description = failed.map((item) => `${item.name}（${item.reason}）`).join("；");
        const summary = `批量导入完成：成功 ${succeeded} 个，失败 ${failed.length} 个`;
        if (succeeded > 0) toast.warning(summary, { description });
        else toast.error(summary, { description });
      }
    } finally {
      setImportProgress(null);
    }
  },
  [load, merchantId],
);
```

- [ ] **Step 3: 启用多选并显示进度**

按钮文字改为：

```tsx
{importProgress
  ? `导入中 ${importProgress.current}/${importProgress.total}`
  : "批量导入素材"}
```

文件输入框增加：

```tsx
multiple
```

- [ ] **Step 4: 运行绿灯合同和布局探针**

Run:

```powershell
cd frontend
node scripts/check-phase12-ai-edit-contract.mjs
node scripts/check-phase12-ai-edit-layout.mjs http://127.0.0.1:5173
```

Expected: 两项均 PASS；Playwright 记录两次导入、两个不同 `material_id` 和两次素材列表读取。

- [ ] **Step 5: 提交功能与回归门禁**

```powershell
git add -- frontend/src/features/ai-edit/pages/MaterialLibrary.tsx frontend/scripts/check-phase12-ai-edit-contract.mjs frontend/scripts/check-phase12-ai-edit-layout.mjs
git commit -m "功能：支持 AI 剪辑素材批量导入"
```

### Task 4: 更新当前事实并完成回归

**Files:**
- Modify: `docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md`

- [ ] **Step 1: 原位更新 §6.2 本地导入**

将 §6.2 的六步流程替换为：

```markdown
1. 浏览器可一次多选视频，为每个文件生成独立且不含本机路径的素材 ID。
2. 前端按选择顺序逐个把文件流式传给 19000；单个失败记录文件名和原因，不阻断后续文件。
3. 19000 将文件复制到受管目录，原文件只读且不被覆盖。
4. 19000 校验媒体类型、计算 SHA-256、执行 ffprobe 并生成低清缩略图。
5. 19000 向 9000 同步 metadata 和缩略图；9000 不保存本机绝对路径。
6. 19000 的本地清单把素材 ID 映射到受管目录相对路径；批次结束后前端只刷新一次 9000 素材列表。
```

- [ ] **Step 2: 原位更新 §15.1 自动化验收**

将现有前端验收项替换为：

```markdown
- 前端接口合同、离线状态、刷新恢复、TypeScript 和构建通过；9000 标准 `{success,data,message}` 响应经 `apiClient` 拦截器处理后只解包一层 `data`。
- 素材库批量导入合同通过：文件多选、双文件顺序流式导入、批次内素材 ID 唯一、单个失败继续和批次结束只刷新一次列表。
```

- [ ] **Step 3: 执行完整前端验证**

Run:

```powershell
cd frontend
node scripts/check-phase12-ai-edit-contract.mjs
npx tsc -b --pretty false
npm run build
node scripts/check-phase12-ai-edit-layout.mjs http://127.0.0.1:5173
```

Expected: 合同 PASS、TypeScript exit 0、Vite 构建 PASS、Playwright PASS。

- [ ] **Step 4: 检查差异与脏工作区保护**

Run:

```powershell
git diff --check -- docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md
git status --short
git check-ignore -v .env.lan.local
```

Expected: diff check exit 0；`.env.lan.local` 不出现在 status；用户既有两份脏文档仍未暂存。

- [ ] **Step 5: 提交文档事实更新**

```powershell
git add -- docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md
git commit -m "文档：更新 AI 剪辑批量导入验收事实"
```

- [ ] **Step 6: 提交后核验**

Run:

```powershell
git status --short
git log -3 --oneline
```

Expected: 只剩用户原有脏文件；新提交链包含设计、批量导入功能和文档事实更新。
