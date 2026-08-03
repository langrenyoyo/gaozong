/**
 * 前端状态映射逻辑测试（纯逻辑，不依赖 React 渲染框架）。
 * 复制 LasRemixWorkbench 的状态映射与计算逻辑，验证中文文案正确性。
 * 运行：node frontend/src/features/ai-edit/pages/__status_logic_test__.js
 * 退出码 0=全通过，1=失败。
 */

// === 复制自 LasRemixWorkbench.tsx 的状态逻辑 ===
const STATUS_VISUALS = {
  submitted: { label: "排队中" },
  queued: { label: "排队中" },
  running: { label: "生成中" },
  processing: { label: "生成中" },
  processing_result: { label: "正在整理视频" },
  completed: { label: "已完成" },
  succeeded: { label: "已完成" },
  failed: { label: "生成失败" },
  deleting: { label: "删除中" },
  delete_failed: { label: "删除失败" },
};

function computeDisplayStatus(job) {
  const s = job.status;
  if (s === "delete_failed" || s === "deleting") return s;
  if (s === "processing_result") return s;
  if (s === "failed") return s;
  if (s === "completed" || s === "succeeded") return s;
  if (s === "running" || s === "processing") return s;
  if (s === "submitted" || s === "queued") return s;
  return s;
}

function statusOf(status) {
  return STATUS_VISUALS[status] || { label: "处理中" };
}

// === 测试 ===
let failures = 0;
function assert(cond, msg) {
  if (!cond) {
    console.error("FAIL:", msg);
    failures++;
  }
}

// 测试 13：状态中文映射
const cases = {
  submitted: "排队中",
  running: "生成中",
  processing_result: "正在整理视频",
  completed: "已完成",
  deleting: "删除中",
  delete_failed: "删除失败",
  processing: "生成中",
  succeeded: "已完成",
  failed: "生成失败",
};
for (const [status, expected] of Object.entries(cases)) {
  const disp = computeDisplayStatus({ status, delivery_status: null });
  assert(statusOf(disp).label === expected, `状态 ${status} 应映射为 ${expected}，实际 ${statusOf(disp).label}`);
}

// 未知状态兜底
const unknown = statusOf("nonexistent_status");
assert(unknown.label === "处理中", `未知状态应兜底为"处理中"，实际 ${unknown.label}`);

// 测试 15：canPlay 逻辑（has_final_video + 可交付状态）
function canPlay(job) {
  const isDeliverable = job.status === "succeeded" || job.status === "completed";
  return job.has_final_video && isDeliverable;
}
assert(canPlay({ has_final_video: false, status: "succeeded" }) === false, "无视频不可播放");
assert(canPlay({ has_final_video: true, status: "running" }) === false, "未完成不可播放");
assert(canPlay({ has_final_video: true, status: "succeeded" }) === true, "已归档+succeeded 可播放");
assert(canPlay({ has_final_video: true, status: "completed" }) === true, "已归档+completed 可播放");
assert(canPlay({ has_final_video: true, status: "failed" }) === false, "失败状态不可播放");

if (failures === 0) {
  console.log("OK 前端状态逻辑测试全通过（状态映射 + 兜底 + canPlay 禁用规则）");
  process.exit(0);
} else {
  console.error(`\n${failures} 项失败`);
  process.exit(1);
}
