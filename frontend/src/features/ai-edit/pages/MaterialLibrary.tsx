// Phase 12 Task 9 AI 剪辑素材库。
// 冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §10/§11。
//
// 三个标签页：私有素材（merchant scope）/ 平台公共（platform scope）/ 回收站（deleted_at 非空）。
// 素材元数据来源 9000（fetchAiEditMaterials，商户隔离，公共 Out 不含 storage_key/merchant_id/绝对路径）。
// 本机文件导入与删除走 127.0.0.1:19000（localApi，token 映射商户，前端不自报 merchant_id）。
// 不引入假素材、假任务；不出现已取消的过审入口（CANCELLED_BY_CUSTOMER）。

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  ClockIcon,
  RefreshCwIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { fetchAiEditMaterials } from "../api";
import { deleteLocalMaterial, importLocalMaterial } from "../localApi";
import type { AiEditMaterial, AiEditMaterialScope } from "../types";

type TabKey = "merchant" | "platform" | "trash";

const TAB_LABELS: Record<TabKey, string> = {
  merchant: "私有素材",
  platform: "平台公共",
  trash: "回收站",
};

const SCOPE_LABELS: Record<AiEditMaterialScope, string> = {
  merchant: "私有",
  platform: "公共",
};

/** 统一错误信息：兼容 axios（9000）与 fetch（19000）两种错误形态。 */
function resolveError(err: unknown): string {
  if (err && typeof err === "object") {
    const anyErr = err as {
      response?: { data?: { message?: string; detail?: string | { message?: string } } };
      message?: string;
    };
    const detail = anyErr.response?.data?.detail;
    if (detail && typeof detail === "object" && detail.message) return detail.message;
    if (typeof detail === "string") return detail;
    return anyErr.response?.data?.message || anyErr.message || "请求失败";
  }
  return err instanceof Error ? err.message : "请求失败";
}

/** 状态点：用颜色区分待分析/分析中/已分析/失败。 */
function statusBadge(status: string | null | undefined): { label: string; className: string } {
  const s = (status || "").toLowerCase();
  if (s === "succeeded" || s === "analyzed" || s === "done")
    return { label: status || "完成", className: "text-emerald-600 bg-emerald-50" };
  if (s === "running" || s === "analyzing" || s === "pending")
    return { label: status || "处理中", className: "text-amber-600 bg-amber-50" };
  if (s === "failed" || s === "error")
    return { label: status || "失败", className: "text-rose-600 bg-rose-50" };
  if (!status) return { label: "待分析", className: "text-slate-500 bg-slate-100" };
  return { label: status, className: "text-slate-600 bg-slate-100" };
}

