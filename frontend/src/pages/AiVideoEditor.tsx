import {
  BadgeCheckIcon,
  ClapperboardIcon,
  Clock3Icon,
  DownloadIcon,
  CircleAlertIcon,
  FileVideo2Icon,
  ImageIcon,
  Loader2Icon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  ShieldCheckIcon,
  SparklesIcon,
  Trash2Icon,
  UploadCloudIcon,
  XIcon,
} from "lucide-react";
import { ReactNode, useState } from "react";
import { editStats, editTasks, EditTaskStatus } from "../data/videoEditData";

const statusVisuals: Record<EditTaskStatus, { tone: string; accent: string }> = {
  AI合成中: {
    tone: "bg-blue-100 text-blue-700",
    accent: "bg-blue-500 shadow-blue-500/20",
  },
  AI合成成功: {
    tone: "bg-emerald-100 text-emerald-700",
    accent: "bg-emerald-500 shadow-emerald-500/20",
  },
  AI合成失败: {
    tone: "bg-red-100 text-red-700",
    accent: "bg-red-500 shadow-red-500/20",
  },
  一键过审中: {
    tone: "bg-amber-100 text-amber-700",
    accent: "bg-amber-500 shadow-amber-500/20",
  },
  一键过审成功: {
    tone: "bg-cyan-100 text-cyan-700",
    accent: "bg-cyan-500 shadow-cyan-500/20",
  },
  一键过审失败: {
    tone: "bg-red-100 text-red-700",
    accent: "bg-red-500 shadow-red-500/20",
  },
};

const statIcons: Record<string, { icon: ReactNode; tone: string }> = {
  口播素材: { icon: <ClapperboardIcon size={18} />, tone: "bg-slate-100 text-slate-700 ring-slate-200" },
  AI合成中: { icon: <Loader2Icon size={18} />, tone: "bg-blue-100 text-blue-700 ring-blue-200" },
  AI合成失败: { icon: <CircleAlertIcon size={18} />, tone: "bg-red-100 text-red-700 ring-red-200" },
  一键过审中: { icon: <ShieldCheckIcon size={18} />, tone: "bg-amber-100 text-amber-700 ring-amber-200" },
  一键过审失败: { icon: <CircleAlertIcon size={18} />, tone: "bg-red-100 text-red-700 ring-red-200" },
  高光素材: { icon: <SparklesIcon size={18} />, tone: "bg-cyan-100 text-cyan-700 ring-cyan-200" },
  AI合成成功: { icon: <BadgeCheckIcon size={18} />, tone: "bg-emerald-100 text-emerald-700 ring-emerald-200" },
  一键过审成功: { icon: <ShieldCheckIcon size={18} />, tone: "bg-cyan-100 text-cyan-700 ring-cyan-200" },
};

const statGroups = [
  { title: "素材总览", columns: 2, labels: ["口播素材", "高光素材"] },
  { title: "AI合成", columns: 3, labels: ["AI合成中", "AI合成失败", "AI合成成功"] },
  { title: "一键过审", columns: 3, labels: ["一键过审中", "一键过审失败", "一键过审成功"] },
];

const uniqueStatuses = Array.from(new Set(editTasks.map((task) => task.status)));

function TaskActionButtons({ status }: { status: EditTaskStatus }) {
  const actions =
    status === "AI合成中"
      ? ["delete"]
      : status === "AI合成成功" || status === "一键过审失败"
        ? ["review", "play", "download", "delete"]
        : status === "AI合成失败"
          ? ["delete"]
          : ["play", "download", "delete"];

  return (
    <>
      {actions.includes("review") ? (
        <button className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#eff6ff] px-3 text-xs font-semibold text-[#2563eb]">
          <ShieldCheckIcon size={13} />
          一键过审
        </button>
      ) : null}
      {actions.includes("play") ? (
        <button className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#f4f6f8] px-3 text-xs font-semibold text-[#475467]">
          <PlayIcon size={13} />
          播放
        </button>
      ) : null}
      {actions.includes("download") ? (
        <button className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#f4f6f8] px-3 text-xs font-semibold text-[#475467]">
          <DownloadIcon size={13} />
          下载
        </button>
      ) : null}
      {actions.includes("delete") ? (
        <button className="inline-flex h-8 items-center gap-1 rounded-lg bg-red-50 px-3 text-xs font-semibold text-red-500">
          <Trash2Icon size={13} />
          删除
        </button>
      ) : null}
    </>
  );
}

