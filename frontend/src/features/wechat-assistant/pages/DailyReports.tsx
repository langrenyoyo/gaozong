/**
 * Phase 8 Task 8：小高AI微信助手 - 每日报表后台页面。
 *
 * 消费 Task 7 接口：生成、重试、列表、安全下载。
 * 权限以后端为准：普通报表走 auto_wechat:agent，线索溯源需 auto_wechat:leads。
 * 前端只做能力入口展示（有 leads 才显示 trace 单类选项），不伪造权限绕过。
 * 不接触 storage_key/绝对路径/token；下载文件名来自后端 file_name。
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  DownloadIcon,
  FileSpreadsheetIcon,
  Loader2Icon,
  RefreshCwIcon,
} from "lucide-react";
import type { AppUser } from "../../../App";
import { PERMISSIONS, hasPermission } from "../../capabilities";
import { getApiErrorCode } from "../../../api/client";
import {
  downloadDailyReport,
  fetchDailyReports,
  generateDailyReports,
  regenerateDailyReport,
} from "../../../api/dailyReports";
import type {
  DailyReportJobItem,
  DailyReportListQuery,
  DailyReportType,
  SkippedReport,
} from "../../../api/types";
import { formatDateTimeLocal } from "../../../lib/datetime";

const REPORT_TYPE_LABELS: Record<string, string> = {
  short_video_live_lead: "留资管理表",
  daily_sales_feedback: "每日销售反馈表",
  lead_trace: "线索溯源表",
  sales_unit_cost: "销售单车成本表",
};

const STATUS_LABELS: Record<string, { label: string; tone: string }> = {
  none: { label: "待生成", tone: "text-slate-500" },
  generating: { label: "生成中", tone: "text-amber-600" },
  generated: { label: "已完成", tone: "text-emerald-600" },
  partial: { label: "部分完成", tone: "text-blue-600" },
  failed: { label: "失败", tone: "text-rose-600" },
};

const SKIP_REASON_LABELS: Record<string, string> = {
  PERMISSION_DENIED: "当前账号缺少 auto_wechat:leads 权限",
};

function todayStr(): string {
  // 自然日（浏览器本地时区），避免时区漂移；传给后端固定 YYYY-MM-DD
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function diagnosticsText(job: DailyReportJobItem): string {
  if (!job.diagnostics || job.diagnostics.length === 0) return "";
  return job.diagnostics
    .map((d) => (d.exception_type ? `${d.code}(${d.exception_type})×${d.count}` : `${d.code}×${d.count}`))
    .join("，");
}

function triggerBlobDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName || "daily_report.xlsx";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function DailyReports({ user }: { user: AppUser }) {
  const canLeads = hasPermission(user, PERMISSIONS.leads);
  const [reportDay, setReportDay] = useState<string>(todayStr());
  const [reportType, setReportType] = useState<string>("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [filterType, setFilterType] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [records, setRecords] = useState<DailyReportJobItem[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<SkippedReport[]>([]);
  const [generating, setGenerating] = useState(false);
  const [regeneratingId, setRegeneratingId] = useState<number | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);

  const loadList = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const query: DailyReportListQuery = {
        page,
        page_size: pageSize,
        report_type: filterType || undefined,
        status: filterStatus || undefined,
      };
      const resp = await fetchDailyReports(query);
      setRecords(resp.records || []);
      setTotal(resp.total || 0);
    } catch (err) {
      setRecords([]);
      setTotal(0);
      setListError(err instanceof Error ? err.message : "日报列表加载失败");
    } finally {
      setListLoading(false);
    }
  }, [page, pageSize, filterType, filterStatus]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const handleGenerate = async () => {
    if (!reportDay) {
      toast.error("请选择报表日期");
      return;
    }
    setGenerating(true);
    try {
      const resp = await generateDailyReports({
        report_day: reportDay,
        report_type: reportType ? (reportType as DailyReportType) : undefined,
      });
      setSkipped(resp.skipped || []);
      const ok = resp.jobs.length;
      const fail = resp.jobs.filter((j) => j.status === "failed").length;
      if (fail > 0) {
        toast.warning(`生成完成：${ok} 个任务，其中 ${fail} 个失败，请查看诊断或重试`);
      } else {
        toast.success(`已生成 ${ok} 个日报任务`);
      }
      setPage(1);
      await loadList();
    } catch (err) {
      const code = getApiErrorCode(err);
      if (code === "PERMISSION_DENIED") {
        toast.error("当前账号缺少所需权限（线索溯源需 auto_wechat:leads）");
      } else {
        toast.error(err instanceof Error ? err.message : "日报生成失败");
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleRegenerate = async (job: DailyReportJobItem) => {
    setRegeneratingId(job.id);
    try {
      await regenerateDailyReport(job.id);
      toast.success(`${REPORT_TYPE_LABELS[job.report_type] || job.report_type} 已重新生成`);
      await loadList();
    } catch (err) {
      const code = getApiErrorCode(err);
      if (code === "DAILY_REPORT_GENERATING") {
        toast.warning("任务正在生成中，请稍后重试");
      } else if (code === "PERMISSION_DENIED") {
        toast.error("当前账号缺少所需权限");
      } else if (code === "DAILY_REPORT_NOT_FOUND") {
        toast.error("任务不存在或已不属于当前商户");
      } else {
        toast.error(err instanceof Error ? err.message : "重试失败");
      }
    } finally {
      setRegeneratingId(null);
    }
  };

  const handleDownload = async (job: DailyReportJobItem) => {
    setDownloadingId(job.id);
    try {
      const blob = await downloadDailyReport(job.id);
      // 文件名来自后端 file_name，前端不拼路径
      triggerBlobDownload(blob, job.file_name || `daily_report_${job.id}.xlsx`);
      toast.success("已开始下载");
    } catch (err) {
      const code = getApiErrorCode(err);
      if (code === "DAILY_REPORT_NOT_FOUND") {
        toast.error("文件不可用或已被校验拦截，请重新生成后再下载");
      } else if (code === "PERMISSION_DENIED") {
        toast.error("当前账号缺少下载该报表的权限");
      } else {
        toast.error(err instanceof Error ? err.message : "下载失败");
      }
    } finally {
      setDownloadingId(null);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <section className="flex h-full flex-col overflow-auto bg-[#f3f6fa]">
      <header className="border-b border-[#e4e8f0] bg-white px-6 py-4">
        <h1 className="text-[15px] font-bold text-[#1a1f2e]">每日报表</h1>
        <p className="mt-1 text-xs text-[#8b95a6]">
          生成留资管理、每日销售反馈、销售单车成本与线索溯源四类日报；下载文件由后端按可信商户校验后返回。
        </p>
      </header>

      <div className="flex-1 space-y-4 p-6">
        {/* 操作区 */}
        <div className="rounded-2xl border border-[#e4e8f0] bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="mb-1 block text-xs font-semibold text-[#64748b]">报表日期（自然日）</label>
              <input
                type="date"
                value={reportDay}
                onChange={(e) => setReportDay(e.target.value)}
                className="h-9 w-44 rounded-xl border border-[#e4e8f0] bg-white px-3 text-sm text-[#1a1f2e] focus:outline-none focus:ring-2 focus:ring-[#2563eb]/30"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-[#64748b]">报表类型</label>
              <select
                value={reportType}
                onChange={(e) => setReportType(e.target.value)}
                className="h-9 w-48 rounded-xl border border-[#e4e8f0] bg-white px-3 text-sm text-[#1a1f2e] focus:outline-none focus:ring-2 focus:ring-[#2563eb]/30"
              >
                <option value="">默认集（四类）</option>
                <option value="short_video_live_lead">留资管理表</option>
                <option value="daily_sales_feedback">每日销售反馈表</option>
                <option value="sales_unit_cost">销售单车成本表</option>
                {canLeads ? (
                  <option value="lead_trace">线索溯源表（需 leads 权限）</option>
                ) : null}
              </select>
            </div>
            <button
              type="button"
              onClick={handleGenerate}
              disabled={generating}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:opacity-60"
            >
              {generating ? <Loader2Icon size={14} className="animate-spin" /> : <RefreshCwIcon size={14} />}
              {generating ? "生成中" : "生成日报"}
            </button>
            {!canLeads ? (
              <span className="text-[11px] text-[#94a3b8]">
                线索溯源需 auto_wechat:leads 权限；默认集生成时会自动跳过并在下方提示原因。
              </span>
            ) : null}
          </div>

          {/* skipped 结构化展示：不吞掉权限不足等原因 */}
          {skipped.length > 0 ? (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3">
              <p className="text-xs font-semibold text-amber-800">部分报表已跳过：</p>
              <ul className="mt-1 space-y-1">
                {skipped.map((s, idx) => (
                  <li key={`${s.report_type}-${idx}`} className="text-[11px] leading-5 text-amber-700">
                    <span className="font-semibold">{REPORT_TYPE_LABELS[s.report_type] || s.report_type}</span>
                    {s.variant ? `（${s.variant}）` : ""}：{SKIP_REASON_LABELS[s.reason] || s.reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        {/* 筛选 + 列表 */}
        <div className="rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex flex-wrap items-center gap-3 border-b border-[#e4e8f0] px-5 py-3">
            <span className="text-sm font-bold text-[#1a1f2e]">任务列表</span>
            <select
              value={filterType}
              onChange={(e) => {
                setFilterType(e.target.value);
                setPage(1);
              }}
              className="h-8 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs text-[#1a1f2e]"
            >
              <option value="">全部类型</option>
              <option value="short_video_live_lead">留资管理表</option>
              <option value="daily_sales_feedback">每日销售反馈表</option>
              <option value="sales_unit_cost">销售单车成本表</option>
              <option value="lead_trace">线索溯源表</option>
            </select>
            <select
              value={filterStatus}
              onChange={(e) => {
                setFilterStatus(e.target.value);
                setPage(1);
              }}
              className="h-8 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs text-[#1a1f2e]"
            >
              <option value="">全部状态</option>
              <option value="generated">已完成</option>
              <option value="partial">部分完成</option>
              <option value="failed">失败</option>
              <option value="generating">生成中</option>
            </select>
            <button
              type="button"
              onClick={loadList}
              className="ml-auto inline-flex h-8 items-center gap-1 rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151] hover:bg-[#f4f6f8]"
            >
              <RefreshCwIcon size={12} /> 刷新
            </button>
          </div>

          {listError ? (
            <div className="px-5 py-6 text-xs text-rose-600">{listError}</div>
          ) : null}

          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-xs">
              <thead className="bg-[#f8fafc] text-[11px] uppercase tracking-wide text-[#8b95a6]">
                <tr>
                  <th className="px-5 py-3 font-semibold">报表日期</th>
                  <th className="px-5 py-3 font-semibold">类型</th>
                  <th className="px-5 py-3 font-semibold">变体</th>
                  <th className="px-5 py-3 font-semibold">状态</th>
                  <th className="px-5 py-3 font-semibold">文件</th>
                  <th className="px-5 py-3 font-semibold">诊断</th>
                  <th className="px-5 py-3 font-semibold">生成时间</th>
                  <th className="px-5 py-3 text-right font-semibold">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#eef1f6]">
                {listLoading ? (
                  <tr>
                    <td colSpan={8} className="px-5 py-8 text-center text-[#8b95a6]">
                      <Loader2Icon size={16} className="mr-2 inline animate-spin" />
                      加载中...
                    </td>
                  </tr>
                ) : records.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-5 py-8 text-center text-[#8b95a6]">
                      暂无日报任务，请先生成。
                    </td>
                  </tr>
                ) : (
                  records.map((job) => {
                    const statusMeta = STATUS_LABELS[job.status] || { label: job.status, tone: "text-slate-500" };
                    const diag = diagnosticsText(job);
                    const isGenerating = job.status === "generating";
                    return (
                      <tr key={job.id} className="hover:bg-[#f8fafc]">
                        <td className="px-5 py-3 text-[#1a1f2e]">{job.report_day}</td>
                        <td className="px-5 py-3 text-[#1a1f2e]">
                          <span className="inline-flex items-center gap-1">
                            <FileSpreadsheetIcon size={12} className="text-[#2563eb]" />
                            {REPORT_TYPE_LABELS[job.report_type] || job.report_type}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-[#64748b]">{job.report_variant}</td>
                        <td className="px-5 py-3">
                          <span className={`font-semibold ${statusMeta.tone}`}>{statusMeta.label}</span>
                          {job.is_previous_artifact ? (
                            <span className="ml-1 text-[10px] text-[#94a3b8]">（展示上次成功文件）</span>
                          ) : null}
                        </td>
                        <td className="px-5 py-3 text-[#64748b]">
                          {job.artifact_status === "available" ? (
                            <span>{job.file_name || "可下载"}</span>
                          ) : (
                            <span className="text-[#94a3b8]">未生成</span>
                          )}
                        </td>
                        <td className="max-w-[220px] px-5 py-3 text-[#94a3b8]" title={diag}>
                          {diag || "—"}
                        </td>
                        <td className="px-5 py-3 text-[#94a3b8]">
                          {job.generated_at ? formatDateTimeLocal(job.generated_at) : "—"}
                        </td>
                        <td className="px-5 py-3">
                          <div className="flex justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => handleDownload(job)}
                              disabled={!job.download_available || downloadingId === job.id}
                              className="inline-flex h-7 items-center gap-1 rounded-lg border border-[#e4e8f0] bg-white px-2.5 text-[11px] font-semibold text-[#374151] hover:bg-[#f4f6f8] disabled:cursor-not-allowed disabled:opacity-50"
                              title={job.download_available ? "下载" : "文件不可用"}
                            >
                              {downloadingId === job.id ? <Loader2Icon size={12} className="animate-spin" /> : <DownloadIcon size={12} />}
                              下载
                            </button>
                            <button
                              type="button"
                              onClick={() => handleRegenerate(job)}
                              disabled={isGenerating || regeneratingId === job.id}
                              className="inline-flex h-7 items-center gap-1 rounded-lg border border-[#e4e8f0] bg-white px-2.5 text-[11px] font-semibold text-[#374151] hover:bg-[#f4f6f8] disabled:cursor-not-allowed disabled:opacity-50"
                              title={isGenerating ? "生成中，不可重复抢占" : "重试"}
                            >
                              {regeneratingId === job.id ? <Loader2Icon size={12} className="animate-spin" /> : <RefreshCwIcon size={12} />}
                              重试
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* 分页 */}
          <div className="flex items-center justify-between border-t border-[#e4e8f0] px-5 py-3 text-xs text-[#8b95a6]">
            <span>共 {total} 条</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="h-7 rounded-lg border border-[#e4e8f0] bg-white px-3 font-semibold text-[#374151] hover:bg-[#f4f6f8] disabled:opacity-50"
              >
                上一页
              </button>
              <span>
                第 {page} / {totalPages} 页
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="h-7 rounded-lg border border-[#e4e8f0] bg-white px-3 font-semibold text-[#374151] hover:bg-[#f4f6f8] disabled:opacity-50"
              >
                下一页
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
