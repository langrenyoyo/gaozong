// AI小高剪辑（参照 react_base_back AiVideoEditor 重做，2026-07-31）。
// 任务列表式：统计栏 + 工具栏（状态筛选+搜索+计数）+ 任务卡片 + 新建任务弹层。
// 纯 LAS 云端：新建任务 = 选素材（已上传云）+ 填 script → createLasJob。

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  CircleAlertIcon,
  ClapperboardIcon,
  Clock3Icon,
  DownloadIcon,
  FilmIcon,
  Loader2Icon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  SendIcon,
  Trash2Icon,
  UploadCloudIcon,
  XIcon,
} from "lucide-react";
import { createLasJob, deleteLasJob, fetchAiEditMaterials, fetchDownloadUrl, fetchPlayUrl, listLasJobs } from "../api";
import type { AiEditMaterial, LasJobStatus } from "../types";
import { userFacingError } from "../../../lib/userFacingError";

const SCRIPT_EXAMPLE = `剪成一条约 60 秒的汽车真人讲解视频。开头优先保留最有吸引力的车辆信息，随后按外观、座舱、配置、车况和总结组织。删除口误与重复表述，同一信息多次录制时优先保留最后一次完整自然的口播。讲到具体部位、配置、屏幕、座椅、空间或车况时，必须优先匹配能够直接证明该信息的对应空镜；泛化空镜不能抢占更匹配的素材。默认硬切，只有口播切到重点产品细节时使用轻量转场。`;

// 中文任务状态映射（兼容规范状态与现有旧状态，不展示英文技术枚举）
const STATUS_VISUALS: Record<string, { label: string; tone: string; accent: string }> = {
  submitted: { label: "排队中", tone: "bg-slate-100 text-slate-700", accent: "bg-slate-400" },
  queued: { label: "排队中", tone: "bg-slate-100 text-slate-700", accent: "bg-slate-400" },
  running: { label: "生成中", tone: "bg-blue-100 text-blue-700", accent: "bg-blue-500" },
  processing: { label: "生成中", tone: "bg-blue-100 text-blue-700", accent: "bg-blue-500" },
  processing_result: { label: "正在整理视频", tone: "bg-amber-100 text-amber-700", accent: "bg-amber-500" },
  completed: { label: "已完成", tone: "bg-emerald-100 text-emerald-700", accent: "bg-emerald-500" },
  succeeded: { label: "已完成", tone: "bg-emerald-100 text-emerald-700", accent: "bg-emerald-500" },
  failed: { label: "生成失败", tone: "bg-red-100 text-red-700", accent: "bg-red-500" },
  deleting: { label: "删除中", tone: "bg-amber-100 text-amber-700", accent: "bg-amber-500" },
  delete_failed: { label: "删除失败", tone: "bg-red-100 text-red-700", accent: "bg-red-500" },
};

/** 计算最终展示状态：优先级 delete_failed > deleting > processing_result > failed > completed/succeeded > running/processing > submitted/queued。
 *  综合后端 status/delivery_status/delete_status 三个字段。 */
function computeDisplayStatus(job: { status: string; delivery_status: string | null }): string {
  // 删除态优先（delete_status 未在列表返回，但 status 可能含 deleting；此处以 delivery/status 推断）
  if (job.delivery_status === "failed" && job.status === "failed") {
    // 归档失败也属失败，但需区分；交由下方 failed
  }
  // 规范状态优先，兼容旧状态
  const s = job.status;
  if (s === "delete_failed" || s === "deleting") return s;
  if (s === "processing_result") return s;
  if (s === "failed") return s;
  if (s === "completed" || s === "succeeded") return s;
  if (s === "running" || s === "processing") return s;
  if (s === "submitted" || s === "queued") return s;
  return s; // 未知，兜底在 statusOf 里处理
}

function statusOf(status: string) {
  return STATUS_VISUALS[status] || { label: "处理中", tone: "bg-slate-100 text-slate-700", accent: "bg-slate-400" };
}

// 视频能力标签代码 → 中文展示（来源后端 video_tags，基于真实处理模式）
const VIDEO_TAG_LABELS: Record<string, string> = {
  script_driven: "口播文案驱动",
  ai_subtitle: "AI智能字幕",
  ai_clip_matching: "AI片段拼接",
};