export default function MaterialLibrary() {
  const [materials, setMaterials] = useState<AiEditMaterial[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("merchant");
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchAiEditMaterials();
      setMaterials(resp.items || []);
    } catch (err) {
      setError(resolveError(err));
      setMaterials([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = materials.filter((m) => {
    if (tab === "trash") return Boolean(m.deleted_at);
    if (tab === "platform") return m.scope === "platform" && !m.deleted_at;
    return m.scope === "merchant" && !m.deleted_at;
  });

  const onPickFile = useCallback(async () => {
    fileInputRef.current?.click();
  }, []);

  const onFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      // 本机素材 ID：时间戳 + 文件名片段，避免冲突；后端按商户隔离。
      const materialId = `mat_${Date.now()}_${file.name.replace(/[^\w.-]/g, "_").slice(0, 32)}`;
      setImporting(true);
      try {
        const result = await importLocalMaterial(file, materialId);
        toast.success(`本机导入成功：${result.material_id}（${result.size_bytes} 字节）`);
        // 导入后刷新 9000 列表（后端同步到 9000 元数据后才会出现）。
        await load();
      } catch (err) {
        toast.error(`本机导入失败：${resolveError(err)}`);
      } finally {
        setImporting(false);
      }
    },
    [load],
  );

  const onDelete = useCallback(
    async (materialId: string) => {
      if (!window.confirm("确认删除该本机素材？将进入 7 天回收站。")) return;
      try {
        await deleteLocalMaterial(materialId);
        toast.success("已移入回收站");
        await load();
      } catch (err) {
        toast.error(`删除失败：${resolveError(err)}`);
      }
    },
    [load],
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex items-center justify-between border-b border-[#e4e8f0] bg-white px-6 py-4">
        <div>
          <h1 className="text-lg font-bold text-[#1a1f2e]">小高素材库</h1>
          <p className="mt-1 text-xs text-[#8b95a6]">
            私有/公共素材与回收站；本机导入由小高AI微信助手（127.0.0.1:19000）处理。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1 rounded-lg border border-[#e4e8f0] bg-white px-3 py-2 text-xs font-medium text-[#1a1f2e] hover:bg-[#f3f6fa] disabled:opacity-50"
          >
            <RefreshCwIcon className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
          <button
            type="button"
            onClick={onPickFile}
            disabled={importing || tab === "trash"}
            className="inline-flex items-center gap-1 rounded-lg bg-[#1a1f2e] px-3 py-2 text-xs font-medium text-white hover:bg-[#2a3142] disabled:opacity-50"
          >
            <UploadIcon className="h-3.5 w-3.5" />
            {importing ? "导入中…" : "导入本机素材"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={onFileChange}
          />
        </div>
      </header>

      <nav className="flex items-center gap-1 border-b border-[#e4e8f0] bg-white px-6">
        {(Object.keys(TAB_LABELS) as TabKey[]).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
              tab === key
                ? "border-[#1a1f2e] text-[#1a1f2e]"
                : "border-transparent text-[#8b95a6] hover:text-[#1a1f2e]"
            }`}
          >
            {TAB_LABELS[key]}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
        {error ? (
          <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
            <AlertCircleIcon className="mt-0.5 h-4 w-4 shrink-0" />
            <span>素材加载失败：{error}</span>
          </div>
        ) : loading ? (
          <div className="grid h-32 place-items-center text-sm text-[#8b95a6]">加载中…</div>
        ) : filtered.length === 0 ? (
          <div className="grid h-32 place-items-center rounded-xl border border-dashed border-[#e4e8f0] bg-white text-sm text-[#8b95a6]">
            {tab === "trash" ? "回收站为空" : "暂无素材，点击右上角导入"}
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-[#e4e8f0] bg-white">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#f9fafb] text-xs text-[#8b95a6]">
                <tr>
                  <th className="px-4 py-3 font-medium">素材 ID</th>
                  <th className="px-4 py-3 font-medium">范围</th>
                  <th className="px-4 py-3 font-medium">类型</th>
                  <th className="px-4 py-3 font-medium">分析状态</th>
                  <th className="px-4 py-3 font-medium">增稳状态</th>
                  <th className="px-4 py-3 font-medium">创建时间</th>
                  <th className="px-4 py-3 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f1f4f9]">
                {filtered.map((m) => {
                  const analysis = statusBadge(m.analysis_status);
                  const stab = statusBadge(m.stabilization_status);
                  return (
                    <tr key={m.material_id} className="hover:bg-[#f9fafb]">
                      <td className="px-4 py-3 font-mono text-xs text-[#1a1f2e]">{m.material_id}</td>
                      <td className="px-4 py-3">
                        <span className="rounded px-1.5 py-0.5 text-xs text-slate-600 bg-slate-100">
                          {SCOPE_LABELS[m.scope] || m.scope}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[#5a6478]">{m.media_type || "-"}</td>
                      <td className="px-4 py-3">
                        <span className={`rounded px-1.5 py-0.5 text-xs ${analysis.className}`}>
                          {analysis.label}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`rounded px-1.5 py-0.5 text-xs ${stab.className}`}>
                          {stab.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-[#8b95a6]">
                        {m.created_at
                          ? new Date(m.created_at).toLocaleString("zh-CN", { hour12: false })
                          : "-"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {tab === "trash" ? (
                          <span className="inline-flex items-center gap-1 text-xs text-[#8b95a6]">
                            <ClockIcon className="h-3.5 w-3.5" />
                            {m.purge_after
                              ? `将于 ${new Date(m.purge_after).toLocaleDateString("zh-CN")} 清除`
                              : "待清除"}
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => onDelete(m.material_id)}
                            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-rose-600 hover:bg-rose-50"
                          >
                            <Trash2Icon className="h-3.5 w-3.5" />
                            删除
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="flex items-center justify-between border-t border-[#f1f4f9] px-4 py-2 text-xs text-[#8b95a6]">
              <span className="inline-flex items-center gap-1">
                <CheckCircle2Icon className="h-3.5 w-3.5 text-emerald-500" />
                共 {filtered.length} 条（来自 9000 真实素材，商户隔离）
              </span>
              <span className="font-mono">
                {filtered[0]?.source_sha256?.slice(0, 12) || "—"}…
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