function UploadModal({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<1 | 2>(1);

  return (
    <div className="fixed inset-0 z-20 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[720px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">新建剪辑任务</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">
              第一步上传口播视频，第二步上传高光视频
            </p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="px-6 py-6">
          <div className="grid place-items-center rounded-2xl border border-dashed border-[#cbd5e1] bg-[#f8fafc] px-6 py-10 text-center">
            <div className="grid h-20 w-20 place-items-center rounded-2xl bg-white text-[#2563eb] shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
              {step === 1 ? <UploadCloudIcon size={32} /> : <FileVideo2Icon size={30} />}
            </div>
            <p className="mt-4 text-sm font-semibold text-[#1a1f2e]">
              {step === 1 ? "上传完整的口播讲解视频" : "上传车辆高光视频"}
            </p>
            <p className="mt-1 text-xs text-[#8b95a6]">
              {step === 1 ? "上传后自动提取文案，用于后续匹配素材" : "可上传多个片段，AI 会分析镜头内容"}
            </p>
            <div className="mt-4 flex gap-2">
              <button className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white">上传</button>
              <button className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">素材库选择</button>
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-4">
            <div className="mb-2 text-xs font-semibold text-[#64748b]">20260104125345.mp4</div>
            <div className="grid h-24 place-items-center rounded-xl bg-white text-xs text-[#8b95a6] ring-1 ring-[#e4e8f0]">
              {step === 1 ? "文案提取中" : "AI 分析中"}
            </div>
          </div>
        </div>

        <div className="flex justify-between border-t border-[#e4e8f0] px-5 py-4">
          <button
            onClick={() => (step === 1 ? onClose() : setStep(1))}
            className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]"
          >
            {step === 1 ? "取消" : "上一步"}
          </button>
          <button
            onClick={() => (step === 1 ? setStep(2) : onClose())}
            className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
          >
            {step === 1 ? "下一步" : "提交剪辑任务"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AiVideoEditor() {
  const [showModal, setShowModal] = useState(false);
  const [autoReviewEnabled, setAutoReviewEnabled] = useState(false);

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <ClapperboardIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">AI小高剪辑</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">管理口播追分任务，跟踪每一步完成进度</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button className="flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151]">
            <RefreshCwIcon size={14} />
            刷新
          </button>
          <button
            onClick={() => setShowModal(true)}
            className="flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-3 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
          >
            <PlusIcon size={14} />
            新建任务
          </button>
        </div>
      </header>

      <div className="grid shrink-0 grid-cols-[1.1fr_1.45fr_1.45fr] gap-0 border-b border-[#e4e8f0] bg-white">
        {statGroups.map((group) => (
          <div key={group.title} className="border-r border-[#f0f2f7] px-4 py-3 last:border-r-0">
            <div className="mb-2 text-[11px] font-semibold text-[#98a2b3]">{group.title}</div>
            <div className={`grid gap-3 ${group.columns === 2 ? "grid-cols-2" : "grid-cols-3"}`}>
              {group.labels.map((label) => {
                const stat = editStats.find((item) => item.label === label);
                const visual = statIcons[label] || statIcons["口播素材"];

                return (
                  <div key={label} className="flex min-w-0 items-center gap-2">
                    <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ring-1 ${visual.tone}`}>
                      {visual.icon}
                    </div>
                    <div className="min-w-0 text-left">
                      <div className="truncate text-[11px] font-semibold text-[#667085]">{label}</div>
                      <div className="mt-1 text-xl font-bold leading-none text-[#1a1f2e]">{stat?.value || "0"}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="flex shrink-0 items-center gap-3 border-b border-[#e4e8f0] bg-white px-5 py-3">
        <select className="h-9 w-[160px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs text-[#374151] outline-none">
          <option>全部</option>
          {uniqueStatuses.map((status) => (
            <option key={status}>{status}</option>
          ))}
        </select>
        <label className="relative w-[300px]">
          <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
          <input className="h-9 w-full rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10" placeholder="搜索标题" />
        </label>
        <button
          type="button"
          onClick={() => setAutoReviewEnabled((enabled) => !enabled)}
          className={`ml-auto inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-xs font-semibold transition-smooth ${
            autoReviewEnabled
              ? "border-blue-200 bg-[#eff6ff] text-[#2563eb]"
              : "border-[#e4e8f0] bg-white text-[#64748b]"
          }`}
          aria-pressed={autoReviewEnabled}
        >
          <span className={`relative h-5 w-9 rounded-full transition-smooth ${autoReviewEnabled ? "bg-[#2563eb]" : "bg-[#d0d5dd]"}`}>
            <span className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-smooth ${autoReviewEnabled ? "translate-x-4" : "translate-x-0"}`} />
          </span>
          自动一键过审
        </button>
        <span className="text-xs font-semibold text-[#667085]">
          共 <b className="text-[#2563eb]">{editTasks.length}</b> 个任务
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {editTasks.map((task) => {
          const visual = statusVisuals[task.status];

          return (
            <article
              key={task.id}
              className="mb-2 rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-smooth hover:bg-[#f8fafc] last:mb-0"
            >
              <div className="flex items-start justify-between gap-4 px-5 py-4">
                <div className="flex min-w-0 items-start gap-3">
                  <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-white shadow-lg ${visual.accent}`}>
                    <ImageIcon size={20} />
                  </div>
                  <div className="min-w-0">
                    <h2 className="truncate text-sm font-bold text-[#1a1f2e]">{task.title}</h2>
                    <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-[#667085]">
                      <span className="truncate text-[#98a2b3]">视频标签：{task.tag}</span>
                      <span className="inline-flex items-center gap-1">
                        <Clock3Icon size={13} />
                        {task.createdAt}
                      </span>
                    </div>
                  </div>
                </div>
                <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold ${visual.tone}`}>
                  {task.status}
                </span>
              </div>
              <div className="flex items-center gap-2 border-t border-[#eef2f6] px-[68px] py-3">
                <TaskActionButtons status={task.status} />
              </div>
            </article>
          );
        })}
      </div>

      {showModal ? <UploadModal onClose={() => setShowModal(false)} /> : null}
    </section>
  );
}
