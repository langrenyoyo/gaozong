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
  UploadCloudIcon,
  XIcon,
} from "lucide-react";
import { createLasJob, fetchAiEditMaterials, listLasJobs } from "../api";
import type { AiEditMaterial, LasJobStatus } from "../types";
import { userFacingError } from "../../../lib/userFacingError";

const SCRIPT_EXAMPLE = `剪成一条约 60 秒的汽车真人讲解视频。开头优先保留最有吸引力的车辆信息，随后按外观、座舱、配置、车况和总结组织。删除口误与重复表述，同一信息多次录制时优先保留最后一次完整自然的口播。讲到具体部位、配置、屏幕、座椅、空间或车况时，必须优先匹配能够直接证明该信息的对应空镜；泛化空镜不能抢占更匹配的素材。默认硬切，只有口播切到重点产品细节时使用轻量转场。`;

const STATUS_VISUALS: Record<string, { label: string; tone: string; accent: string }> = {
  processing: { label: "处理中", tone: "bg-blue-100 text-blue-700", accent: "bg-blue-500" },
  succeeded: { label: "已完成", tone: "bg-emerald-100 text-emerald-700", accent: "bg-emerald-500" },
  failed: { label: "失败", tone: "bg-red-100 text-red-700", accent: "bg-red-500" },
};

function statusOf(status: string) {
  return STATUS_VISUALS[status] || { label: status, tone: "bg-slate-100 text-slate-700", accent: "bg-slate-400" };
}

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
  const [statusFilter, setStatusFilter] = useState("");
  const [keyword, setKeyword] = useState("");
  const [showModal, setShowModal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await listLasJobs({ status: statusFilter || undefined, page: 1, page_size: 50 });
      setJobs(resp.items || []);
      setTotal(resp.total || 0);
    } catch {
      // 静默
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    if (!keyword.trim()) return jobs;
    return jobs.filter((j) => String(j.job_id).includes(keyword.trim()) || (j.las_task_id || "").includes(keyword.trim()));
  }, [jobs, keyword]);

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
            placeholder="搜索任务"
          />
        </label>
        <span className="ml-auto text-xs font-semibold text-[#667085]">
          共 <b className="text-[#2563eb]">{total}</b> 个任务
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {loading && filtered.length === 0 ? (
          <div className="text-xs text-[#8b95a6]">加载中…</div>
        ) : filtered.length === 0 ? (
          <div className="grid place-items-center py-12 text-xs text-[#8b95a6]">
            暂无任务，点击右上角“新建任务”提交混剪
          </div>
        ) : (
          filtered.map((job) => {
            const visual = statusOf(job.status);
            return (
              <article key={job.job_id} className="mb-2 rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-colors hover:bg-[#f8fafc] last:mb-0">
                <div className="flex items-start justify-between gap-4 px-5 py-4">
                  <div className="flex min-w-0 items-start gap-3">
                    <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-white shadow-lg ${visual.accent}`}>
                      <FilmIcon size={20} />
                    </div>
                    <div className="min-w-0">
                      <h2 className="truncate text-sm font-bold text-[#1a1f2e]">混剪任务 #{job.job_id}</h2>
                      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-[#667085]">
                        <span className="truncate text-[#98a2b3]">阶段：{job.stage || "-"}</span>
                        <span className="inline-flex items-center gap-1">
                          <Clock3Icon size={13} />
                          {job.created_at ? new Date(job.created_at).toLocaleString() : "-"}
                        </span>
                      </div>
                      {job.error_message ? (
                        <div className="mt-1 text-[11px] text-rose-600">{job.error_message}</div>
                      ) : null}
                    </div>
                  </div>
                  <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold ${visual.tone}`}>
                    {visual.label}
                  </span>
                </div>
                {job.artifacts.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-2 border-t border-[#eef1f6] px-[68px] py-3">
                    {job.artifacts.map((a) => (
                      a.url ? (
                        <a
                          key={a.artifact_type}
                          href={a.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#f4f6f8] px-3 text-xs font-semibold text-[#475467] hover:bg-[#eef1f6]"
                        >
                          {a.artifact_type.startsWith("video_") ? <PlayIcon size={13} /> : <DownloadIcon size={13} />}
                          {artifactLabel(a.artifact_type)}
                        </a>
                      ) : null
                    ))}
                  </div>
                ) : null}
              </article>
            );
          })
        )}
      </div>

      {showModal ? <NewTaskModal onClose={() => setShowModal(false)} onSubmitted={() => void load()} /> : null}
    </section>
  );
}

function artifactLabel(type: string): string {
  const labels: Record<string, string> = {
    video_subtitled: "带字幕成片",
    video_clean: "无字幕成片",
    subtitle_srt: "字幕",
    match_scheme: "剪辑方案",
    result_json: "完整结果",
  };
  return labels[type] || type;
}
