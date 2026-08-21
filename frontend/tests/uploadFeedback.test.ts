// 素材上传纯逻辑测试（node:test 直接跑，无需前端测试框架）。
//
// 运行：node --test src/features/ai-edit/uploadFeedback.test.ts
// 覆盖 T1~T9：上传 timeout 覆盖 / 全局 timeout 不变 / 成功 / timeout 不误报 /
// network 不误报 / 明确 HTTP 失败仍报失败 / 多文件混合 / 无自动重试 / 成功路径回归。
//
// 不连网络、不连后端；runUpload 的 uploadOne 用 mock。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import {
  MATERIAL_UPLOAD_TIMEOUT_MS,
  MAX_MATERIAL_UPLOAD_BYTES,
  MATERIAL_TOO_LARGE_TEXT,
  classifyUploadError,
  isMaterialTooLarge,
  isMaterialSizeLimitError,
  runUpload,
  summarizeUploadResults,
} from "../src/features/ai-edit/uploadFeedback.ts";

const __dirname = dirname(fileURLToPath(import.meta.url));

// ---------- T1：upload timeout override ----------

test("T1 upload timeout 显式覆盖为 120000（> 全局 10000）", () => {
  assert.equal(MATERIAL_UPLOAD_TIMEOUT_MS, 120_000);
  assert.ok(MATERIAL_UPLOAD_TIMEOUT_MS > 10_000);
});

// ---------- T2：全局 timeout 不变 ----------

test("T2 全局 axios timeout 仍为 10000，未被修改", () => {
  const clientSrc = readFileSync(
    join(__dirname, "..", "src", "api", "client.ts"),
    "utf-8",
  );
  assert.match(clientSrc, /timeout:\s*10000/);
  // client.ts 不得引用上传专用超时常量（全局配置与上传覆盖分离）
  assert.doesNotMatch(clientSrc, /MATERIAL_UPLOAD_TIMEOUT_MS/);
});

// ---------- T3：成功上传 ----------

test("T3 上传 resolve → success 计数 + 成功反馈 + 刷新列表", async () => {
  const calls: string[] = [];
  const counts = await runUpload(["a", "b"], async (f) => {
    calls.push(String(f));
  });
  assert.deepEqual(counts, { ok: 2, failed: 0, unknown: 0, tooLarge: 0 });
  const fb = summarizeUploadResults(counts);
  assert.match(fb.toastText ?? "", /已成功上传 2 个素材/);
  assert.equal(fb.errorText, null);
  assert.equal(fb.callLoad, true);
});

// ---------- T4：timeout 不误报失败 ----------

test("T4 timeout（ECONNABORTED，无 response）→ UNKNOWN，不得显示上传失败", async () => {
  const err = { code: "ECONNABORTED", message: "timeout of 10000ms exceeded" };
  assert.equal(classifyUploadError(err), "unknown");
  const counts = await runUpload(["a"], async () => {
    throw err;
  });
  assert.deepEqual(counts, { ok: 0, failed: 0, unknown: 1, tooLarge: 0 });
  const fb = summarizeUploadResults(counts);
  assert.match(fb.errorText ?? "", /结果暂未确认/);
  assert.doesNotMatch(fb.errorText ?? "", /上传失败，请稍后重试/);
});

// ---------- T5：network / no response → UNKNOWN ----------

test("T5 network（无 response）→ UNKNOWN，不得断言失败", async () => {
  const err = { code: "ERR_NETWORK", message: "Network Error" };
  assert.equal(classifyUploadError(err), "unknown");
  const counts = await runUpload(["a"], async () => {
    throw err;
  });
  assert.deepEqual(counts, { ok: 0, failed: 0, unknown: 1, tooLarge: 0 });
  const fb = summarizeUploadResults(counts);
  assert.match(fb.errorText ?? "", /结果暂未确认/);
  assert.doesNotMatch(fb.errorText ?? "", /上传失败，请稍后重试/);
});

// ---------- T6：明确 HTTP 失败仍显示失败 ----------

test("T6 HTTP 4xx（有 response）→ FAILED", async () => {
  const err = { response: { status: 400, data: { detail: { message: "INVALID_VIDEO_TYPE" } } } };
  assert.equal(classifyUploadError(err), "failed");
  const counts = await runUpload(["a"], async () => {
    throw err;
  });
  assert.deepEqual(counts, { ok: 0, failed: 1, unknown: 0, tooLarge: 0 });
  const fb = summarizeUploadResults(counts);
  assert.equal(fb.errorText, "上传失败，请稍后重试");
});

// ---------- T7：多文件混合（success + timeout）----------

test("T7 多文件 success+timeout → 如实报告 success+unknown，不得显示全部失败", async () => {
  const counts = await runUpload(["ok", "timeout"], async (f) => {
    if (String(f) === "timeout") throw { code: "ECONNABORTED" };
  });
  assert.deepEqual(counts, { ok: 1, failed: 0, unknown: 1, tooLarge: 0 });
  const fb = summarizeUploadResults(counts);
  assert.match(fb.toastText ?? "", /已成功上传 1 个素材/);
  assert.match(fb.toastText ?? "", /1 个上传结果暂未确认/);
  assert.doesNotMatch(fb.toastText ?? "", /全部/);
  assert.equal(fb.errorText, null);
});