function NewTaskModal({
  onClose,
  onSubmitted,
}: {
  onClose: () => void;
  onSubmitted: () => void;
}) {
  const [materials, setMaterials] = useState<AiEditMaterial[]>([]);
  const [loadingMaterials, setLoadingMaterials] = useState(false);
  const [selectedUrls, setSelectedUrls] = useState<string[]>([]);
  const [script, setScript] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cloudMaterials = useMemo(() => materials.filter((m) => m.tos_presigned_url), [materials]);

  useEffect(() => {
    void (async () => {
      setLoadingMaterials(true);
      try {
        const resp = await fetchAiEditMaterials();
        setMaterials(resp.items || []);
      } catch {
        // 静默
      } finally {
        setLoadingMaterials(false);
      }
    })();
  }, []);

  const toggleUrl = (url: string) => {
    setSelectedUrls((prev) => (prev.includes(url) ? prev.filter((u) => u !== url) : [...prev, url]));
  };

  const submit = async () => {
    setError(null);
    if (selectedUrls.length === 0) {
      setError("请至少选择一个已上传到云的素材");
      return;
    }
    if (!script.trim()) {
      setError("请填写创作指令");
      return;
    }
    setSubmitting(true);
    try {
      await createLasJob({ video_urls: selectedUrls, script: script.trim(), template: "automotive_headtalk" });
      toast.success("任务已提交，云端混剪中");
      onSubmitted();
      onClose();
    } catch (err) {
      setError(userFacingError(err, "提交失败，请稍后重试"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-20 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm" role="dialog" aria-modal="true">
      <div className="flex max-h-[88vh] w-full max-w-[720px] flex-col overflow-hidden rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">新建剪辑任务</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">选择已上传到云的素材，填写创作指令，提交云端混剪</p>
          </div>
          <button type="button" onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
          <h3 className="text-sm font-bold text-[#1a1f2e]">选择素材</h3>
          <p className="mt-1 text-xs text-[#8b95a6]">仅显示已上传到云的素材（在素材库上传到 TOS）</p>
          <div className="mt-3 max-h-[240px] overflow-y-auto rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-3">
            {loadingMaterials ? (
              <div className="text-xs text-[#8b95a6]">加载中…</div>
            ) : cloudMaterials.length === 0 ? (
              <div className="text-xs text-[#8b95a6]">暂无已上传到云的素材，请先到素材库上传</div>
            ) : (
              cloudMaterials.map((m) => {
                const url = m.tos_presigned_url as string;
                const checked = selectedUrls.includes(url);
                return (
                  <label key={m.material_id} className="flex items-center gap-2 py-1.5 text-xs text-[#475467]">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleUrl(url)}
                      className="h-3.5 w-3.5 rounded border-[#cbd5e1] text-[#2563eb]"
                    />
                    <span className="truncate">{m.display_name || m.material_id}</span>
                  </label>
                );
              })
            )}
          </div>

          <div className="mt-5 flex items-center justify-between">
            <h3 className="text-sm font-bold text-[#1a1f2e]">创作指令</h3>
            <button type="button" onClick={() => setScript(SCRIPT_EXAMPLE)} className="text-[11px] font-semibold text-[#2563eb] hover:underline">
              填入示例
            </button>
          </div>
          <p className="mt-1 text-xs text-[#8b95a6]">自然语言描述目标时长、保留/删除内容、叙事顺序，最长 4000 字</p>
          <textarea
            value={script}
            onChange={(e) => setScript(e.target.value)}
            rows={6}
            maxLength={4000}
            placeholder="如：剪成一条约 60 秒的汽车真人讲解视频，删除口误与重复表述…"
            className="mt-2 w-full resize-y rounded-xl border border-[#e4e8f0] px-3 py-2 text-xs text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
          />
          <div className="mt-1 text-right text-[10px] text-[#8b95a6]">{script.length}/4000</div>

          {error ? (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-700">
              <CircleAlertIcon size={14} />
              {error}
            </div>
          ) : null}
        </div>

        <div className="flex justify-end border-t border-[#e4e8f0] px-5 py-4">
          <button type="button" onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={submitting}
            className="ml-2 inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:opacity-60"
          >
            {submitting ? <Loader2Icon size={14} className="animate-spin" /> : <SendIcon size={14} />}
            {submitting ? "提交中…" : "提交混剪"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function LasRemixWorkbench({ merchantId }: { merchantId: string }) {
  void merchantId;
  const [jobs, setJobs] = useState<LasJobStatus[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [keyword, setKeyword] = useState("");
  const [showModal, setShowModal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const resp = await listLasJobs({ status: statusFilter || undefined, page: 1, page_size: 50, keyword: keyword.trim() || undefined });
      setJobs(resp.items || []);
      setTotal(resp.total || 0);
    } catch (e) {
      setJobs([]);
      setTotal(0);
      setLoadError(userFacingError(e, "任务列表加载失败"));
    } finally {
      setLoading(false);
    }
  }, [statusFilter, keyword]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { processing: 0, succeeded: 0, failed: 0 };
    for (const j of jobs) {
      if (c[j.status] !== undefined) c[j.status] += 1;
    }
    return c;
  }, [jobs]);

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <ClapperboardIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">AI小高剪辑</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">管理混剪任务，跟踪云端合成进度</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => void load()} className="flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151]">
            <RefreshCwIcon size={14} className={loading ? "animate-spin" : ""} />
            刷新
          </button>
          <button
            type="button"
            onClick={() => setShowModal(true)}
            className="flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
          >
            <PlusIcon size={14} />
            新建任务
          </button>
        </div>
      </header>

      <div className="grid shrink-0 grid-cols-3 gap-0 border-b border-[#e4e8f0] bg-white">
        {[
          { label: "处理中", value: counts.processing, icon: <Loader2Icon size={18} />, tone: "bg-blue-100 text-blue-700 ring-blue-200", accent: "bg-blue-500" },
          { label: "已完成", value: counts.succeeded, icon: <FilmIcon size={18} />, tone: "bg-emerald-100 text-emerald-700 ring-emerald-200", accent: "bg-emerald-500" },
          { label: "失败", value: counts.failed, icon: <CircleAlertIcon size={18} />, tone: "bg-red-100 text-red-700 ring-red-200", accent: "bg-red-500" },
        ].map((stat) => (
          <div key={stat.label} className="border-r border-[#f0f2f7] px-4 py-3 last:border-r-0">
            <div className="mb-2 text-[11px] font-semibold text-[#98a2b3]">{stat.label}</div>
            <div className="flex items-center gap-2">
              <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ring-1 ${stat.tone}`}>
                {stat.icon}
              </div>
              <div className="text-xl font-bold leading-none text-[#1a1f2e]">{stat.value}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="flex shrink-0 items-center gap-3 border-b border-[#e4e8f0] bg-white px-5 py-3">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-9 w-[160px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs text-[#374151] outline-none"
        >
          <option value="">全部状态</option>
          <option value="processing">处理中</option>
          <option value="succeeded">已完成</option>
          <option value="failed">失败</option>
        </select>
        <label className="relative w-[300px]">
          <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            className="h-9 w-full rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
            placeholder="搜索任务标题"
          />
        </label>
        <span className="ml-auto text-xs font-semibold text-[#667085]">
          共 <b className="text-[#2563eb]">{total}</b> 个任务
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {loadError ? (
          <div className="grid place-items-center gap-3 py-12 text-xs">
            <div className="text-rose-600">{loadError}</div>
            <button type="button" onClick={() => void load()} className="rounded-lg border border-[#e4e8f0] bg-white px-3 py-1.5 font-semibold text-[#374151]">
              重试
            </button>
          </div>
        ) : loading && jobs.length === 0 ? (
          <div className="text-xs text-[#8b95a6]">加载中…</div>
        ) : jobs.length === 0 ? (
          <div className="grid place-items-center py-12 text-xs text-[#8b95a6]">
            {keyword.trim() ? "未找到匹配的任务" : "暂无任务，点击右上角“新建任务”提交混剪"}
          </div>
        ) : (
          jobs.map((job) => (
            <JobCard key={job.job_id} job={job} onDeleted={() => void load()} />
          ))
        )}
      </div>

      {showModal ? <NewTaskModal onClose={() => setShowModal(false)} onSubmitted={() => void load()} /> : null}
    </section>
  );
}

/** 任务卡片：标题 + 中文状态 + 视频标签 + 播放/下载/删除。 */
function JobCard({ job, onDeleted }: { job: LasJobStatus; onDeleted: () => void }) {
  const displayStatus = computeDisplayStatus(job);
  const visual = statusOf(displayStatus);
  // 播放/下载可用：已归档最终视频 + 任务可交付完成（兼容 succeeded/completed） + 未删除
  const isDeliverable = job.status === "succeeded" || job.status === "completed";
  const canPlay = job.has_final_video && isDeliverable;
  // 禁用原因文案
  const disabledHint = !canPlay
    ? !isDeliverable
      ? job.status === "failed"
        ? "视频生成失败"
        : job.status === "processing_result"
        ? "视频正在整理"
        : "视频尚未生成完成"
      : !job.has_final_video
      ? job.delivery_status === "failed"
        ? "视频归档失败"
        : "暂无可用视频"
      : "暂无可用视频"
    : "";
  const [deleting, setDeleting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [mediaLoading, setMediaLoading] = useState(false);
  const [playUrl, setPlayUrl] = useState<string | null>(null);

  const handlePlay = async () => {
    if (!canPlay || mediaLoading) return;
    setMediaLoading(true);
    try {
      const url = await fetchPlayUrl(job.job_id);
      setPlayUrl(url);
    } catch (e) {
      toast.error(userFacingError(e, "获取播放地址失败"));
    } finally {
      setMediaLoading(false);
    }
  };

  const handleDownload = async () => {
    if (!canPlay || mediaLoading) return;
    setMediaLoading(true);
    try {
      const { url, filename } = await fetchDownloadUrl(job.job_id);
      // fetch blob 触发下载（避免浏览器跳转显示视频）
      const resp = await fetch(url);
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast.error(userFacingError(e, "获取下载地址失败"));
    } finally {
      setMediaLoading(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteLasJob(job.job_id);
      toast.success("任务已删除");
      onDeleted();
    } catch (e) {
      // 删除失败（含 delete_failed 部分失败）：不假装成功，任务保留可见，提示重试
      const msg = userFacingError(e, "删除失败，部分资源未清理，请重试");
      toast.error(msg);
    } finally {
      setDeleting(false);
      setConfirming(false);
    }
  };

  return (
    <article className="mb-2 rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-colors hover:bg-[#f8fafc] last:mb-0">
      <div className="flex items-start justify-between gap-4 px-5 py-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-white shadow-lg ${visual.accent}`}>
            <FilmIcon size={20} />
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-bold text-[#1a1f2e]">{job.title}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-[#667085]">
              <span className="inline-flex items-center gap-1">
                <Clock3Icon size={13} />
                {job.created_at ? new Date(job.created_at).toLocaleString() : "-"}
              </span>
            </div>
            {job.video_tags.length > 0 ? (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {job.video_tags.map((tag) => (
                  <span key={tag} className="rounded-md bg-[#eff6ff] px-2 py-0.5 text-[11px] font-semibold text-[#2563eb]">
                    {VIDEO_TAG_LABELS[tag] || tag}
                  </span>
                ))}
              </div>
            ) : null}
            {job.error_message ? (
              <div className="mt-1 text-[11px] text-rose-600">{job.error_message}</div>
            ) : null}
          </div>
        </div>
        <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold ${visual.tone}`}>
          {visual.label}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-[#eef1f6] px-[68px] py-3">
        <button
          type="button"
          onClick={() => void handlePlay()}
          disabled={!canPlay || mediaLoading}
          title={disabledHint}
          className={`inline-flex h-8 items-center gap-1 rounded-lg px-3 text-xs font-semibold ${canPlay && !mediaLoading ? "bg-[#2563eb] text-white hover:bg-[#1d4ed8]" : "cursor-not-allowed bg-[#f4f6f8] text-[#9aa3b2]"}`}
        >
          <PlayIcon size={13} />
          {mediaLoading ? "加载中…" : "播放"}
        </button>
        <button
          type="button"
          onClick={() => void handleDownload()}
          disabled={!canPlay || mediaLoading}
          title={disabledHint}
          className={`inline-flex h-8 items-center gap-1 rounded-lg px-3 text-xs font-semibold ${canPlay && !mediaLoading ? "bg-[#f4f6f8] text-[#475467] hover:bg-[#eef1f6]" : "cursor-not-allowed bg-[#f4f6f8] text-[#9aa3b2]"}`}
        >
          <DownloadIcon size={13} />
          {mediaLoading ? "加载中…" : "下载"}
        </button>
        {!canPlay ? <span className="text-[11px] text-[#98a2b3]">{disabledHint}</span> : null}
        {confirming ? (
          <span className="inline-flex h-8 items-center gap-2 rounded-lg px-2 text-xs text-rose-600">
            确认删除？
            <button type="button" onClick={() => void handleDelete()} disabled={deleting} className="rounded bg-rose-600 px-2 py-0.5 text-[11px] font-semibold text-white disabled:opacity-50">
              {deleting ? "删除中…" : "确认"}
            </button>
            <button type="button" onClick={() => setConfirming(false)} className="text-[11px] text-[#8b95a6]">
              取消
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={deleting}
            className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#f4f6f8] px-3 text-xs font-semibold text-rose-600 hover:bg-[#fee2e2] disabled:opacity-50"
          >
            <Trash2Icon size={13} />
            删除
          </button>
        )}
      </div>
      {playUrl ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={() => setPlayUrl(null)}>
          <div className="max-h-[90vh] max-w-[90vw] rounded-xl bg-white p-3" onClick={(e) => e.stopPropagation()}>
            <video src={playUrl} controls autoPlay className="max-h-[80vh] max-w-[80vw] rounded-lg" />
            <div className="mt-2 text-center">
              <button type="button" onClick={() => setPlayUrl(null)} className="rounded-lg border border-[#e4e8f0] px-3 py-1 text-xs font-semibold text-[#374151]">关闭</button>
            </div>
          </div>
        </div>
      ) : null}
    </article>
  );
}
