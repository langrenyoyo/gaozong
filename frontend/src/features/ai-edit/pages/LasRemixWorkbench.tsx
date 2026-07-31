// AI剪辑 LAS speech_auto 云端混剪工作台（2026-07-31 重做）。
// 纯 LAS 云端方案：填素材地址 + script → 提交 → 轮询进度 → 预览/下载产物。
// 不做本地 FFmpeg/9100 规划（LAS 已全包）。

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  DownloadIcon,
  FilmIcon,
  LoaderIcon,
  PlayIcon,
  SendIcon,
} from "lucide-react";
import { createLasJob, fetchAiEditMaterials, getLasJob } from "../api";
import type { AiEditMaterial, LasJobStatus } from "../types";
import { userFacingError } from "../../../lib/userFacingError";
import ModuleTabs from "../../../components/ModuleTabs";

const SCRIPT_EXAMPLE = `剪成一条约 60 秒的汽车真人讲解视频。开头优先保留最有吸引力的车辆信息，随后按外观、座舱、配置、车况和总结组织。删除口误与重复表述，同一信息多次录制时优先保留最后一次完整自然的口播。讲到具体部位、配置、屏幕、座椅、空间或车况时，必须优先匹配能够直接证明该信息的对应空镜；泛化空镜不能抢占更匹配的素材。默认硬切，只有口播切到重点产品细节时使用轻量转场。`;

const TERMINAL_STATUSES = ["succeeded", "failed"];