// ---------- T8：无自动重试 ----------

test("T8 timeout 后 uploadOne 只调用 1 次（无自动 retry）", async () => {
  let calls = 0;
  await runUpload(["a", "b", "c"], async () => {
    calls += 1;
    throw { code: "ECONNABORTED" };
  });
  assert.equal(calls, 3); // 每个文件恰好一次，无重试
});

// ---------- T9：现有成功路径回归 ----------

test("T9 全成功路径保持（成功提示 + 刷新 + 无 error）", async () => {
  const counts = await runUpload(["a"], async () => {});
  const fb = summarizeUploadResults(counts);
  assert.match(fb.toastText ?? "", /已成功上传 1 个素材/);
  assert.equal(fb.errorText, null);
  assert.equal(fb.callLoad, true);
});

// ---------- T10：F1 大小前置校验（V1/V2）----------

test("T10 499MB 放行、恰好 500MB 放行（边界）、501MB 阻断", () => {
  assert.equal(MAX_MATERIAL_UPLOAD_BYTES, 500 * 1024 * 1024);
  assert.equal(isMaterialTooLarge(499 * 1024 * 1024), false); // V1
  assert.equal(isMaterialTooLarge(500 * 1024 * 1024), false); // 边界：严格大于才超限
  assert.equal(isMaterialTooLarge(500 * 1024 * 1024 + 1), true);
  assert.equal(isMaterialTooLarge(501 * 1024 * 1024), true); // V2
});

// ---------- T11：nginx 413 HTML mock（V3）----------

test("T11 nginx 413 HTML → 分类 tooLarge + 固定友好文案（不展示 HTML/技术异常）", async () => {
  const err = { response: { status: 413, data: "<html>413 Request Entity Too Large</html>" } };
  assert.equal(isMaterialSizeLimitError(err), true);
  const counts = await runUpload(["a"], async () => {
    throw err;
  });
  assert.deepEqual(counts, { ok: 0, failed: 0, unknown: 0, tooLarge: 1 });
  const fb = summarizeUploadResults(counts);
  assert.equal(fb.errorText, MATERIAL_TOO_LARGE_TEXT);
  assert.doesNotMatch(fb.errorText ?? "", /<html/);
  assert.equal(fb.toastText, null);
  assert.equal(fb.callLoad, false);
});

// ---------- T12：后端 FILE_TOO_LARGE mock（V4）----------

test("T12 后端 FILE_TOO_LARGE 413 → 与 nginx 413 同一固定文案", async () => {
  const err = {
    response: { status: 413, data: { detail: { code: "FILE_TOO_LARGE", message: "文件不能超过 500MB" } } },
  };
  assert.equal(isMaterialSizeLimitError(err), true);
  const counts = await runUpload(["a"], async () => {
    throw err;
  });
  assert.deepEqual(counts, { ok: 0, failed: 0, unknown: 0, tooLarge: 1 });
  const fb = summarizeUploadResults(counts);
  assert.equal(fb.errorText, MATERIAL_TOO_LARGE_TEXT);
  assert.doesNotMatch(fb.errorText ?? "", /FILE_TOO_LARGE/);
  assert.equal(fb.toastText, null);
  assert.equal(fb.callLoad, false);
});

// ---------- T13：混合（success + tooLarge，V6）----------

test("T13 混合 success+tooLarge → toast 追加超限计数，仍刷新列表", async () => {
  const counts = await runUpload(["ok", "big"], async (f) => {
    if (String(f) === "big") throw { response: { status: 413, data: "<html>413</html>" } };
  });
  assert.deepEqual(counts, { ok: 1, failed: 0, unknown: 0, tooLarge: 1 });
  const fb = summarizeUploadResults(counts);
  assert.match(fb.toastText ?? "", /已成功上传 1 个素材/);
  assert.match(fb.toastText ?? "", /1 个文件超过 500MB 未上传/);
  assert.equal(fb.errorText, null);
  assert.equal(fb.callLoad, true);
});

// ---------- T14：混合（failed + tooLarge，无成功，V6）----------

test("T14 混合 failed+tooLarge 无成功 → error 文案末尾追加超限计数，不刷新", async () => {
  const counts = await runUpload(["fail", "big"], async (f) => {
    if (String(f) === "fail") throw { response: { status: 400, data: { detail: { message: "INVALID" } } } };
    throw { response: { status: 413, data: "<html>413</html>" } };
  });
  assert.deepEqual(counts, { ok: 0, failed: 1, unknown: 0, tooLarge: 1 });
  const fb = summarizeUploadResults(counts);
  assert.match(fb.errorText ?? "", /上传失败，请稍后重试/);
  assert.match(fb.errorText ?? "", /1 个文件超过 500MB 未上传/);
  assert.equal(fb.toastText, null);
  assert.equal(fb.callLoad, false);
});
