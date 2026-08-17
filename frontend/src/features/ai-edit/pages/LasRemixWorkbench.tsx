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
import { createLasJob, deleteLasJob, fetchAiEditMaterials, fetchDownloadLink, fetchPlayUrl, listLasJobs } from "../api";
import type { AiEditMaterial, LasJobStatus, LasVideoItem } from "../types";
import { userFacingError } from "../../../lib/userFacingError";

// 三模式配置（2026-08-17 三模式升级）：中文名 + PDF 第 4.7 节 Script 示例（不自行创作新文案）。
// 素材角色/分段/时长控件随 mode 动态显示（AC-010）。
const MODE_OPTIONS: Array<{
  value: "marketing_headtalk" | "long_real_shot" | "real_shot_headtalk";
  label: string;
  hint: string;
  scriptExample: string;
  showDuration: boolean;
  showRole: boolean;
  showSection: boolean;
}> = [
  {
    value: "marketing_headtalk",
    label: "口播营销",
    hint: "拍好的真人口播成品，最多 30 条，关键处切空镜佐证",
    showDuration: false,
    showRole: true,
    showSection: false,
    scriptExample: "剪成一条约 60 秒的产品讲解视频。开头留最能抓住人的完整表达，随后按 问题 → 功能 → 效果 → 总结 组织。删除口误、重复信息和无效停顿；同一内容多次录制时保留最后一次完整自然的表述。讲到外观、功能细节和实际操作时必须切能直接证明该信息的空镜，泛化画面不要抢占更匹配的素材；其余保持人物原画。默认硬切，只在口播切到关键细节时用轻量转场。BGM 有节奏感一点，音效克制。",
  },
  {
    value: "long_real_shot",
    label: "长实拍纪实",
    hint: "一件事的完整过程，最多 100 条，按事件顺序推进，支持目标时长",
    showDuration: true,
    showRole: true,
    showSection: false,
    scriptExample: "把这次上门维修的完整过程剪成两分半。按 到场 → 排查 → 报价确认 → 维修 → 验收 的顺序推进。开场用师傅敲门到场、说明这次来处理什么那段；结尾切在客户验收签字、双方道别。保留问题暴露和解决的完整链条，以及客户的疑问与师傅的回应（成对保留，不要只留一半）；删掉等待、重复寒暄和没有新信息的闲聊。字幕特效克制，只在关键结论处用。BGM 舒缓衬底，不要抢人声。",
  },
  {
    value: "real_shot_headtalk",
    label: "实拍 + 口播",
    hint: "前段实拍现场 + 后段口播营销，两段拼接；支持目标时长",
    showDuration: true,
    showRole: true,
    showSection: true,
    scriptExample: "整片两分钟左右。前半段用交车现场的真实过程：验车、办手续、交钥匙、叮嘱注意事项，保留现场感和原声，结尾切在交钥匙和送别；后半段接销售面向镜头的总结，讲到具体配置和服务承诺时切对应空镜。两段都删掉口误和重复表述。实拍段保持纪实调性，口播段可以有节奏一点。",
  },
];

// 素材角色/分段中文名
const ROLE_LABELS: Record<string, string> = { speech: "口播", voiceover: "配音", broll: "空镜" };
const SECTION_LABELS: Record<string, string> = { real_shot: "实拍", headtalk: "口播" };

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

/** 单个选中素材：url + 展示名 + 可选角色/分段（按 mode 显示与清理）。 */
interface MaterialSelection {
  url: string;
  displayName: string;
  role?: "speech" | "voiceover" | "broll";
  section?: "real_shot" | "headtalk";
}