export default function LasRemixWorkbench({ merchantId }: { merchantId: string }) {
  void merchantId; // 商户上下文由 9000 注入，前端不自报
  const [videoUrlsText, setVideoUrlsText] = useState("");
  const [script, setScript] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<LasJobStatus | null>(null);
  const [polling, setPolling] = useState(false);
  const [showMaterialPicker, setShowMaterialPicker] = useState(false);
  const [materials, setMaterials] = useState<AiEditMaterial[]>([]);
  const [materialLoading, setMaterialLoading] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cloudMaterials = materials.filter((m) => m.tos_presigned_url);

  const loadMaterials = useCallback(async () => {
    setMaterialLoading(true);
    try {
      const resp = await fetchAiEditMaterials();
      setMaterials(resp.items || []);
    } catch {
      // 静默：素材加载失败不阻断混剪
    } finally {
      setMaterialLoading(false);
    }
  }, []);

  const toggleMaterialUrl = (url: string) => {
    const current = videoUrlsText
      .split(/[\n,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const next = current.includes(url) ? current.filter((u) => u !== url) : [...current, url];
    setVideoUrlsText(next.join("\n"));
  };

  const selectedUrls = new Set(
    videoUrlsText.split(/[\n,，]/).map((s) => s.trim()).filter(Boolean),
  );

  const videoUrls = videoUrlsText
    .split(/[\n,，]/)
    .map((s) => s.trim())
    .filter(Boolean);

  const clearPollTimer = () => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

  const pollJob = useCallback(async (jobId: number) => {
    setPolling(true);
    try {
      const data = await getLasJob(jobId);
      setJob(data);
      if (!TERMINAL_STATUSES.includes(data.status)) {
        pollTimer.current = setTimeout(() => void pollJob(jobId), 5000);
      }
    } catch (err) {
      setError(userFacingError(err, "查询任务状态失败，请稍后重试"));
    } finally {
      setPolling(false);
    }
  }, []);

  useEffect(() => {
    return clearPollTimer;
  }, []);

  const submit = async () => {
    setError(null);
    if (videoUrls.length === 0) {
      setError("请至少填写一个视频地址（tos:// 或 https 预签名）");
      return;
    }
    if (videoUrls.length > 30) {
      setError("视频数量不能超过 30 个");
      return;
    }
    if (!script.trim()) {
      setError("请填写创作指令（script）");
      return;
    }
    if (script.length > 4000) {
      setError("创作指令不能超过 4000 字");
      return;
    }
    setSubmitting(true);
    try {
      const data = await createLasJob({
        video_urls: videoUrls,
        script: script.trim(),
        template: "automotive_headtalk",
      });
      setJob(data);
      toast.success("任务已提交，正在云端混剪");
      void pollJob(data.job_id);
    } catch (err) {
      setError(userFacingError(err, "提交失败，请稍后重试"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto bg-[#f3f6fa] p-6">
      <header className="flex items-center gap-3">
        <FilmIcon size={22} className="text-[#2563eb]" />
        <div>
          <h1 className="text-[15px] font-bold text-[#1a1f2e]">AI小高剪辑</h1>
          <p className="mt-1 text-xs text-[#8b95a6]">
            填写素材地址与创作指令，提交后云端自动剪辑（识别口播、删口误、匹配空镜、生成字幕）。每次输出一条成片。
          </p>
          <ModuleTabs items={[
            { label: "素材库", path: "/ai-edit/materials" },
            { label: "LAS 混剪工作台", path: "/ai-edit/editor" },
          ]} />
        </div>
      </header>

      <section className="rounded-xl border border-[#e4e8f0] bg-white p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-[#1a1f2e]">素材地址</h2>
          <button
            type="button"
            onClick={() => {
              setShowMaterialPicker((v) => !v);
              if (!showMaterialPicker) void loadMaterials();
            }}
            className="text-[11px] font-semibold text-[#2563eb] hover:underline"
          >
            {showMaterialPicker ? "收起素材库" : "从素材库选择"}
          </button>
        </div>
        <p className="mt-1 text-[11px] text-[#8b95a6]">
          每行一个或用逗号分隔；支持 tos:// 或 https 预签名地址，最多 30 个。素材库中已上传到云的素材可直接勾选。
        </p>
        {showMaterialPicker ? (
          <div className="mt-2 max-h-[200px] overflow-y-auto rounded-md border border-[#eef1f6] p-2">
            {materialLoading ? (
              <div className="text-[11px] text-[#8b95a6]">加载中…</div>
            ) : cloudMaterials.length === 0 ? (
              <div className="text-[11px] text-[#8b95a6]">暂无已上传到云的素材，请先在素材库上传到 TOS</div>
            ) : (
              cloudMaterials.map((m) => {
                const url = m.tos_presigned_url as string;
                const checked = selectedUrls.has(url);
                return (
                  <label key={m.material_id} className="flex items-center gap-2 py-1 text-xs text-[#475467]">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleMaterialUrl(url)}
                      className="h-3.5 w-3.5 rounded border-[#cbd5e1] text-[#2563eb]"
                    />
                    <span className="truncate">{m.display_name || m.material_id}</span>
                  </label>
                );
              })
            )}
          </div>
        ) : null}
        <textarea
          value={videoUrlsText}
          onChange={(e) => setVideoUrlsText(e.target.value)}
          rows={4}
          placeholder={"https://example.com/material-01.mp4\nhttps://example.com/material-02.mp4\ntos://bucket/path/video.mp4"}
          className="mt-2 w-full resize-y rounded-md border border-[#e4e8f0] px-3 py-2 text-xs text-[#1a1f2e] focus:border-[#2563eb] focus:outline-none"
        />
        <div className="mt-1 text-right text-[10px] text-[#8b95a6]">{videoUrls.length} 个</div>
      </section>

      <section className="rounded-xl border border-[#e4e8f0] bg-white p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-[#1a1f2e]">创作指令</h2>
          <button
            type="button"
            onClick={() => setScript(SCRIPT_EXAMPLE)}
            className="text-[11px] font-semibold text-[#2563eb] hover:underline"
          >
            填入汽车口播示例
          </button>
        </div>
        <p className="mt-1 text-[11px] text-[#8b95a6]">
          自然语言描述目标时长、保留/删除内容、叙事顺序、必须展示的画面、字幕转场偏好。最长 4000 字。
        </p>
        <textarea
          value={script}
          onChange={(e) => setScript(e.target.value)}
          rows={6}
          maxLength={4000}
          placeholder="如：剪成一条约 60 秒的汽车真人讲解视频，删除口误与重复表述，讲到具体配置时优先展示对应空镜……"
          className="mt-2 w-full resize-y rounded-md border border-[#e4e8f0] px-3 py-2 text-xs text-[#1a1f2e] focus:border-[#2563eb] focus:outline-none"
        />
        <div className="mt-1 text-right text-[10px] text-[#8b95a6]">{script.length}/4000</div>
      </section>

      {error ? (
        <div className="flex items-center gap-2 rounded-md border border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-700">
          <AlertCircleIcon size={14} />
          {error}
        </div>
      ) : null}

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void submit()}
          disabled={submitting}
          className="inline-flex h-10 items-center gap-2 rounded-md bg-[#2563eb] px-5 text-sm font-semibold text-white hover:bg-[#1d4ed8] disabled:opacity-60"
        >
          {submitting ? <LoaderIcon size={16} className="animate-spin" /> : <SendIcon size={16} />}
          {submitting ? "提交中…" : "提交混剪"}
        </button>
      </div>

      {job ? (
        <section className="rounded-xl border border-[#e4e8f0] bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-[#1a1f2e]">任务状态</h2>
            <span className="text-[11px] text-[#8b95a6]">任务 #{job.job_id}</span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
            <StatusBadge status={job.status} />
            <span className="text-[#8b95a6]">阶段：{job.stage || "-"}</span>
            {polling ? <LoaderIcon size={13} className="animate-spin text-[#8b95a6]" /> : null}
          </div>
          {job.error_message ? (
            <div className="mt-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
              {job.error_message}
            </div>
          ) : null}

          {job.artifacts.length > 0 ? (
            <div className="mt-4 space-y-2">
              <h3 className="text-xs font-bold text-[#1a1f2e]">产物</h3>
              {job.artifacts.map((a) => (
                <div key={a.artifact_type} className="flex items-center justify-between rounded-md border border-[#eef1f6] px-3 py-2 text-xs">
                  <span className="font-semibold text-[#475467]">{artifactLabel(a.artifact_type)}</span>
                  {a.url ? (
                    <div className="flex gap-2">
                      {isVideo(a.artifact_type) ? (
                        <a href={a.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[#2563eb] hover:underline">
                          <PlayIcon size={13} /> 预览
                        </a>
                      ) : null}
                      <a href={a.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[#475467] hover:underline">
                        <DownloadIcon size={13} /> 下载
                      </a>
                    </div>
                  ) : (
                    <span className="text-[#8b95a6]">无</span>
                  )}
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    processing: { label: "处理中", cls: "bg-blue-100 text-blue-700" },
    succeeded: { label: "已完成", cls: "bg-emerald-100 text-emerald-700" },
    failed: { label: "失败", cls: "bg-rose-100 text-rose-700" },
  };
  const item = map[status] || { label: status, cls: "bg-slate-100 text-slate-700" };
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ${item.cls}`}>
      {status === "succeeded" ? <CheckCircle2Icon size={12} /> : null}
      {item.label}
    </span>
  );
}

function artifactLabel(type: string): string {
  const labels: Record<string, string> = {
    video_subtitled: "带字幕成片（推荐）",
    video_clean: "无字幕成片",
    subtitle_srt: "字幕文件",
    match_scheme: "剪辑方案",
    result_json: "完整结果",
  };
  return labels[type] || type;
}

function isVideo(type: string): boolean {
  return type === "video_subtitled" || type === "video_clean";
}
