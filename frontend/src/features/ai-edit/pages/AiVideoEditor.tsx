// Phase 12 Task 9 AI小高剪辑工作台（轻量）。
// 冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §5/§6/§11。
//
// 唯一流程（Task 10-FIX1 冻结）：模板/素材来自 9000（fetchAiEditTemplates/fetchAiEditMaterials）；
// 任务创建/取消/重试走 19000（createLocalJob/cancelLocalJob/retryLocalJob），19000 内部调 9000
// agent-create/agent-retry 登记 + 启动/取消/重入队 Worker；任务状态查询走 9000（fetchAiEditJob，
// 9000 为权威状态源，19000 终态回写）。不直接调 9000 /jobs 创建，否则 19000 agent-create 冲突。
// 不引入假任务、假统计。过审入口已 CANCELLED_BY_CUSTOMER，本页不出现。

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  FilmIcon,
  Loader2Icon,
  PlayIcon,
  RotateCcwIcon,
  ScissorsIcon,
  SquareIcon,
  UploadIcon,
} from "lucide-react";
import {
  fetchAiEditJob,
  fetchAiEditMaterials,
  fetchAiEditTemplates,
} from "../api";
import {
  cancelLocalJob,
  createLocalJob,
  retryLocalJob,
} from "../localApi";
import type {
  AiEditJob,
  AiEditMaterial,
  AiEditTemplate,
} from "../types";
import { userFacingError } from "../../../lib/userFacingError";

/** 统一错误信息（兼容 axios 形态）。 */
function resolveError(err: unknown): string {
  return userFacingError(err, "数据加载失败，请稍后重试");
}

const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  review_required: "待确认",
  cancel_requested: "取消中",
  cancelled: "已取消",
  failed: "失败",
  succeeded: "成功",
};

/** 阶段顺序（设计 §6），用于进度条展示。 */
const STAGE_ORDER = [
  "preflight",
  "analyze",
  "stabilize_optional",
  "plan_input",
  "render_preview_720p",
  "review_required",
  "render_final_1080p",
  "verify",
  "completed",
];

function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "未开始";
  const idx = STAGE_ORDER.indexOf(stage);
  return idx >= 0 ? `${idx + 1}/${STAGE_ORDER.length} ${stage}` : stage;
}

type MaterialRole = "main" | "broll" | "pip_replacement";

const ROLE_LABELS: Record<MaterialRole, string> = {
  main: "主素材",
  broll: "空镜替换",
  pip_replacement: "画中画替换",
};