/** 各 mode 合法的角色集合（用于切换 mode 时清理失效值）。 */
const MODE_ROLES: Record<string, string[]> = {
  marketing_headtalk: ["speech", "voiceover", "broll"],
  long_real_shot: ["speech", "voiceover"],
  real_shot_headtalk: ["speech", "broll"],
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
  const [mode, setMode] = useState<"marketing_headtalk" | "long_real_shot" | "real_shot_headtalk">("marketing_headtalk");
  const [selectedItems, setSelectedItems] = useState<MaterialSelection[]>([]);
  const [script, setScript] = useState("");
  const [autoScriptRef] = useState<{ current: string }>({ current: "" });
  const [targetDuration, setTargetDuration] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cloudMaterials = useMemo(() => materials.filter((m) => m.tos_presigned_url), [materials]);
  const currentModeCfg = MODE_OPTIONS.find((m) => m.value === mode) ?? MODE_OPTIONS[0];

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

  /** 切换 mode：清理失效角色/分段值（不合法控件不得只隐藏值），并处理脚本自动填充/防覆盖。 */
  const handleModeChange = (nextMode: (typeof mode)) => {
    if (nextMode === mode) return;
    setMode(nextMode);
    const nextCfg = MODE_OPTIONS.find((m) => m.value === nextMode)!;
    // 清理失效值：删除当前 mode 不合法的 role；section 一律清空（实拍+口播需重新选择/走自动分段）
    const validRoles = MODE_ROLES[nextMode];
    setSelectedItems((prev) =>
      prev.map((it) => {
        const next: MaterialSelection = { url: it.url, displayName: it.displayName };
        if (it.role && validRoles.includes(it.role)) next.role = it.role;
        return next;
      }),
    );
    // 脚本：空 或 仍等于系统自动填充内容 → 自动替换；已修改 → 确认后才替换
    const scriptModified = script.trim() !== "" && script.trim() !== autoScriptRef.current;
    if (!scriptModified) {
      setScript(nextCfg.scriptExample);
      autoScriptRef.current = nextCfg.scriptExample;
    } else {
      // 不静默覆盖：确认后才替换（计划 Frontend Contract）
      // 因 confirm 阻塞与 setState 同异步问题，此处用二次点击语义：
      // 弹出原生确认，确认则替换脚本，取消则保留商户已编辑内容（mode 切换仍生效）。
      if (window.confirm("切换模式将替换你已编辑的创作指令为对应示例，是否替换？")) {
        setScript(nextCfg.scriptExample);
        autoScriptRef.current = nextCfg.scriptExample;
      }
    }
  };

  const toggleUrl = (m: AiEditMaterial) => {
    const url = m.tos_presigned_url as string;
    setSelectedItems((prev) => {
      if (prev.some((it) => it.url === url)) {
        return prev.filter((it) => it.url !== url);
      }
      return [...prev, { url, displayName: m.display_name || m.material_id }];
    });
  };

  const updateItemRole = (url: string, role: MaterialSelection["role"]) => {
    setSelectedItems((prev) => prev.map((it) => (it.url === url ? { ...it, role } : it)));
  };

  const updateItemSection = (url: string, section: MaterialSelection["section"]) => {
    setSelectedItems((prev) => prev.map((it) => (it.url === url ? { ...it, section } : it)));
  };

  const submit = async () => {
    setError(null);
    if (selectedItems.length === 0) {
      setError("请至少选择一个已上传到云的素材");
      return;
    }
    if (!script.trim()) {
      setError("请填写创作指令");
      return;
    }
    // 目标时长仅 long_real_shot / real_shot_headtalk 支持，且需在 10~3600
    let duration: number | undefined;
    if (currentModeCfg.showDuration && targetDuration.trim() !== "") {
      duration = Number(targetDuration.trim());
      if (!Number.isInteger(duration) || duration < 10 || duration > 3600) {
        setError("目标时长需为 10~3600 秒之间的整数");
        return;
      }
    }
    // 实拍+口播：部分选中素材标了 section 时必须全部标（后端兜底校验）
    if (mode === "real_shot_headtalk") {
      const sectioned = selectedItems.filter((it) => it.section);
      if (sectioned.length > 0 && sectioned.length !== selectedItems.length) {
        setError("实拍+口播模式下分段要么全部素材都选，要么全部留自动判定");
        return;
      }
    }
    // 组装 video_urls：对象数组（含可选 role/section）
    const video_urls: LasVideoItem[] = selectedItems.map((it) => {
      const obj: LasVideoItem = { url: it.url };
      if (it.role) obj.role = it.role;
      if (it.section) obj.section = it.section;
      return obj;
    });
    setSubmitting(true);
    try {
      await createLasJob({
        video_urls,
        script: script.trim(),
        mode,
        template: "automotive_headtalk",
        ...(duration !== undefined ? { target_duration_sec: duration } : {}),
      });
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
            <p className="mt-1 text-xs text-[#8b95a6]">选择模式与已上传素材，填写创作指令，提交云端混剪</p>
          </div>
          <button type="button" onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
          {/* 模式选择 */}
          <h3 className="text-sm font-bold text-[#1a1f2e]">混剪模式</h3>
          <div className="mt-2 grid grid-cols-3 gap-2">
            {MODE_OPTIONS.map((m) => (
              <button
                key={m.value}
                type="button"
                onClick={() => handleModeChange(m.value)}
                className={`rounded-xl border px-3 py-2 text-left transition-colors ${
                  mode === m.value
                    ? "border-[#2563eb] bg-[#eff6ff] text-[#1d4ed8]"
                    : "border-[#e4e8f0] bg-white text-[#475467] hover:bg-[#f8fafc]"
                }`}
              >
                <div className="text-xs font-bold">{m.label}</div>
                <div className="mt-0.5 text-[10px] leading-snug text-[#8b95a6]">{m.hint}</div>
              </button>
            ))}
          </div>

          {/* 素材选择 */}
          <h3 className="mt-5 text-sm font-bold text-[#1a1f2e]">选择素材</h3>
          <p className="mt-1 text-xs text-[#8b95a6]">
            仅显示已上传到云的素材（在素材库上传到 TOS）
            {mode === "real_shot_headtalk" ? "；实拍+口播模式下可为每条素材指定分段，留“自动判定”由系统按原声分段" : ""}
          </p>
          <div className="mt-3 max-h-[240px] overflow-y-auto rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-3">
            {loadingMaterials ? (
              <div className="text-xs text-[#8b95a6]">加载中…</div>
            ) : cloudMaterials.length === 0 ? (
              <div className="text-xs text-[#8b95a6]">暂无已上传到云的素材，请先到素材库上传</div>
            ) : (
              cloudMaterials.map((m) => {
                const url = m.tos_presigned_url as string;
                const selected = selectedItems.find((it) => it.url === url);
                const checked = selected !== undefined;
                return (
                  <div key={m.material_id} className="flex items-center gap-2 py-1.5 text-xs text-[#475467]">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleUrl(m)}
                      className="h-3.5 w-3.5 shrink-0 rounded border-[#cbd5e1] text-[#2563eb]"
                    />
                    <span className="min-w-0 flex-1 truncate">{m.display_name || m.material_id}</span>
                    {checked && currentModeCfg.showSection ? (
                      <select
                        value={selected?.section ?? ""}
                        onChange={(e) => updateItemSection(url, (e.target.value || undefined) as MaterialSelection["section"])}
                        className="h-7 shrink-0 rounded-lg border border-[#e4e8f0] bg-white px-1.5 text-[11px] text-[#374151] outline-none"
                      >
                        <option value="">自动判定</option>
                        <option value="real_shot">实拍段</option>
                        <option value="headtalk">口播段</option>
                      </select>
                    ) : null}
                    {checked && currentModeCfg.showRole ? (
                      <select
                        value={selected?.role ?? ""}
                        onChange={(e) => updateItemRole(url, (e.target.value || undefined) as MaterialSelection["role"])}
                        className="h-7 shrink-0 rounded-lg border border-[#e4e8f0] bg-white px-1.5 text-[11px] text-[#374151] outline-none"
                      >
                        <option value="">{ROLE_LABELS.speech}（默认）</option>
                        {MODE_ROLES[mode].map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r] ?? r}
                          </option>
                        ))}
                      </select>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>

          {/* 目标时长（仅 long_real_shot / real_shot_headtalk） */}
          {currentModeCfg.showDuration ? (
            <div className="mt-4 flex items-center gap-2">
              <h3 className="shrink-0 text-sm font-bold text-[#1a1f2e]">目标时长</h3>
              <input
                type="number"
                min={10}
                max={3600}
                value={targetDuration}
                onChange={(e) => setTargetDuration(e.target.value)}
                placeholder="秒（10~3600，可留空由系统决定）"
                className="h-9 w-72 rounded-xl border border-[#e4e8f0] px-3 text-xs outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
              />
            </div>
          ) : null}

          {/* 创作指令 */}
          <div className="mt-5 flex items-center justify-between">
            <h3 className="text-sm font-bold text-[#1a1f2e]">创作指令</h3>
            <button
              type="button"
              onClick={() => {
                setScript(currentModeCfg.scriptExample);
                autoScriptRef.current = currentModeCfg.scriptExample;
              }}
              className="text-[11px] font-semibold text-[#2563eb] hover:underline"
            >
              填入当前模式示例
            </button>
          </div>
          <p className="mt-1 text-xs text-[#8b95a6]">自然语言描述目标时长、保留/删除内容、叙事顺序，最长 4000 字；切换模式可自动填入对应示例</p>
          <textarea
            value={script}
            onChange={(e) => setScript(e.target.value)}
            rows={6}
            maxLength={4000}
            placeholder={currentModeCfg.scriptExample.slice(0, 60) + "…"}
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

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    // silent=true（自动轮询）：失败保留旧列表不显示错误，避免抖动
    const silent = opts?.silent ?? false;
    if (!silent) {
      setLoading(true);
      setLoadError(null);
    }
    try {
      const resp = await listLasJobs({ status: statusFilter || undefined, page: 1, page_size: 50, keyword: keyword.trim() || undefined });
      setJobs(resp.items || []);
      setTotal(resp.total || 0);
      if (!silent) setLoadError(null);
    } catch (e) {
      if (!silent) {
        setJobs([]);
        setTotal(0);
        setLoadError(userFacingError(e, "任务列表加载失败"));
      }
      // silent 模式失败静默，保留旧列表
    } finally {
      if (!silent) setLoading(false);
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

  // 自动轮询：有生成中任务时每 15 秒刷新列表（LAS 文档建议 10-15s 轮询），
  // LAS 完成或失败后任务变终态，自动停止轮询。不阻塞 LAS 后端轮询。
  const hasGenerating = useMemo(
    () => jobs.some((j) => j.status === "processing" || j.status === "submitted" || j.status === "running"),
    [jobs],
  );
  useEffect(() => {
    if (!hasGenerating) return;
    const t = setInterval(() => void load({ silent: true }), 15000);
    return () => clearInterval(t);
  }, [hasGenerating, load]);

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

  // 伪进度条：生成中任务按已等待时间推进，完成时 100
  const isGenerating = displayStatus === "queued" || displayStatus === "running" || displayStatus === "processing" || displayStatus === "submitted";
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!isGenerating) return;
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, [isGenerating]);

  const est = job.estimated_seconds || 180;
  const elapsed = job.created_at ? Math.max(0, (Date.now() - new Date(job.created_at).getTime()) / 1000) : 0;
  const fakeProgress = isGenerating
    ? elapsed < est
      ? Math.min(80, (elapsed / est) * 80)
      : Math.min(95, 80 + ((elapsed - est) / Math.max(est, 1)) * 15)
    : job.status === "succeeded" || job.status === "completed"
      ? 100
      : 0;
  const estMin = Math.max(1, Math.floor(est / 60));
  const estMax = Math.ceil((est * 1.5) / 60);
  const elapsedMin = Math.floor(elapsed / 60);
  const elapsedSec = Math.floor(elapsed % 60);

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
      // 获取短期 token 下载链接，用 <a href> 触发浏览器原生下载（带进度条）
      const { download_url, filename } = await fetchDownloadLink(job.job_id);
      const a = document.createElement("a");
      a.href = download_url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      toast.error(userFacingError(e, "下载失败"));
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
      {isGenerating ? (
        <div className="border-t border-[#eef1f6] px-[68px] py-2.5">
          <div className="mb-1.5 flex items-center justify-between text-[11px] text-[#667085]">
            <span>预计 {estMin}~{estMax} 分钟 · 已等待 {elapsedMin}分{elapsedSec}秒</span>
            <span className="font-semibold text-[#2563eb]">{Math.round(fakeProgress)}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-[#e4e8f0]">
            <div className="h-full rounded-full bg-[#2563eb] transition-all duration-1000 ease-out" style={{ width: `${fakeProgress}%` }} />
          </div>
        </div>
      ) : null}
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
