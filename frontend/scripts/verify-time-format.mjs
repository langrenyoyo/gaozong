import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "..");
const outputDir = resolve(projectRoot, "dist-time-test");
const tscBin = resolve(projectRoot, "node_modules/typescript/bin/tsc");

const cases = [
  {
    input: "2026-06-18T06:53:00Z",
    expected: "06/18 14:53",
    description: "带 Z 的 UTC 时间展示为本地时间",
  },
  {
    input: "2026-06-18T06:53:00",
    expected: "06/18 14:53",
    description: "无时区标记的后端时间按 UTC 解析",
  },
  {
    input: "2026-06-18T14:53:00+08:00",
    expected: "06/18 14:53",
    description: "带 +08:00 的时间不重复加 8 小时",
  },
];

try {
  rmSync(outputDir, { recursive: true, force: true });
  execFileSync(
    process.execPath,
    [
      tscBin,
      "src/lib/datetime.ts",
      "--target",
      "ES2022",
      "--module",
      "ES2022",
      "--moduleResolution",
      "bundler",
      "--outDir",
      "dist-time-test",
      "--skipLibCheck",
    ],
    { cwd: projectRoot, stdio: "inherit" },
  );

  const { formatDateTimeLocal } = await import(pathToFileURL(resolve(outputDir, "datetime.js")));

  for (const item of cases) {
    const actual = formatDateTimeLocal(item.input, {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
    if (actual !== item.expected) {
      throw new Error(`${item.description}: expected ${item.expected}, got ${actual}`);
    }
  }

  console.log("时间格式化样例验证通过");
} finally {
  rmSync(outputDir, { recursive: true, force: true });
}
