// 素材上传的失败分类与结果汇总（纯逻辑，无 React/JSX 依赖，便于 node 直接测试）。
//
// 背景：上传视频走全局 axios timeout=10000ms 会在大文件/慢网络上误判超时；
// 生产已证明「客户端 timeout ≠ 服务端一定失败」（上传实际成功但前端报假失败）。
// 因此本模块坚持：UNKNOWN_RESULT（timeout/network/无 response）≠ FAILED（明确服务端拒绝）。
//
// 分类/统计/循环均为纯函数，测试见 uploadFeedback.test.ts（node:test 直接跑）。

/** 素材上传专用超时（ms）：视频文件大，不能继承全局 10s timeout。 */
export const MATERIAL_UPLOAD_TIMEOUT_MS = 120_000;

/** 素材上传大小上限（字节）：与后端 ai_edit.py max_size 逐字一致（500MB）。 */
export const MAX_MATERIAL_UPLOAD_BYTES = 500 * 1024 * 1024;

/** 超限固定提示文案：F1 前置拦截 / F2 413 统一友好提示共用（P0.5 规格冻结）。 */
export const MATERIAL_TOO_LARGE_TEXT = "视频文件不能超过500MB，请压缩后重新上传";

/** 判断文件大小是否超限：严格大于，恰好 500MB 放行（与后端 len > max_size 语义一致）。 */
export function isMaterialTooLarge(size: number): boolean {
  return size > MAX_MATERIAL_UPLOAD_BYTES;
}

/**
 * 判断上传错误是否为大小限制（HTTP 413）。
 * 后端唯一 413 即 FILE_TOO_LARGE；nginx 413 HTML 同为 status 413，单一状态判定覆盖两个来源。
 */
export function isMaterialSizeLimitError(err: unknown): boolean {
  if (err && typeof err === "object" && "response" in err) {
    const response = (err as { response?: { status?: unknown } }).response;
    return response !== undefined && response !== null && response.status === 413;
  }
  return false;
}

/** 单个文件上传结果分类。 */
export type UploadErrorKind = "failed" | "unknown";

/**
 * 判断一次上传错误是「明确失败」还是「结果未知」。
 *
 * - 有明确 HTTP response（4xx/5xx 后端明确拒绝）→ failed
 * - 无 response（timeout / network error / 请求未完成）→ unknown
 *   （客户端超时 ≠ 服务端一定失败，生产已实证；不在此断言失败）
 * - 非 axios 形状错误 → 保守 unknown
 */
export function classifyUploadError(err: unknown): UploadErrorKind {
  if (err && typeof err === "object" && "response" in err) {
    const response = (err as { response?: unknown }).response;
    if (response !== undefined && response !== null) {
      return "failed";
    }
  }
  return "unknown";
}

/** 一批文件的上传计数。 */
export interface UploadCounts {
  ok: number;
  failed: number;
  unknown: number;
  tooLarge: number;
}

/** 汇总结果对应的前端反馈（toast 文案 / error 文案 / 是否刷新列表）。 */
export interface UploadFeedback {
  toastText: string | null;
  errorText: string | null;
  callLoad: boolean;
}

/**
 * 根据计数生成前端反馈。
 *
 * 原则：
 * - 有成功 → 成功提示 + 刷新列表（success 与 unknown/failed/tooLarge 混合都要如实报告）；
 * - 全部 unknown（timeout/network）→ 结果未知，不显示「上传失败」；
 * - 全部明确失败 → 显示上传失败；
 * - tooLarge（HTTP 413）→ 固定超限文案；与成功混合时追加到成功提示，与失败混合时追加到错误文案。
 */
export function summarizeUploadResults(c: UploadCounts): UploadFeedback {
  if (c.ok > 0) {
    const parts: string[] = [`已成功上传 ${c.ok} 个素材`];
    if (c.unknown > 0) parts.push(`${c.unknown} 个上传结果暂未确认`);
    if (c.failed > 0) parts.push(`${c.failed} 个上传失败`);
    if (c.tooLarge > 0) parts.push(`${c.tooLarge} 个文件超过 500MB 未上传`);
    return {
      toastText: parts.join("，") + "，请刷新素材列表确认",
      errorText: null,
      callLoad: true,
    };
  }
  if (c.unknown > 0 && c.failed === 0) {
    return {
      toastText: null,
      errorText:
        "上传结果暂未确认，请刷新素材列表确认后再重试" +
        (c.tooLarge > 0 ? `；${c.tooLarge} 个文件超过 500MB 未上传` : ""),
      callLoad: false,
    };
  }
  if (c.unknown > 0 && c.failed > 0) {
    return {
      toastText: null,
      errorText:
        `上传失败：${c.failed} 个失败，${c.unknown} 个上传结果未确认，请刷新素材列表确认` +
        (c.tooLarge > 0 ? `；${c.tooLarge} 个文件超过 500MB 未上传` : ""),
      callLoad: false,
    };
  }
  if (c.failed > 0) {
    return {
      toastText: null,
      errorText:
        "上传失败，请稍后重试" +
        (c.tooLarge > 0 ? `；${c.tooLarge} 个文件超过 500MB 未上传` : ""),
      callLoad: false,
    };
  }
  if (c.tooLarge > 0) {
    // 纯超限（ok/failed/unknown 均为 0）：固定文案
    return {
      toastText: null,
      errorText: MATERIAL_TOO_LARGE_TEXT,
      callLoad: false,
    };
  }
  return { toastText: null, errorText: null, callLoad: false };
}

/**
 * 逐文件上传并汇总计数。
 *
 * 关键保证：每个文件只调用 uploadOne 一次（NO automatic retry）。
 * timeout/network 等失败只计数为 unknown，不触发重试。
 */
export async function runUpload(
  files: readonly unknown[],
  uploadOne: (file: unknown) => Promise<unknown>,
): Promise<UploadCounts> {
  const counts: UploadCounts = { ok: 0, failed: 0, unknown: 0, tooLarge: 0 };
  for (const file of files) {
    try {
      await uploadOne(file);
      counts.ok += 1;
    } catch (err) {
      // 413（nginx / FILE_TOO_LARGE）优先归为 tooLarge，其余沿用 failed/unknown 分类
      if (isMaterialSizeLimitError(err)) {
        counts.tooLarge += 1;
      } else if (classifyUploadError(err) === "failed") {
        counts.failed += 1;
      } else {
        counts.unknown += 1;
      }
    }
  }
  return counts;
}