export default function AiVideoEditor() {
  const [templates, setTemplates] = useState<AiEditTemplate[]>([]);
  const [materials, setMaterials] = useState<AiEditMaterial[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(true);
  const [metaError, setMetaError] = useState<string | null>(null);

  const [selectedTemplate, setSelectedTemplate] = useState<string>("");
  // 选中素材：material_id → role
  const [selected, setSelected] = useState<Record<string, MaterialRole>>({});
  // 首尾时间：material_id → { start, end }
  const [trims, setTrims] = useState<Record<string, { start: string; end: string }>>({});
  // 渲染目标：720P 草稿 / 1080P 成片（决定提交后是否进入确认环节）
  const [renderTarget, setRenderTarget] = useState<"720" | "1080">("720");
  // 字幕、背景音乐和画面稳定开关（一期由模板规则决定是否生效，页面仅收集偏好，不伪造后端字段）
  const [enableSubtitle, setEnableSubtitle] = useState(true);
  const [enableBgm, setEnableBgm] = useState(true);
  const [enableStabilize, setEnableStabilize] = useState(true);
  const [subtitleText, setSubtitleText] = useState("");

  const [currentJob, setCurrentJob] = useState<AiEditJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  const loadMeta = useCallback(async () => {
    setLoadingMeta(true);
    setMetaError(null);
    try {
      const [tpls, mats] = await Promise.all([
        fetchAiEditTemplates(),
        fetchAiEditMaterials(),
      ]);
      setTemplates(tpls.items || []);
      setMaterials((mats.items || []).filter((m) => !m.deleted_at && m.scope === "merchant"));
    } catch (err) {
      setMetaError(resolveError(err));
    } finally {
      setLoadingMeta(false);
    }
  }, []);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  // 轮询当前任务状态（运行中时）。
  useEffect(() => {
    if (!currentJob) return;
    const status = currentJob.status;
    if (status !== "running" && status !== "queued" && status !== "cancel_requested") return;
    const timer = setInterval(async () => {
      try {
        const job = await fetchAiEditJob(currentJob.job_id);
        setCurrentJob(job);
      } catch {
        // 轮询失败静默，下个 tick 重试
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [currentJob]);

  const selectedItems = useMemo(() => Object.keys(selected), [selected]);

  const onCreate = useCallback(async () => {
    if (!selectedTemplate) {
      toast.error("请先选择模板");
      return;
    }
    if (selectedItems.length === 0) {
      toast.error("请至少选择一个素材");
      return;
    }
    // 19000 创建任务：传入 material_id + role + 首尾时间（FIX2-6 落实，不再静默丢弃）。
    // 字幕、背景音乐、画面稳定和分辨率一期由模板规则决定，页面收集但渲染以模板为准。
    const jobMaterials = selectedItems.map((materialId) => {
      const trim = trims[materialId];
      const startSec = trim?.start ? Number(trim.start) : undefined;
      const endSec = trim?.end ? Number(trim.end) : undefined;
      return {
        material_id: materialId,
        role: selected[materialId],
        ...(startSec != null && !Number.isNaN(startSec) ? { source_start: startSec } : {}),
        ...(endSec != null && !Number.isNaN(endSec) ? { source_end: endSec } : {}),
      };
    });
    const jobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    setSubmitting(true);
    try {
      // 唯一创建顺序：前端→19000 创建→19000 内部调 9000 agent-create 登记 + 启动 Worker。
      // 不直接调 9000 /jobs，否则 19000 agent-create 会因任务已存在冲突。
      await createLocalJob({
        job_id: jobId,
        template_key: selectedTemplate,
        materials: jobMaterials,
      });
      // 创建后立即从 9000 拉权威状态（9000 已由 19000 登记）。
      const job = await fetchAiEditJob(jobId);
      setCurrentJob(job);
      toast.success(`任务已提交：${job.job_id}（渲染规格由模板决定）`);
    } catch (err) {
      toast.error(`任务创建失败：${resolveError(err)}`);
    } finally {
      setSubmitting(false);
    }
  }, [selectedTemplate, selectedItems, selected, trims]);

  const onCancel = useCallback(async () => {
    if (!currentJob) return;
    setActionLoading(true);
    try {
      // 取消由 19000 协调：终止 Worker + 终态回写 9000 cancelled。
      await cancelLocalJob(currentJob.job_id);
      const job = await fetchAiEditJob(currentJob.job_id);
      setCurrentJob(job);
      toast.success("已请求取消任务");
    } catch (err) {
      toast.error(`取消失败：${resolveError(err)}`);
    } finally {
      setActionLoading(false);
    }
  }, [currentJob]);

  const onRetry = useCallback(async () => {
    if (!currentJob) return;
    setActionLoading(true);
    try {
      // 重试由 19000 协调：调 9000 agent-retry 推进 attempt + 重新入队（令牌轮换）。
      await retryLocalJob(currentJob.job_id);
      const job = await fetchAiEditJob(currentJob.job_id);
      setCurrentJob(job);
      toast.success("已重试任务");
    } catch (err) {
      toast.error(`重试失败：${resolveError(err)}`);
    } finally {
      setActionLoading(false);
    }
  }, [currentJob]);

  const canSubmit = currentJob == null || ["succeeded", "failed", "cancelled"].includes(currentJob.status);
  const canCancel = currentJob != null && ["running", "queued"].includes(currentJob.status);
  const canRetry = currentJob != null && currentJob.status === "failed";

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-4">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-emerald-50 text-emerald-600">
            <ScissorsIcon size={23} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">AI小高剪辑</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">
              选择素材与模板，创建任务；720P 草稿预览后确认 1080P 成片。任务由本机处理程序执行。
            </p>
          </div>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-auto p-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        {/* 左：素材选择 + 模板 + 开关 */}
        <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-[#e4e8f0] bg-white">
          <div className="flex items-center justify-between border-b border-[#f1f4f9] px-5 py-3">
            <h2 className="inline-flex items-center gap-2 text-sm font-bold text-[#1a1f2e]">
              <FilmIcon className="h-4 w-4" />
              素材选择（私有）
            </h2>
            <button
              type="button"
              onClick={loadMeta}
              className="text-xs text-[#8b95a6] hover:text-[#1a1f2e]"
            >
              刷新
            </button>
          </div>

          {metaError ? (
            <div className="m-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
              <AlertCircleIcon className="mt-0.5 h-4 w-4 shrink-0" />
              {metaError}
            </div>
          ) : loadingMeta ? (
            <div className="grid h-24 place-items-center text-sm text-[#8b95a6]">加载中…</div>
          ) : materials.length === 0 ? (
            <div className="grid h-24 place-items-center text-sm text-[#8b95a6]">
              暂无私有素材，请先在素材库导入
            </div>
          ) : (
            <div className="min-h-0 flex-1 divide-y divide-[#f1f4f9] overflow-auto">
              {materials.map((m) => {
                const role = selected[m.material_id];
                const isSelected = Boolean(role);
                const trim = trims[m.material_id] || { start: "", end: "" };
                return (
                  <div key={m.material_id} className="px-5 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <label className="flex min-w-0 items-center gap-2 text-sm text-[#1a1f2e]">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={(e) => {
                            setSelected((prev) => {
                              const next = { ...prev };
                              if (e.target.checked) next[m.material_id] = "main";
                              else delete next[m.material_id];
                              return next;
                            });
                          }}
                        />
                        <span className="truncate font-mono text-xs">{m.material_id}</span>
                      </label>
                      {isSelected && (
                        <select
                          value={role}
                          onChange={(e) =>
                            setSelected((prev) => ({
                              ...prev,
                              [m.material_id]: e.target.value as MaterialRole,
                            }))
                          }
                          className="rounded border border-[#e4e8f0] px-2 py-1 text-xs"
                        >
                          {(Object.keys(ROLE_LABELS) as MaterialRole[]).map((r) => (
                            <option key={r} value={r}>
                              {ROLE_LABELS[r]}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                    {isSelected && (
                      <div className="mt-2 flex items-center gap-2 pl-6 text-xs text-[#5a6478]">
                        <span>首尾时间(秒)</span>
                        <input
                          type="number"
                          min={0}
                          placeholder="起始"
                          value={trim.start}
                          onChange={(e) =>
                            setTrims((prev) => ({
                              ...prev,
                              [m.material_id]: { ...trim, start: e.target.value },
                            }))
                          }
                          className="w-20 rounded border border-[#e4e8f0] px-2 py-1"
                        />
                        <input
                          type="number"
                          min={0}
                          placeholder="结束"
                          value={trim.end}
                          onChange={(e) =>
                            setTrims((prev) => ({
                              ...prev,
                              [m.material_id]: { ...trim, end: e.target.value },
                            }))
                          }
                          className="w-20 rounded border border-[#e4e8f0] px-2 py-1"
                        />
                        {role === "broll" && (
                          <span className="text-[#8b95a6]">（空镜替换片段）</span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* 右：模板 + 开关 + 任务 */}
        <section className="flex min-h-0 flex-col gap-4 overflow-auto">
          <div className="rounded-xl border border-[#e4e8f0] bg-white p-4">
            <h2 className="text-sm font-bold text-[#1a1f2e]">模板与渲染目标</h2>
            <select
              value={selectedTemplate}
              onChange={(e) => setSelectedTemplate(e.target.value)}
              className="mt-3 w-full rounded-lg border border-[#e4e8f0] px-3 py-2 text-sm"
            >
              <option value="">选择模板…</option>
              {templates.map((t) => (
                <option key={t.template_key} value={t.template_key}>
                  {t.name}（{t.template_key}）
                </option>
              ))}
            </select>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {(["720", "1080"] as const).map((target) => (
                <button
                  key={target}
                  type="button"
                  onClick={() => setRenderTarget(target)}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium ${
                    renderTarget === target
                      ? "border-[#1a1f2e] bg-[#1a1f2e] text-white"
                      : "border-[#e4e8f0] bg-white text-[#1a1f2e] hover:bg-[#f3f6fa]"
                  }`}
                >
                  {target === "720" ? "720P 草稿" : "1080P 成片"}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-[#8b95a6]">
              一期 pipeline 依次生成 720P 预览与 1080P 成片；此处选择查看目标，渲染规格由模板规则决定。
            </p>
          </div>

          <div className="rounded-xl border border-[#e4e8f0] bg-white p-4">
            <h2 className="text-sm font-bold text-[#1a1f2e]">片段选项</h2>
            <div className="mt-3 space-y-2 text-sm">
              <label className="flex items-center justify-between">
                <span className="text-[#5a6478]">字幕开关</span>
                <input
                  type="checkbox"
                  checked={enableSubtitle}
                  onChange={(e) => setEnableSubtitle(e.target.checked)}
                />
              </label>
              <label className="flex items-center justify-between">
                <span className="text-[#5a6478]">背景音乐开关</span>
                <input
                  type="checkbox"
                  checked={enableBgm}
                  onChange={(e) => setEnableBgm(e.target.checked)}
                />
              </label>
              <label className="flex items-center justify-between">
                <span className="text-[#5a6478]">增稳开关</span>
                <input
                  type="checkbox"
                  checked={enableStabilize}
                  onChange={(e) => setEnableStabilize(e.target.checked)}
                />
              </label>
              <textarea
                placeholder="字幕编辑（一期由模板规则驱动，提交时以模板规则为准）"
                value={subtitleText}
                onChange={(e) => setSubtitleText(e.target.value)}
                rows={3}
                className="mt-1 w-full rounded-lg border border-[#e4e8f0] px-3 py-2 text-xs"
              />
            </div>
            <p className="mt-2 text-xs text-[#8b95a6]">
              字幕、背景音乐和画面稳定由模板规则决定是否生效；页面只收集偏好，不伪造后端字段。
            </p>
          </div>

          <div className="rounded-xl border border-[#e4e8f0] bg-white p-4">
            <h2 className="text-sm font-bold text-[#1a1f2e]">任务进度</h2>
            {currentJob ? (
              <div className="mt-3 space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-[#5a6478]">{currentJob.job_id}</span>
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${
                      currentJob.status === "succeeded"
                        ? "bg-emerald-50 text-emerald-600"
                        : currentJob.status === "failed"
                          ? "bg-rose-50 text-rose-600"
                          : "bg-amber-50 text-amber-600"
                    }`}
                  >
                    {STATUS_LABELS[currentJob.status] || currentJob.status}
                  </span>
                </div>
                <div className="text-xs text-[#5a6478]">阶段：{stageLabel(currentJob.stage)}</div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#f1f4f9]">
                  <div
                    className="h-full bg-[#1a1f2e] transition-all"
                    style={{ width: `${Math.min(100, Math.max(0, currentJob.progress))}%` }}
                  />
                </div>
                {currentJob.error_summary && (
                  <div className="flex items-start gap-1 rounded bg-rose-50 p-2 text-xs text-rose-700">
                    <AlertCircleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    {currentJob.error_summary}
                  </div>
                )}
                <div className="flex items-center gap-2 pt-1">
                  <button
                    type="button"
                    onClick={onCancel}
                    disabled={!canCancel || actionLoading}
                    className="inline-flex items-center gap-1 rounded-lg border border-[#e4e8f0] px-3 py-1.5 text-xs text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                  >
                    <SquareIcon className="h-3.5 w-3.5" />
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={onRetry}
                    disabled={!canRetry || actionLoading}
                    className="inline-flex items-center gap-1 rounded-lg border border-[#e4e8f0] px-3 py-1.5 text-xs text-[#1a1f2e] hover:bg-[#f3f6fa] disabled:opacity-50"
                  >
                    <RotateCcwIcon className="h-3.5 w-3.5" />
                    重试
                  </button>
                </div>
              </div>
            ) : (
              <p className="mt-3 text-xs text-[#8b95a6]">尚未创建任务。</p>
            )}
          </div>

          <button
            type="button"
            onClick={onCreate}
            disabled={!canSubmit || submitting || loadingMeta}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#1a1f2e] px-4 py-3 text-sm font-bold text-white hover:bg-[#2a3142] disabled:opacity-50"
          >
            {submitting ? (
              <Loader2Icon className="h-4 w-4 animate-spin" />
            ) : (
              <PlayIcon className="h-4 w-4" />
            )}
            创建任务（{renderTarget === "720" ? "720P 草稿" : "1080P 成片"}）
          </button>
        </section>
      </div>
    </div>
  );
}
