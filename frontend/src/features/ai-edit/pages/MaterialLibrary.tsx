// 小高素材库（参照 react_base_back MaterialLibrary 重做，2026-07-31）。
// 左列表（搜索 + 全部/口播/高光分类 + 日期分组卡片）+ 右详情预览 + 上传素材（TOS）。
// 不再使用私有/公共/回收站分类。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ClapperboardIcon,
  FilmIcon,
  PlayIcon,
  SearchIcon,
  Trash2Icon,
  UploadCloudIcon,
} from "lucide-react";
import { fetchAiEditMaterials, uploadMaterialToTos, deleteMaterial } from "../api";
import type { AiEditMaterial } from "../types";
import { userFacingError } from "../../../lib/userFacingError";

type CategoryKey = "全部" | "口播" | "高光";

const TYPE_CLASS: Record<string, string> = {
  口播: "bg-[#eff6ff] text-[#2563eb]",
  高光: "bg-[#d1fae5] text-[#047857]",
};

function materialCategory(m: AiEditMaterial): "口播" | "高光" | "未分类" {
  const c = (m.category || "").trim();
  if (c === "口播" || c === "spoken") return "口播";
  if (c === "高光" || c === "broll" || c === "highlight") return "高光";
  return "未分类";
}

function materialDate(m: AiEditMaterial): string {
  const d = m.created_at ? new Date(m.created_at) : null;
  if (!d || Number.isNaN(d.getTime())) return "未知日期";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

export default function MaterialLibrary({ merchantId }: { merchantId: string }) {
  void merchantId;
  const [materials, setMaterials] = useState<AiEditMaterial[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState<CategoryKey>("全部");
  const [tosUploading, setTosUploading] = useState(false);
  const [tosCategory, setTosCategory] = useState<"口播" | "高光">("口播");
  const tosFileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchAiEditMaterials();
      const items = resp.items || [];
      setMaterials(items);
      setSelectedId((cur) => cur || (items.length > 0 ? items[0].material_id : null));
    } catch (err) {
      setError(userFacingError(err, "素材加载失败，请稍后重试"));
      setMaterials([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    return materials.filter((m) => {
      const mc = materialCategory(m);
      const matchCategory = category === "全部" || mc === category;
      const matchKeyword =
        !keyword.trim() ||
        (m.display_name || "").includes(keyword.trim()) ||
        m.material_id.includes(keyword.trim());
      return matchCategory && matchKeyword;
    });
  }, [materials, keyword, category]);

  const grouped = useMemo(() => {
    const acc: Record<string, AiEditMaterial[]> = {};
    for (const item of filtered) {
      const key = materialDate(item);
      (acc[key] = acc[key] || []).push(item);
    }
    return acc;
  }, [filtered]);

  const selected = materials.find((m) => m.material_id === selectedId) || filtered[0] || null;

  const onTosPick = useCallback((cat: "口播" | "高光") => {
    setTosCategory(cat);
    tosFileInputRef.current?.click();
  }, []);

  const onTosUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      e.target.value = "";
      if (files.length === 0) return;
      setTosUploading(true);
      setError(null);
      let ok = 0;
      let fail = 0;
      for (const file of files) {
        try {
          await uploadMaterialToTos(file, tosCategory);
          ok += 1;
        } catch {
          fail += 1;
        }
      }
      setTosUploading(false);
      if (ok > 0) {
        toast.success(`已上传 ${ok} 个素材${fail > 0 ? `，${fail} 个失败` : ""}`);
        await load();
      } else if (fail > 0) {
        setError("上传失败，请稍后重试");
      }
    },
    [load],
  );

  const onDeleteMaterial = useCallback(
    async (materialId: string) => {
      if (!window.confirm("确定删除该素材？")) return;
      try {
        await deleteMaterial(materialId);
        toast.success("素材已删除");
        await load();
      } catch (err) {
        setError(userFacingError(err, "删除失败，请稍后重试"));
      }
    },
    [load],
  );

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <ClapperboardIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">小高素材库</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">管理口播和高光视频素材</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => onTosPick("口播")}
          disabled={tosUploading}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:opacity-60"
        >
          <UploadCloudIcon size={14} />
          {tosUploading ? "上传中…" : "上传素材"}
        </button>
        <input
          ref={tosFileInputRef}
          type="file"
          accept="video/*"
          multiple
          className="hidden"
          onChange={onTosUpload}
        />
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)]">
        <aside className="flex min-h-0 flex-col border-r border-[#e4e8f0] bg-white">
          <div className="border-b border-[#e4e8f0] p-4">
            <label className="relative block">
              <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
              <input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className="h-9 w-full rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                placeholder="输入名称搜索"
              />
            </label>
            <div className="mt-3 grid grid-cols-3 rounded-xl bg-[#eef2f7] p-1">
              {(["全部", "口播", "高光"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setCategory(item)}
                  className={`h-8 rounded-lg text-xs font-semibold transition-colors ${
                    category === item
                      ? "bg-white text-[#1a1f2e] shadow-[0_1px_2px_rgba(15,23,42,0.08)]"
                      : "text-[#8b95a6] hover:text-[#1a1f2e]"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {loading ? (
              <div className="text-xs text-[#8b95a6]">加载中…</div>
            ) : error ? (
              <div className="text-xs text-rose-600">{error}</div>
            ) : Object.keys(grouped).length === 0 ? (
              <div className="text-xs text-[#8b95a6]">暂无素材，点击右上角上传</div>
            ) : (
              Object.entries(grouped).map(([date, items]) => (
                <div key={date} className="mb-4 last:mb-0">
                  <div className="mb-2 text-xs font-bold text-[#667085]">{date}</div>
                  <div className="grid gap-2">
                    {items.map((item) => {
                      const active = selected?.material_id === item.material_id;
                      const mc = materialCategory(item);
                      return (
                        <button
                          key={item.material_id}
                          type="button"
                          onClick={() => setSelectedId(item.material_id)}
                          className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors ${
                            active ? "bg-[#eff6ff] ring-1 ring-[#bfdbfe]" : "hover:bg-[#f8fafc]"
                          }`}
                        >
                          <div className="relative grid h-14 w-16 shrink-0 place-items-center rounded-xl bg-[#e0edff]">
                            <FilmIcon size={20} className="text-[#2563eb]" />
                            <div className="absolute left-1/2 top-1/2 grid h-6 w-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white/90 text-[#101828]">
                              <PlayIcon size={12} fill="currentColor" />
                            </div>
                          </div>
                          <div className="min-w-0">
                            <div className="truncate text-xs font-bold text-[#1a1f2e]">
                              {item.display_name || item.material_id}
                            </div>
                            <div className="mt-1 text-[11px] text-[#98a2b3]">
                              {item.duration_seconds ? `时长 ${formatDuration(item.duration_seconds)}` : (item.tos_presigned_url ? "已上传到云" : "本机")}
                            </div>
                            {mc !== "未分类" ? (
                              <span className={`mt-1 inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${TYPE_CLASS[mc]}`}>
                                {mc}
                              </span>
                            ) : null}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>

        {selected ? (
          <div className="flex min-h-0 flex-col border-l border-[#e4e8f0] bg-white">
            <div className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
              <div>
                <h2 className="text-[15px] font-bold text-[#1a1f2e]">{selected.display_name || selected.material_id}</h2>
                <p className="mt-1 text-xs text-[#8b95a6]">
                  {materialCategory(selected)}{selected.duration_seconds ? ` · 时长 ${formatDuration(selected.duration_seconds)}` : ""} · {selected.tos_presigned_url ? "已上传到云" : "仅本机"}
                  {selected.analysis_status === "analyzing" ? " · 分析中…" : selected.analysis_status === "analyzed" ? " · 已分析" : selected.analysis_status === "failed" ? " · 分析失败" : ""}
                </p>
              </div>
              <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${TYPE_CLASS[materialCategory(selected)] || "bg-slate-100 text-slate-700"}`}>
                {materialCategory(selected)}
              </span>
            </div>

            <div className="shrink-0 bg-[#101828] p-4">
              <div className="relative grid h-[min(38vh,360px)] min-h-[240px] place-items-center overflow-hidden rounded-xl bg-[#111827]">
                {selected.tos_presigned_url ? (
                  <video
                    src={selected.tos_presigned_url}
                    controls
                    className="max-h-[360px] w-full object-contain"
                  />
                ) : (
                  <div className="text-center text-white/60">
                    <FilmIcon size={48} className="mx-auto" />
                    <p className="mt-2 text-xs">素材未上传到云，无法预览</p>
                  </div>
                )}
              </div>
            </div>

            {/* 口播文案 / 片段描述（方舟多模态分析结果） */}
            <div className="mx-5 mt-4 min-h-0 flex-1 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-4">
              <h3 className="text-sm font-bold text-[#1a1f2e]">
                {materialCategory(selected) === "高光" ? "片段描述" : "口播文案"}
              </h3>
              <p className="mt-1 text-xs text-[#98a2b3]">
                {materialCategory(selected) === "高光" ? "用于剪辑镜头匹配" : "用于匹配高光素材"}
              </p>
              {selected.analysis_status === "analyzing" ? (
                <div className="mt-3 rounded-xl bg-white p-3 text-xs text-[#8b95a6] ring-1 ring-[#eef2f6]">
                  AI 分析中，请稍候…
                </div>
              ) : selected.transcript || selected.description ? (
                <div className="mt-3 max-h-[160px] overflow-y-auto rounded-xl bg-white p-3 text-sm leading-7 text-[#374151] ring-1 ring-[#eef2f6]">
                  {selected.transcript || selected.description}
                </div>
              ) : (
                <div className="mt-3 rounded-xl bg-white p-3 text-xs text-[#8b95a6] ring-1 ring-[#eef2f6]">
                  {selected.analysis_status === "failed" ? "分析失败，请重新上传或检查 ARK_API_KEY 配置" : "暂无分析结果，上传后自动分析"}
                </div>
              )}
            </div>

            <div className="mx-5 mt-4 shrink-0 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-4">
              <h3 className="text-sm font-bold text-[#1a1f2e]">素材信息</h3>
              <div className="mt-3 space-y-2 text-xs text-[#475467]">
                <div>素材 ID：{selected.material_id}</div>
                <div>分类：{materialCategory(selected)}</div>
                {selected.duration_seconds ? <div>时长：{formatDuration(selected.duration_seconds)}</div> : null}
                {selected.width && selected.height ? <div>分辨率：{selected.width}×{selected.height}</div> : null}
                {selected.file_size_bytes ? <div>大小：{formatFileSize(selected.file_size_bytes)}</div> : null}
              </div>
            </div>

            <div className="flex shrink-0 items-center justify-between border-t border-[#e4e8f0] px-5 py-4">
              <button
                type="button"
                onClick={() => void onDeleteMaterial(selected.material_id)}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-rose-200 bg-rose-50 px-4 text-xs font-semibold text-rose-600 hover:bg-rose-100"
              >
                <Trash2Icon size={14} />
                删除素材
              </button>
              <button
                type="button"
                onClick={() => onTosPick(materialCategory(selected) === "高光" ? "高光" : "口播")}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
              >
                <UploadCloudIcon size={14} />
                上传素材
              </button>
            </div>
          </div>
        ) : (
          <div className="grid place-items-center border-l border-[#e4e8f0] bg-white text-xs text-[#8b95a6]">
            选择左侧素材查看详情
          </div>
        )}
      </div>
    </section>
  );
}
