/**
 * Phase 8 Task 8：小高AI微信助手 - 每日报表后台页面。
 *
 * 五个 tab：报表任务 / 待归因线索 / 数据完整度 / 广告日数据 / 展厅价位。
 * 消费 Task 3/7 后端接口；权限以后端为准：普通读 agent，写操作需 agent + leads。
 * 前端只做能力入口展示（canWrite 控制写按钮可见），不伪造权限绕过。
 * 下载文件名取自响应头 Content-Disposition；不接触内部存储键/绝对路径/令牌。
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  DownloadIcon,
  FileSpreadsheetIcon,
  Loader2Icon,
  RefreshCwIcon,
  SaveIcon,
} from "lucide-react";
import type { AppUser } from "../../../App";
import { PERMISSIONS, hasPermission } from "../../capabilities";
import { getApiErrorCode } from "../../../api/client";
import {
  downloadDailyReport,
  fetchDailyAdMetrics,
  fetchDailyReports,
  fetchLeadAttributions,
  fetchMerchantReportProfile,
  fetchReportCompleteness,
  generateDailyReports,
  regenerateDailyReport,
  upsertDailyAdMetrics,
  upsertLeadAttributions,
  upsertMerchantReportProfile,
} from "../../../api/dailyReports";
import type {
  DailyAdMetricOut,
  DailyReportDiagnostic,
  DailyReportJobItem,
  DailyReportType,
  DailyReportVariant,
  LeadAttributionItem,
  LeadReportAttributionUpsert,
  SkippedReport,
} from "../../../api/types";
import { formatDateTimeLocal } from "../../../lib/datetime";
import { userFacingError } from "../../../lib/userFacingError";

const REPORT_TYPE_LABELS: Record<string, string> = {
  short_video_live_lead: "留资管理表",
  daily_sales_feedback: "每日销售反馈表",
  lead_trace: "线索溯源表",
  sales_unit_cost: "销售单车成本表",
};

const STATUS_META: Record<string, { label: string; tone: string }> = {
  none: { label: "待生成", tone: "text-slate-500" },
  generating: { label: "生成中", tone: "text-amber-600" },
  generated: { label: "已完成", tone: "text-emerald-600" },
  partial: { label: "部分完成", tone: "text-blue-600" },
  failed: { label: "失败", tone: "text-rose-600" },
};

// 执行包稳定诊断码（与后端 daily_report_service / daily_report_data_service 同一组）
const COMPLETENESS_LABELS: Record<string, string> = {
  lead_attribution_incomplete: "待归因线索",
  short_video_ad_metric_missing: "短视频广告指标缺失",
  live_ad_metric_missing: "直播广告指标缺失",
  showroom_price_profile_missing: "展厅价位未配置",
  budget_text_unparseable: "预算文本不可解析",
  ad_spend_allocation_unavailable: "广告消耗分摊不可用",
  daily_summary_llm_failed: "每日总结摘要失败",
  daily_summary_input_too_large: "每日总结输入过大",
  trace_source_incomplete: "溯源信息不完整",
  // 任务编排层系统级稳定码（非报表数据完整度，仅暴露 exception_type，不暴露异常正文）
  generation_failed: "生成失败",
};

const SKIP_REASON_LABELS: Record<string, string> = {
  PERMISSION_DENIED: "当前账号缺少 auto_wechat:leads 权限",
};

const TRAFFIC_TYPES = ["paid", "organic", "unknown"];
const CONTENT_TYPES = ["short_video", "live", "other", "unknown"];

type TabKey = "tasks" | "attribution" | "completeness" | "ad-metrics" | "profile";

const TABS: { key: TabKey; label: string }[] = [
  { key: "tasks", label: "报表任务" },
  { key: "attribution", label: "待归因线索" },
  { key: "completeness", label: "数据完整度" },
  { key: "ad-metrics", label: "广告日数据" },
  { key: "profile", label: "展厅价位" },
];

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function diagnosticsText(job: DailyReportJobItem): string {
  if (!job.diagnostics || job.diagnostics.length === 0) return "";
  return job.diagnostics
    .map((d) => {
      // 中文标签映射；未知码原文兜底，不静默隐藏
      const label = COMPLETENESS_LABELS[d.code] ?? d.code;
      return d.exception_type ? `${label}(${d.exception_type})×${d.count}` : `${label}×${d.count}`;
    })
    .join("，");
}

function triggerBlobDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function NoticeBanner() {
  // 两条固定事实提示（执行包 Step 8/9），不得改成"不可变快照"或"已与样例一致"
  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-[11px] leading-5 text-blue-800">
      <p>· 历史重生成按当前归因和当前跟进状态重算，不是不可变历史快照。</p>
      <p>· 字段顺序已按需求冻结，样例视觉尚未验收（不以"已与样例一致"表述）。</p>
    </div>
  );
}

function ReadOnlyHint({ canWrite }: { canWrite: boolean }) {
  if (canWrite) return null;
  return (
    <p className="text-[11px] text-[#94a3b8]">
      当前账号缺少 auto_wechat:leads 权限，本视图只读；写操作最终权限仍由后端判定。
    </p>
  );
}

export default function DailyReports({ user }: { user: AppUser }) {
  const canWrite = hasPermission(user, PERMISSIONS.agent) && hasPermission(user, PERMISSIONS.leads);
  const [tab, setTab] = useState<TabKey>("tasks");

  return (
    <section className="flex h-full flex-col overflow-auto bg-[#f3f6fa]">
      <header className="border-b border-[#e4e8f0] bg-white px-6 py-4">
        <h1 className="text-[15px] font-bold text-[#1a1f2e]">每日报表</h1>
        <p className="mt-1 text-xs text-[#8b95a6]">
          生成留资管理、每日销售反馈、销售单车成本与线索溯源四类日报；补录归因、广告指标与展厅价位；下载由后端按可信商户校验后返回。
        </p>
      </header>

      <div className="border-b border-[#e4e8f0] bg-white px-6">
        <div className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`-mb-px border-b-2 px-4 py-2.5 text-xs font-semibold transition ${
                tab === t.key
                  ? "border-[#2563eb] text-[#2563eb]"
                  : "border-transparent text-[#8b95a6] hover:text-[#1a1f2e]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 p-6">
        {tab === "tasks" ? (
          <ReportsTaskTab />
        ) : tab === "attribution" ? (
          <AttributionTab canWrite={canWrite} />
        ) : tab === "completeness" ? (
          <CompletenessTab />
        ) : tab === "ad-metrics" ? (
          <AdMetricsTab canWrite={canWrite} />
        ) : (
          <ProfileTab canWrite={canWrite} />
        )}
      </div>
    </section>
  );
}

// ===================== 报表任务 =====================

function ReportsTaskTab() {
  const [reportDay, setReportDay] = useState<string>(todayStr());
  const [checked, setChecked] = useState<Record<string, boolean>>({
    short_video_live_lead: true,
    daily_sales_feedback: true,
    sales_unit_cost: true,
    lead_trace: true,
  });
  const [traceVariant, setTraceVariant] = useState<DailyReportVariant>("created");
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [filterType, setFilterType] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
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
      const resp = await fetchDailyReports({
        page,
        page_size: pageSize,
        report_type: filterType || undefined,
        status: filterStatus || undefined,
      });
      setRecords(resp.records || []);
      setTotal(resp.total || 0);
    } catch (err) {
      setRecords([]);
      setTotal(0);
      setListError(userFacingError(err, "任务列表加载失败"));
    } finally {
      setListLoading(false);
    }
  }, [page, filterType, filterStatus]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const handleGenerate = async () => {
    if (!reportDay) {
      toast.error("请选择报表日期");
      return;
    }
    const selected: { type: DailyReportType; variant: DailyReportVariant }[] = [];
    if (checked.short_video_live_lead) selected.push({ type: "short_video_live_lead", variant: "default" });
    if (checked.daily_sales_feedback) selected.push({ type: "daily_sales_feedback", variant: "default" });
    if (checked.sales_unit_cost) selected.push({ type: "sales_unit_cost", variant: "default" });
    if (checked.lead_trace) selected.push({ type: "lead_trace", variant: traceVariant });
    if (selected.length === 0) {
      toast.error("请至少选择一类报表");
      return;
    }
    setGenerating(true);
    const allSkipped: SkippedReport[] = [];
    let okCount = 0;
    let failCount = 0;
    try {
      for (const item of selected) {
        try {
          const resp = await generateDailyReports({
            report_day: reportDay,
            report_type: item.type,
            report_variant: item.variant,
          });
          okCount += resp.jobs.length;
          failCount += resp.jobs.filter((j) => j.status === "failed").length;
          allSkipped.push(...(resp.skipped || []));
        } catch (err) {
          if (item.type === "lead_trace" && getApiErrorCode(err) === "PERMISSION_DENIED") {
            allSkipped.push({ report_type: item.type, variant: item.variant, reason: "PERMISSION_DENIED" });
          } else {
            throw err;
          }
        }
      }
      setSkipped(allSkipped);
      if (failCount > 0) {
        toast.warning(`生成完成：${okCount} 个任务，其中 ${failCount} 个失败，请查看诊断或重试`);
      } else {
        toast.success(`已生成 ${okCount} 个日报任务`);
      }
      setPage(1);
      await loadList();
    } catch (err) {
      toast.error(userFacingError(err, "日报生成失败"));
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
      if (code === "DAILY_REPORT_GENERATING") toast.warning("任务正在生成中，请稍后重试");
      else if (code === "PERMISSION_DENIED") toast.error("当前账号缺少所需权限");
      else if (code === "DAILY_REPORT_NOT_FOUND") toast.error("任务不存在或已不属于当前商户");
      else toast.error(userFacingError(err, "重试失败"));
    } finally {
      setRegeneratingId(null);
    }
  };

  const handleDownload = async (job: DailyReportJobItem) => {
    setDownloadingId(job.id);
    try {
      // 文件名取自响应头 Content-Disposition；前端不接触存储路径
      const { blob, filename } = await downloadDailyReport(job.id);
      triggerBlobDownload(blob, filename);
      toast.success("已开始下载");
    } catch (err) {
      const code = getApiErrorCode(err);
      if (code === "DAILY_REPORT_NOT_FOUND") toast.error("文件不可用或已被校验拦截，请重新生成后再下载");
      else if (code === "PERMISSION_DENIED") toast.error("当前账号缺少下载该报表的权限");
      else toast.error(userFacingError(err, "下载失败"));
    } finally {
      setDownloadingId(null);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-4">
      <NoticeBanner />

      <div className="rounded-2xl border border-[#e4e8f0] bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs font-semibold text-[#64748b]">报表日期（自然日）</label>
            <input
              type="date"
              aria-label="报表日期"
              value={reportDay}
              onChange={(e) => setReportDay(e.target.value)}
              className="h-9 w-44 rounded-xl border border-[#e4e8f0] bg-white px-3 text-sm text-[#1a1f2e] focus:outline-none focus:ring-2 focus:ring-[#2563eb]/30"
            />
          </div>
          <div className="flex flex-wrap items-center gap-4">
            {(Object.keys(REPORT_TYPE_LABELS) as (keyof typeof REPORT_TYPE_LABELS)[]).map((key) => (
              <label key={key} className="inline-flex items-center gap-1.5 text-xs text-[#1a1f2e]">
                <input
                  type="checkbox"
                  checked={!!checked[key]}
                  onChange={(e) => setChecked((c) => ({ ...c, [key]: e.target.checked }))}
                  className="h-3.5 w-3.5 rounded border-[#cbd5e1]"
                />
                {REPORT_TYPE_LABELS[key]}
              </label>
            ))}
          </div>
          {checked.lead_trace ? (
            <div className="flex items-center gap-2 text-xs text-[#1a1f2e]">
              <span className="text-[#64748b]">线索溯源口径</span>
              {(["created", "assigned"] as DailyReportVariant[]).map((v) => (
                <label key={v} className="inline-flex items-center gap-1">
                  <input
                    type="radio"
                    name="trace-variant"
                    checked={traceVariant === v}
                    onChange={() => setTraceVariant(v)}
                    className="h-3.5 w-3.5"
                  />
                  {v === "created" ? "按创建" : "按分配"}
                </label>
              ))}
            </div>
          ) : null}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:opacity-60"
          >
            {generating ? <Loader2Icon size={14} className="animate-spin" /> : <RefreshCwIcon size={14} />}
            {generating ? "生成中" : "生成所选报表"}
          </button>
        </div>

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

      <div className="rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        <div className="flex flex-wrap items-center gap-3 border-b border-[#e4e8f0] px-5 py-3">
          <span className="text-sm font-bold text-[#1a1f2e]">任务列表</span>
          <select aria-label="筛选报表类型" value={filterType} onChange={(e) => { setFilterType(e.target.value); setPage(1); }} className="h-8 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs">
            <option value="">全部类型</option>
            <option value="short_video_live_lead">留资管理表</option>
            <option value="daily_sales_feedback">每日销售反馈表</option>
            <option value="sales_unit_cost">销售单车成本表</option>
            <option value="lead_trace">线索溯源表</option>
          </select>
          <select aria-label="筛选报表状态" value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1); }} className="h-8 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs">
            <option value="">全部状态</option>
            <option value="generated">已完成</option>
            <option value="partial">部分完成</option>
            <option value="failed">失败</option>
            <option value="generating">生成中</option>
          </select>
          <button type="button" onClick={loadList} className="ml-auto inline-flex h-8 items-center gap-1 rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151] hover:bg-[#f4f6f8]">
            <RefreshCwIcon size={12} /> 刷新
          </button>
        </div>

        {listError ? <div className="px-5 py-6 text-xs text-rose-600">{listError} <button type="button" onClick={loadList} className="ml-2 font-semibold text-[#2563eb] underline">重试</button></div> : null}

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
                <tr><td colSpan={8} className="px-5 py-8 text-center text-[#8b95a6]"><Loader2Icon size={16} className="mr-2 inline animate-spin" />加载中...</td></tr>
              ) : records.length === 0 ? (
                <tr><td colSpan={8} className="px-5 py-8 text-center text-[#8b95a6]">暂无日报任务，请先生成。</td></tr>
              ) : (
                records.map((job) => {
                  const meta = STATUS_META[job.status] || { label: job.status, tone: "text-slate-500" };
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
                        <span className={`font-semibold ${meta.tone}`}>{meta.label}</span>
                        {job.is_previous_artifact ? <span className="ml-1 text-[10px] text-[#94a3b8]">（展示上次成功文件）</span> : null}
                      </td>
                      <td className="px-5 py-3 text-[#64748b]">{job.artifact_status === "available" ? (job.file_name || "可下载") : <span className="text-[#94a3b8]">未生成</span>}</td>
                      <td className="max-w-[220px] px-5 py-3 text-[#94a3b8]" title={diag}>{diag || "—"}</td>
                      <td className="px-5 py-3 text-[#94a3b8]">{job.generated_at ? formatDateTimeLocal(job.generated_at) : "—"}</td>
                      <td className="px-5 py-3">
                        <div className="flex justify-end gap-2">
                          <button type="button" onClick={() => handleDownload(job)} disabled={!job.download_available || downloadingId === job.id} title={job.download_available ? "下载" : "文件不可用"} className="inline-flex h-7 items-center gap-1 rounded-lg border border-[#e4e8f0] bg-white px-2.5 text-[11px] font-semibold text-[#374151] hover:bg-[#f4f6f8] disabled:cursor-not-allowed disabled:opacity-50">
                            {downloadingId === job.id ? <Loader2Icon size={12} className="animate-spin" /> : <DownloadIcon size={12} />}下载
                          </button>
                          <button type="button" onClick={() => handleRegenerate(job)} disabled={isGenerating || regeneratingId === job.id} title={isGenerating ? "生成中，不可重复抢占" : "重试"} className="inline-flex h-7 items-center gap-1 rounded-lg border border-[#e4e8f0] bg-white px-2.5 text-[11px] font-semibold text-[#374151] hover:bg-[#f4f6f8] disabled:cursor-not-allowed disabled:opacity-50">
                            {regeneratingId === job.id ? <Loader2Icon size={12} className="animate-spin" /> : <RefreshCwIcon size={12} />}重试
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

        <div className="flex items-center justify-between border-t border-[#e4e8f0] px-5 py-3 text-xs text-[#8b95a6]">
          <span>共 {total} 条</span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="h-7 rounded-lg border border-[#e4e8f0] bg-white px-3 font-semibold text-[#374151] hover:bg-[#f4f6f8] disabled:opacity-50">上一页</button>
            <span>第 {page} / {totalPages} 页</span>
            <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="h-7 rounded-lg border border-[#e4e8f0] bg-white px-3 font-semibold text-[#374151] hover:bg-[#f4f6f8] disabled:opacity-50">下一页</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ===================== 待归因线索 =====================

function AttributionTab({ canWrite }: { canWrite: boolean }) {
  const [reportDay, setReportDay] = useState<string>(todayStr());
  const [missingOnly, setMissingOnly] = useState(true);
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [records, setRecords] = useState<LeadAttributionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<number, LeadReportAttributionUpsert>>({});
  const [savingId, setSavingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchLeadAttributions({ report_day: reportDay, missing_only: missingOnly, page, page_size: pageSize });
      setRecords(resp.records || []);
      setTotal(resp.total || 0);
      setDrafts({});
    } catch (err) {
      setRecords([]);
      setTotal(0);
      setError(userFacingError(err, "待归因线索加载失败"));
    } finally {
      setLoading(false);
    }
  }, [reportDay, missingOnly, page]);

  useEffect(() => {
    void load();
  }, [load]);

  const getDraft = (item: LeadAttributionItem): LeadReportAttributionUpsert => {
    if (drafts[item.lead_id]) return drafts[item.lead_id];
    return {
      lead_id: item.lead_id,
      traffic_type: item.attribution?.traffic_type || "unknown",
      content_type: item.attribution?.content_type || "unknown",
      ad_id: item.attribution?.ad_id || "",
      material_id: item.attribution?.material_id || "",
      trace_url: item.attribution?.trace_url || "",
    };
  };

  const updateDraft = (leadId: number, patch: Partial<LeadReportAttributionUpsert>) => {
    setDrafts((d) => ({ ...d, [leadId]: { ...getDraft({ lead_id: leadId } as LeadAttributionItem), ...d[leadId], ...patch } }));
  };

  const handleSave = async (leadId: number) => {
    const draft = drafts[leadId];
    if (!draft) {
      toast.info("该行未改动");
      return;
    }
    setSavingId(leadId);
    try {
      await upsertLeadAttributions([draft]);
      toast.success("归因已保存");
      await load();
    } catch (err) {
      const code = getApiErrorCode(err);
      if (code === "LEAD_NOT_FOUND") toast.error("线索不属于当前商户");
      else if (code === "PERMISSION_DENIED") toast.error("缺少写权限");
      else toast.error(userFacingError(err, "保存失败"));
    } finally {
      setSavingId(null);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-3">
      <ReadOnlyHint canWrite={canWrite} />
      <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-[#e4e8f0] bg-white p-4">
        <div>
          <label className="mb-1 block text-xs font-semibold text-[#64748b]">报表日期</label>
          <input type="date" aria-label="报表日期" value={reportDay} onChange={(e) => { setReportDay(e.target.value); setPage(1); }} className="h-9 w-44 rounded-xl border border-[#e4e8f0] bg-white px-3 text-sm" />
        </div>
        <label className="inline-flex items-center gap-1.5 text-xs text-[#1a1f2e]">
          <input type="checkbox" checked={missingOnly} onChange={(e) => { setMissingOnly(e.target.checked); setPage(1); }} className="h-3.5 w-3.5" />
          仅看缺归因
        </label>
        <button type="button" onClick={load} className="inline-flex h-9 items-center gap-1 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold hover:bg-[#f4f6f8]"><RefreshCwIcon size={12} />查询</button>
      </div>

      {error ? <div className="text-xs text-rose-600">{error} <button type="button" onClick={load} className="ml-2 font-semibold text-[#2563eb] underline">重试</button></div> : null}

      <div className="overflow-x-auto rounded-2xl border border-[#e4e8f0] bg-white">
        <table className="w-full min-w-[960px] text-left text-xs">
          <thead className="bg-[#f8fafc] text-[11px] uppercase text-[#8b95a6]">
            <tr>
              <th className="px-4 py-3 font-semibold">线索</th>
              <th className="px-4 py-3 font-semibold">流量类型</th>
              <th className="px-4 py-3 font-semibold">内容类型</th>
              <th className="px-4 py-3 font-semibold">广告编号</th>
              <th className="px-4 py-3 font-semibold">素材编号</th>
              <th className="px-4 py-3 font-semibold">溯源链接</th>
              <th className="px-4 py-3 text-right font-semibold">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#eef1f6]">
            {loading ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-[#8b95a6]"><Loader2Icon size={16} className="mr-2 inline animate-spin" />加载中...</td></tr>
            ) : records.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-[#8b95a6]">暂无符合条件的线索。</td></tr>
            ) : (
              records.map((item) => {
                const d = getDraft(item);
                return (
                  <tr key={item.lead_id} className="hover:bg-[#f8fafc]">
                    <td className="px-4 py-2.5">
                      <div className="font-semibold text-[#1a1f2e]">#{item.lead_id}</div>
                      <div className="text-[10px] text-[#94a3b8]">{item.customer_name || "未知客户"}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <select aria-label="流量类型" disabled={!canWrite} value={d.traffic_type} onChange={(e) => updateDraft(item.lead_id, { traffic_type: e.target.value })} className="h-8 w-24 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs disabled:bg-[#f8fafc]">
                        {TRAFFIC_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </td>
                    <td className="px-4 py-2.5">
                      <select aria-label="内容类型" disabled={!canWrite} value={d.content_type} onChange={(e) => updateDraft(item.lead_id, { content_type: e.target.value })} className="h-8 w-28 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs disabled:bg-[#f8fafc]">
                        {CONTENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </td>
                    <td className="px-4 py-2.5">
                      <input aria-label="广告编号" disabled={!canWrite} value={d.ad_id || ""} onChange={(e) => updateDraft(item.lead_id, { ad_id: e.target.value })} className="h-8 w-28 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs disabled:bg-[#f8fafc]" />
                    </td>
                    <td className="px-4 py-2.5">
                      <input aria-label="素材编号" disabled={!canWrite} value={d.material_id || ""} onChange={(e) => updateDraft(item.lead_id, { material_id: e.target.value })} className="h-8 w-28 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs disabled:bg-[#f8fafc]" />
                    </td>
                    <td className="px-4 py-2.5">
                      <input aria-label="溯源链接" disabled={!canWrite} value={d.trace_url || ""} onChange={(e) => updateDraft(item.lead_id, { trace_url: e.target.value })} className="h-8 w-56 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs disabled:bg-[#f8fafc]" />
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button type="button" onClick={() => handleSave(item.lead_id)} disabled={!canWrite || savingId === item.lead_id} className="inline-flex h-7 items-center gap-1 rounded-lg bg-[#2563eb] px-2.5 text-[11px] font-semibold text-white disabled:opacity-50">
                        {savingId === item.lead_id ? <Loader2Icon size={12} className="animate-spin" /> : <SaveIcon size={12} />}保存
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
        <div className="flex items-center justify-between border-t border-[#e4e8f0] px-4 py-3 text-xs text-[#8b95a6]">
          <span>共 {total} 条（不展示原始请求体）</span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="h-7 rounded-lg border border-[#e4e8f0] bg-white px-3 font-semibold text-[#374151] disabled:opacity-50">上一页</button>
            <span>第 {page} / {totalPages} 页</span>
            <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="h-7 rounded-lg border border-[#e4e8f0] bg-white px-3 font-semibold text-[#374151] disabled:opacity-50">下一页</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ===================== 数据完整度 =====================

function CompletenessTab() {
  const [reportDay, setReportDay] = useState<string>(todayStr());
  const [diagnostics, setDiagnostics] = useState<DailyReportDiagnostic[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchReportCompleteness(reportDay);
      setDiagnostics(resp.diagnostics || []);
    } catch (err) {
      setDiagnostics([]);
      setError(userFacingError(err, "完整度加载失败"));
    } finally {
      setLoading(false);
    }
  }, [reportDay]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-3">
      <div className="flex items-end gap-3 rounded-2xl border border-[#e4e8f0] bg-white p-4">
        <div>
          <label className="mb-1 block text-xs font-semibold text-[#64748b]">报表日期</label>
          <input type="date" aria-label="报表日期" value={reportDay} onChange={(e) => setReportDay(e.target.value)} className="h-9 w-44 rounded-xl border border-[#e4e8f0] bg-white px-3 text-sm" />
        </div>
        <button type="button" onClick={load} className="inline-flex h-9 items-center gap-1 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold hover:bg-[#f4f6f8]"><RefreshCwIcon size={12} />查询</button>
      </div>
      {error ? <div className="text-xs text-rose-600">{error} <button type="button" onClick={load} className="ml-2 font-semibold text-[#2563eb] underline">重试</button></div> : null}
      <div className="rounded-2xl border border-[#e4e8f0] bg-white p-5">
        {loading ? (
          <div className="text-xs text-[#8b95a6]"><Loader2Icon size={16} className="mr-2 inline animate-spin" />加载中...</div>
        ) : diagnostics.length === 0 ? (
          <div className="text-xs text-emerald-600">当日数据完整，无缺失项。</div>
        ) : (
          <ul className="space-y-2">
            {diagnostics.map((d, idx) => (
              <li key={`${d.code}-${idx}`} className="flex items-center justify-between rounded-lg bg-[#f8fafc] px-4 py-2.5 text-xs">
                <span className="font-semibold text-[#1a1f2e]">{COMPLETENESS_LABELS[d.code] || d.code}</span>
                <span className="text-rose-600">缺 {d.count} 条</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ===================== 广告日数据 =====================

function AdMetricsTab({ canWrite }: { canWrite: boolean }) {
  const [metricDay, setMetricDay] = useState<string>(todayStr());
  const [shortVideo, setShortVideo] = useState({ spend: "", msg: "" });
  const [live, setLive] = useState({ spend: "", msg: "" });
  const [existing, setExisting] = useState<DailyAdMetricOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchDailyAdMetrics(metricDay);
      const recs = resp.records || [];
      setExisting(recs);
      const sv = recs.find((r) => r.content_type === "short_video");
      const lv = recs.find((r) => r.content_type === "live");
      setShortVideo({ spend: sv?.spend_amount || "", msg: sv ? String(sv.private_message_count) : "" });
      setLive({ spend: lv?.spend_amount || "", msg: lv ? String(lv.private_message_count) : "" });
    } catch (err) {
      setExisting([]);
      setError(userFacingError(err, "广告日数据加载失败"));
    } finally {
      setLoading(false);
    }
  }, [metricDay]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    const items = [];
    if (shortVideo.spend || shortVideo.msg) {
      items.push({ metric_day: metricDay, content_type: "short_video" as const, spend_amount: shortVideo.spend || "0", private_message_count: Number(shortVideo.msg || 0) });
    }
    if (live.spend || live.msg) {
      items.push({ metric_day: metricDay, content_type: "live" as const, spend_amount: live.spend || "0", private_message_count: Number(live.msg || 0) });
    }
    if (items.length === 0) {
      toast.info("请至少填写一类广告数据");
      return;
    }
    setSaving(true);
    try {
      await upsertDailyAdMetrics(items);
      toast.success("广告日数据已保存");
      await load();
    } catch (err) {
      const code = getApiErrorCode(err);
      if (code === "PERMISSION_DENIED") toast.error("缺少写权限");
      else toast.error(userFacingError(err, "保存失败"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <ReadOnlyHint canWrite={canWrite} />
      <div className="flex items-end gap-3 rounded-2xl border border-[#e4e8f0] bg-white p-4">
        <div>
          <label className="mb-1 block text-xs font-semibold text-[#64748b]">指标日期</label>
          <input type="date" aria-label="指标日期" value={metricDay} onChange={(e) => setMetricDay(e.target.value)} className="h-9 w-44 rounded-xl border border-[#e4e8f0] bg-white px-3 text-sm" />
        </div>
        <button type="button" onClick={load} className="inline-flex h-9 items-center gap-1 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold hover:bg-[#f4f6f8]"><RefreshCwIcon size={12} />查询</button>
        <span className="text-[11px] text-[#94a3b8]">仅录入日期、消耗与私信量，不提供广告编号明细输入。</span>
      </div>
      {error ? <div className="text-xs text-rose-600">{error} <button type="button" onClick={load} className="ml-2 font-semibold text-[#2563eb] underline">重试</button></div> : null}
      <div className="rounded-2xl border border-[#e4e8f0] bg-white p-5">
        {loading ? <div className="text-xs text-[#8b95a6]"><Loader2Icon size={16} className="mr-2 inline animate-spin" />加载中...</div> : (
          <div className="space-y-4">
            <AdMetricRow label="短视频" value={shortVideo} onChange={setShortVideo} disabled={!canWrite} />
            <AdMetricRow label="直播" value={live} onChange={setLive} disabled={!canWrite} />
            <div className="flex justify-end">
              <button type="button" onClick={handleSave} disabled={!canWrite || saving} className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white disabled:opacity-50">
                {saving ? <Loader2Icon size={14} className="animate-spin" /> : <SaveIcon size={14} />}保存
              </button>
            </div>
            {existing.length > 0 ? (
              <p className="text-[11px] text-[#94a3b8]">已记录 {existing.length} 条（来源：系统记录）</p>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

function AdMetricRow({ label, value, onChange, disabled }: { label: string; value: { spend: string; msg: string }; onChange: (v: { spend: string; msg: string }) => void; disabled: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="w-16 text-xs font-semibold text-[#1a1f2e]">{label}</span>
      <label className="inline-flex items-center gap-1.5 text-xs text-[#64748b]">
        消耗（元）
        <input type="number" step="0.01" min="0" disabled={disabled} value={value.spend} onChange={(e) => onChange({ ...value, spend: e.target.value })} className="h-8 w-32 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs disabled:bg-[#f8fafc]" />
      </label>
      <label className="inline-flex items-center gap-1.5 text-xs text-[#64748b]">
        私信量
        <input type="number" min="0" disabled={disabled} value={value.msg} onChange={(e) => onChange({ ...value, msg: e.target.value })} className="h-8 w-24 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs disabled:bg-[#f8fafc]" />
      </label>
    </div>
  );
}

// ===================== 展厅价位 =====================

function ProfileTab({ canWrite }: { canWrite: boolean }) {
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");
  const [updated, setUpdated] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchMerchantReportProfile();
      setMin(resp.showroom_price_min_yuan || "");
      setMax(resp.showroom_price_max_yuan || "");
      setUpdated(resp.updated_at || null);
    } catch (err) {
      setError(userFacingError(err, "展厅价位加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    // 两个价位必须同时存在或同时为空
    if ((min.trim() === "") !== (max.trim() === "")) {
      toast.error("价位必须同时填写或同时清空");
      return;
    }
    const minNum = Number(min);
    const maxNum = Number(max);
    if (min && max && minNum > maxNum) {
      toast.error("最低价不能大于最高价");
      return;
    }
    setSaving(true);
    try {
      await upsertMerchantReportProfile({
        showroom_price_min_yuan: min || null,
        showroom_price_max_yuan: max || null,
      });
      toast.success("展厅价位已保存");
      await load();
    } catch (err) {
      const code = getApiErrorCode(err);
      if (code === "PERMISSION_DENIED") toast.error("缺少写权限");
      else toast.error(userFacingError(err, "保存失败"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <ReadOnlyHint canWrite={canWrite} />
      {error ? <div className="text-xs text-rose-600">{error} <button type="button" onClick={load} className="ml-2 font-semibold text-[#2563eb] underline">重试</button></div> : null}
      <div className="rounded-2xl border border-[#e4e8f0] bg-white p-5">
        {loading ? <div className="text-xs text-[#8b95a6]"><Loader2Icon size={16} className="mr-2 inline animate-spin" />加载中...</div> : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-4">
              <label className="inline-flex items-center gap-1.5 text-xs text-[#64748b]">
                最低价（元）
                <input type="number" step="0.01" min="0" disabled={!canWrite} value={min} onChange={(e) => setMin(e.target.value)} className="h-9 w-40 rounded-xl border border-[#e4e8f0] bg-white px-3 text-sm disabled:bg-[#f8fafc]" />
              </label>
              <label className="inline-flex items-center gap-1.5 text-xs text-[#64748b]">
                最高价（元）
                <input type="number" step="0.01" min="0" disabled={!canWrite} value={max} onChange={(e) => setMax(e.target.value)} className="h-9 w-40 rounded-xl border border-[#e4e8f0] bg-white px-3 text-sm disabled:bg-[#f8fafc]" />
              </label>
              <button type="button" onClick={handleSave} disabled={!canWrite || saving} className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white disabled:opacity-50">
                {saving ? <Loader2Icon size={14} className="animate-spin" /> : <SaveIcon size={14} />}保存
              </button>
            </div>
            <p className="text-[11px] text-[#94a3b8]">两个价位须同时填写或同时清空，且最低价 ≤ 最高价。{updated ? `最近更新：${formatDateTimeLocal(updated)}` : ""}</p>
          </div>
        )}
      </div>
    </div>
  );
}
