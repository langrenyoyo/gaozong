import assert from "node:assert/strict";
import { readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

const sourcePath = new URL("../src/features/douyin-cs/douyinConversationIncremental.ts", import.meta.url);
const outputPath = join(tmpdir(), `douyin-conversation-incremental-${process.pid}.mjs`);

try {
  const source = await readFile(sourcePath, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      strict: true,
    },
  }).outputText;
  await writeFile(outputPath, output, "utf8");
  const mod = await import(`${pathToFileURL(outputPath).href}?v=${Date.now()}`);

  const oldMessage = { id: 10, raw_event_id: 10, created_at: "2026-07-28T12:00:00Z", content: "新时间" };
  const lateMessage = { id: 11, raw_event_id: 11, created_at: "2026-07-28T11:00:00Z", content: "迟到入库" };
  const merged = mod.mergeMessagesByEventId([oldMessage], [oldMessage, lateMessage]);
  assert.deepEqual(merged.map((item) => item.raw_event_id), [11, 10]);
  assert.equal(mod.advanceEventCursor(20, 19), 20);
  assert.equal(mod.advanceEventCursor(20, 21), 21);
  assert.equal(mod.retryDelayMs(1, 0), 8000);
  assert.equal(mod.retryDelayMs(2, 0), 16000);
  assert.equal(mod.retryDelayMs(8, 0), 60000);

  let active = 0;
  let maxActive = 0;
  await mod.runWithConcurrency([1, 2, 3, 4, 5], 3, async () => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active -= 1;
  });
  assert.equal(maxActive, 3);

  let runs = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const trigger = mod.createCoalescedRunner(async () => {
    runs += 1;
    if (runs === 1) await gate;
  });
  const first = trigger();
  const second = trigger();
  const third = trigger();
  release();
  await Promise.all([first, second, third]);
  assert.equal(runs, 2);

  console.log("DOUYIN_WORKBENCH_INCREMENTAL_CHECK_OK");
} finally {
  await rm(outputPath, { force: true });
}
