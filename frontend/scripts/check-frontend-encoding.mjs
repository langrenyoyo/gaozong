#!/usr/bin/env node

/**
 * 前端源码编码检查脚本
 *
 * 检测 src 目录下所有 .ts/.tsx/.js/.jsx 文件中是否存在中文乱码字符。
 * 主要检测 GB18030 双重编码产生的 PUA 字符（U+E000 ~ U+F8FF）。
 *
 * 使用方式：
 *   node scripts/check-frontend-encoding.mjs
 *   npm run encoding:check
 */

import { readFileSync, readdirSync, statSync } from "fs";
import { join, extname, relative } from "path";

const TARGET_EXTS = new Set([".ts", ".tsx", ".js", ".jsx"]);
const SRC_ROOT = join(import.meta.dirname, "..", "src");

// PUA 字符范围（U+E000 ~ U+F8FF）
// GB18030 解码错误会产生大量 PUA 字符，这是最可靠的乱码指标
const PUA_REGEX = /[-]/;

/**
 * 递归收集目标文件
 */
function collectFiles(dir) {
  const results = [];
  try {
    const entries = readdirSync(dir);
    for (const entry of entries) {
      const fullPath = join(dir, entry);
      const stat = statSync(fullPath);
      if (stat.isDirectory()) {
        results.push(...collectFiles(fullPath));
      } else if (TARGET_EXTS.has(extname(fullPath))) {
        results.push(fullPath);
      }
    }
  } catch {
    // 目录不存在或无权限，跳过
  }
  return results;
}

// === 主流程 ===
console.log("正在扫描 src/ 目录...\n");

const files = collectFiles(SRC_ROOT);
console.log(`找到 ${files.length} 个文件\n`);

let totalIssues = 0;
const problemFiles = [];

for (const file of files) {
  const relativePath = relative(process.cwd(), file);
  let content;
  try {
    content = readFileSync(file, "utf-8");
  } catch {
    continue;
  }

  const lines = content.split("\n");
  const issues = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (PUA_REGEX.test(line)) {
      const puaMatch = line.match(/[-]+/);
      if (puaMatch) {
        const col = line.indexOf(puaMatch[0]) + 1;
        issues.push({
          line: i + 1,
          col,
          snippet: line.trim().slice(0, 80),
          code: `U+${puaMatch[0].charCodeAt(0).toString(16).toUpperCase()}`,
        });
      }
    }
  }

  if (issues.length > 0) {
    totalIssues += issues.length;
    problemFiles.push({ file: relativePath, issues });
  }
}

if (problemFiles.length === 0) {
  console.log("✅ 所有文件编码正常，未发现 PUA 乱码字符。");
  process.exit(0);
} else {
  console.log("❌ 发现编码问题：\n");
  for (const { file, issues } of problemFiles) {
    console.log(`  ${file}`);
    for (const { line, col, snippet, code } of issues) {
      console.log(`    L${line}:${col} — PUA 字符 (${code})`);
      if (snippet) {
        console.log(`      ${snippet}`);
      }
    }
    console.log();
  }
  console.log(`共 ${problemFiles.length} 个文件、${totalIssues} 处 PUA 乱码。`);
  console.log("请检查文件是否被 GBK/GB18030 编辑器打开后保存。");
  process.exit(1);
}
