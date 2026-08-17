// 前端模式逻辑可运行测试（node:test，无前端测试框架）。
//
// 运行：node --test frontend/src/features/ai-edit/pages/__las_mode_logic_test__.js
// 或：  cd frontend && node --test src/features/ai-edit/pages/__las_mode_logic_test__.js
//
// 覆盖 AC-007~010：三种模式提交值一致（role/时长规则）、模式切换自动填充 Script 示例、
// 商户已编辑 Script 不静默覆盖（防覆盖）、切换 mode 清理失效 role/section/时长值。
//
// 实现说明：模式逻辑为 LasRemixWorkbench.tsx 顶部导出的纯函数（无 React/JSX 依赖）。
// 本测试用 esbuild（vite 的传递依赖，位于 frontend/node_modules）把组件转译为 ESM 后
// import 真实实现，保证测的是组件实际使用的同一份代码，不是副本。
// 依赖：esbuild 由 vite 传递引入；若未来前端依赖变更导致 esbuild 不可用，需改加载方式。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const esbuild = require("esbuild");

// 转译组件为 ESM：bundle 项目内相对导入，外部包保持 external；vite 的 import.meta.env 置空。
// 产物写入组件同目录下的临时目录，保证 node_modules 向上解析到 frontend/node_modules。
const outdir = mkdtempSync(join(import.meta.dirname, ".las-xlate-"));
let mod;
try {
  await esbuild.build({
    entryPoints: [join(import.meta.dirname, "LasRemixWorkbench.tsx")],
    outdir,
    format: "esm",
    platform: "node",
    bundle: true,
    packages: "external",
    jsx: "transform",
    logLevel: "silent",
    define: { "import.meta.env": "{}" },
  });
  mod = await import(pathToFileURL(join(outdir, "LasRemixWorkbench.js")).href);
} finally {
  rmSync(outdir, { recursive: true, force: true });
}

const {
  DEFAULT_MODE_SCRIPT,
  modeSupportsDuration,
  modeAllowedRoles,
  shouldAutoReplaceScript,
  cleanupSelectionForMode,
} = mod;

// ---------- AC-008：首次打开即填充当前模式（口播营销）的 PDF 4.7 节 Script 示例 ----------

test("新建任务首次打开即填充当前模式（口播营销）PDF 4.7 示例，不出现空脚本", () => {
  assert.ok(DEFAULT_MODE_SCRIPT.length > 20, "默认脚本不应为空或占位");
  // 口播营销示例特征（PDF 4.7 节原文）
  assert.match(DEFAULT_MODE_SCRIPT, /产品讲解视频/);
  assert.ok(DEFAULT_MODE_SCRIPT.length <= 4000, "默认脚本不超过 4000 字符上限");
});

// ---------- AC-008/009：自动填充与防覆盖 ----------

test("Script 为空 → 切换模式应自动替换为对应示例", () => {
  assert.equal(shouldAutoReplaceScript("", DEFAULT_MODE_SCRIPT), true);
  assert.equal(shouldAutoReplaceScript("   ", DEFAULT_MODE_SCRIPT), true);
});

test("Script 仍等于系统自动填入内容 → 切换模式自动替换", () => {
  assert.equal(shouldAutoReplaceScript(DEFAULT_MODE_SCRIPT, DEFAULT_MODE_SCRIPT), true);
  // 首尾空白差异仍视为未修改（trim 比较）
  assert.equal(shouldAutoReplaceScript(`  ${DEFAULT_MODE_SCRIPT}  `, DEFAULT_MODE_SCRIPT), true);
});

test("Script 已被商户修改 → 不得静默覆盖（防覆盖，须确认）", () => {
  const edited = "商户自己编写的创作指令，区别于系统示例";
  assert.equal(shouldAutoReplaceScript(edited, DEFAULT_MODE_SCRIPT), false);
  // 已修改后即使再次等于示例也不视为未修改（防误判由组件 confirm 兜底，此处验证判断为已修改）
  assert.equal(shouldAutoReplaceScript("商户指令" + DEFAULT_MODE_SCRIPT, DEFAULT_MODE_SCRIPT), false);
});

// ---------- AC-010：切换 mode 清理失效 role/section（不合法控件不得只隐藏值） ----------

test("切到 long_real_shot：清理非法 role（broll）与全部 section，保留合法 role 与其它字段", () => {
  const items = [
    { url: "https://a", displayName: "a", role: "broll", section: "real_shot" },
    { url: "https://b", displayName: "b", role: "voiceover" },
    { url: "https://c", displayName: "c", role: "speech", section: "headtalk" },
  ];
  const r = cleanupSelectionForMode(items, "long_real_shot");
  assert.equal(r[0].role, undefined, "broll 在 long_real_shot 非法应清理");
  assert.equal(r[1].role, "voiceover", "voiceover 在 long_real_shot 合法应保留");
  assert.equal(r[2].role, "speech");
  assert.equal(r[0].section, undefined, "section 应全部清空");
  assert.equal(r[2].section, undefined);
  assert.equal(r[0].url, "https://a", "url 等其它字段保留");
  assert.equal(r[0].displayName, "a");
  assert.equal(r.length, 3);
});

test("切到 real_shot_headtalk：清理非法 role（voiceover），保留合法 role（speech/broll）", () => {
  const items = [
    { url: "https://a", displayName: "a", role: "voiceover" },
    { url: "https://b", displayName: "b", role: "broll", section: "headtalk" },
    { url: "https://c", displayName: "c", role: "speech" },
  ];
  const r = cleanupSelectionForMode(items, "real_shot_headtalk");
  assert.equal(r[0].role, undefined, "voiceover 在 real_shot_headtalk 非法应清理");
  assert.equal(r[1].role, "broll", "broll 在 real_shot_headtalk 合法应保留");
  assert.equal(r[2].role, "speech");
  assert.equal(r[1].section, undefined, "section 应全部清空（需重新选择/自动分段）");
});

test("切回 marketing_headtalk：全部 role 合法，仅 section 清空", () => {
  const items = [
    { url: "https://a", displayName: "a", role: "voiceover", section: "headtalk" },
  ];
  const r = cleanupSelectionForMode(items, "marketing_headtalk");
  assert.equal(r[0].role, "voiceover", "marketing 支持 voiceover 保留");
  assert.equal(r[0].section, undefined, "marketing 禁 section 清空");
});

// ---------- AC-007/010：目标时长仅实拍类模式支持 ----------

test("目标时长仅 long_real_shot / real_shot_headtalk 支持，口播营销禁用", () => {
  assert.equal(modeSupportsDuration("marketing_headtalk"), false);
  assert.equal(modeSupportsDuration("long_real_shot"), true);
  assert.equal(modeSupportsDuration("real_shot_headtalk"), true);
});

test("各 mode 合法角色集合与后端规则一致", () => {
  assert.deepEqual(modeAllowedRoles("marketing_headtalk"), ["speech", "voiceover", "broll"]);
  assert.deepEqual(modeAllowedRoles("long_real_shot"), ["speech", "voiceover"]);
  assert.deepEqual(modeAllowedRoles("real_shot_headtalk"), ["speech", "broll"]);
});
