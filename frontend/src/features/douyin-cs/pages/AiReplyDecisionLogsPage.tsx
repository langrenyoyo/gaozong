import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircleIcon,
  BotIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  EyeIcon,
  RefreshCwIcon,
  SearchIcon,
  ShieldCheckIcon,
  XIcon,
} from "lucide-react";

import {
  getAiReplyDecisionLogDetail,
  getAiReplyDecisionLogs,
  patchAiReplyDecisionLogEffectiveness,
  type AiReplyDecisionLogDetail,
  type AiReplyDecisionLogListItem,
  type AiReplyDecisionSource,
} from "../api";
import { formatDateTimeLocal } from "../../../lib/datetime";

const PAGE_SIZE = 20;

const INTENT_LABELS: Record<string, string> = {
  price: "询价",
  inventory: "库存",
  test_drive: "试驾",
  contact: "留资/联系",
  complaint: "投诉",
  unknown: "未知",
};

const LEAD_LEVEL_LABELS: Record<string, string> = {
  high: "高意向",
  medium: "中意向",
  low: "低意向",
  unknown: "未知",
};

const RISK_FLAG_LABELS: Record<string, string> = {
  price_commitment: "价格承诺风险",
  no_rag_source: "知识库无命中",
  llm_json_parse_failed: "结构化解析失败",
  llm_requested_auto_send: "模型请求自动发送",
  proxy_forced_auto_send_false: "代理已强制关闭自动发送",
  prompt_injection: "提示词注入风险",
};

function resolveErrorMessage(error: unknown): string {
  if (error && typeof error === "object") {
    const anyError = error as {
      response?: { data?: { message?: string; detail?: string | { message?: string; safe_message?: string } } };
      message?: string;
    };
    const detail = anyError.response?.data?.detail;
    if (detail && typeof detail === "object") return detail.safe_message || detail.message || "请求失败";
    if (typeof detail === "string") return detail;
    return anyError.response?.data?.message || anyError.message || "请求失败";
  }
  return error instanceof Error ? error.message : "请求失败";
}

function safeArray<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function labelFromMap(value: string | null | undefined, labels: Record<string, string>): string {
  if (!value) return "未知";
  return labels[value] || value;
}

function formatConfidence(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "未知";
  const normalized = value <= 1 ? value * 100 : value;
  return `${Math.max(0, Math.min(100, normalized)).toFixed(0)}%`;
}

function sourceScore(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return value <= 1 ? value.toFixed(3) : value.toFixed(1);
}

// Phase 4：发送状态与有效性展示 helper
function sendStatusLabel(status?: string | null): string {
  if (status === "sent") return "已发送";
  if (status === "failed") return "发送失败";
  if (status === "pending") return "待发送";
  return status || "未知";
}

function sendStatusTone(status?: string | null): "slate" | "amber" | "red" | "emerald" {
  if (status === "sent") return "emerald";
  if (status === "failed") return "red";
  if (status === "pending") return "amber";
  return "slate";
}

function effectivenessLabel(value?: boolean | null): string {
  if (value === true) return "有效";
  if (value === false) return "无效";
  return "未标记";
}

// 实发时间优先级：sent_at > send_created_at > 决策 created_at
function displaySendTime(item: { sent_at?: string | null; send_created_at?: string | null; created_at?: string | null }) {
  return item.sent_at || item.send_created_at || item.created_at || null;
}

function Chip({
  children,
  tone = "slate",
}: {
  children: React.ReactNode;
  tone?: "slate" | "blue" | "amber" | "red" | "emerald";
}) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    blue: "bg-blue-100 text-blue-700",
    amber: "bg-amber-100 text-amber-700",
    red: "bg-red-100 text-red-700",
    emerald: "bg-emerald-100 text-emerald-700",
  };
  return <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${tones[tone]}`}>{children}</span>;
}

function SourceList({ sources }: { sources: AiReplyDecisionSource[] }) {
  if (sources.length === 0) {
    return <div className="rounded-xl border border-dashed border-[#dbe3ef] px-3 py-4 text-xs text-[#8b95a6]">暂无知识来源</div>;
  }

  return (
    <div className="space-y-2">
      {sources.map((source, index) => (
        <div key={`${source.chunk_id || "chunk"}-${index}`} className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 py-2 text-xs">
          <div className="font-semibold text-[#1a1f2e]">{source.title || "未命名知识片段"}</div>
          <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-[#64748b]">
            <span>chunk_id：{source.chunk_id ?? "-"}</span>
            <span>document_id：{source.document_id ?? "-"}</span>
            <span>score：{sourceScore(source.score)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function DetailModal({
  detail,
  loading,
  error,
  onClose,
  onMarkEffectiveness,
}: {
  detail: AiReplyDecisionLogDetail | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onMarkEffectiveness: (id: number, isEffective: boolean) => void;
}) {
  const riskFlags = safeArray(detail?.risk_flags);
  const tags = safeArray(detail?.tags);
  const ragSources = safeArray(detail?.rag_sources);
  const sourceChunks = safeArray(detail?.source_chunks);
  const allowedCategoryKeys = safeArray(detail?.allowed_category_keys);

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="flex max-h-[88vh] w-full max-w-[820px] flex-col overflow-hidden rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">AI实发记录详情</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">展示 AI 自动回复和 AI 辅助发送的最终实发内容</p>
          </div>
          <button
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]"
            aria-label="关闭详情"
          >
            <XIcon size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          {loading ? (
            <div className="grid place-items-center py-16 text-sm text-[#8b95a6]">详情加载中...</div>
          ) : error ? (
            <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-600">
              <AlertCircleIcon size={14} />
              {error}
            </div>
          ) : detail ? (
            <div className="space-y-4">
              <div className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-4 py-3">
                <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-[#1a1f2e]">
                  <ShieldCheckIcon size={15} />
                  <span>内容来自发送流水，已包含发送前统一处理结果</span>
                  <Chip tone={sendStatusTone(detail.send_status)}>{sendStatusLabel(detail.send_status)}</Chip>
                  {detail.is_effective === true || detail.is_effective === false ? (
                    <Chip tone={detail.is_effective ? "emerald" : "red"}>{effectivenessLabel(detail.is_effective)}</Chip>
                  ) : null}
                </div>
                {detail.effectiveness_reason ? (
                  <div className="mt-2 text-xs text-[#64748b]">标记原因：{detail.effectiveness_reason}</div>
                ) : null}
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <section className="rounded-xl border border-[#e4e8f0] bg-white p-4">
                  <h3 className="text-xs font-bold text-[#1a1f2e]">客户最新消息</h3>
                  <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-[#475467]">{detail.latest_message || "-"}</p>
                </section>
                <section className="rounded-xl border border-[#e4e8f0] bg-white p-4">
                  <h3 className="text-xs font-bold text-[#1a1f2e]">AI实发内容</h3>
                  <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-[#475467]">
                    {detail.sent_content || "-"}
                  </p>
                  {detail.reply_text ? (
                    <div className="mt-3 border-t border-[#f0f2f7] pt-2">
                      <div className="text-[10px] font-semibold text-[#8b95a6]">模型原始回复</div>
                      <div className="mt-1 whitespace-pre-wrap text-[11px] leading-5 text-[#8b95a6]">{detail.reply_text}</div>
                    </div>
                  ) : null}
                </section>
              </div>

              <section className="rounded-xl border border-[#e4e8f0] bg-white p-4">
                <h3 className="text-xs font-bold text-[#1a1f2e]">决策摘要</h3>
                <div className="mt-3 grid gap-3 text-xs md:grid-cols-4">
                  <div>
                    <div className="text-[#8b95a6]">客户意图</div>
                    <div className="mt-1 font-semibold text-[#1a1f2e]">{labelFromMap(detail.intent, INTENT_LABELS)}</div>
                  </div>
                  <div>
                    <div className="text-[#8b95a6]">意向等级</div>
                    <div className="mt-1 font-semibold text-[#1a1f2e]">{labelFromMap(detail.lead_level, LEAD_LEVEL_LABELS)}</div>
                  </div>
                  <div>
                    <div className="text-[#8b95a6]">置信度</div>
                    <div className="mt-1 font-semibold text-[#1a1f2e]">{formatConfidence(detail.confidence)}</div>
                  </div>
                  <div>
                    <div className="text-[#8b95a6]">人工确认</div>
                    <div className="mt-1 font-semibold text-[#1a1f2e]">{detail.manual_required ? "需要" : "不需要"}</div>
                  </div>
                </div>
                {detail.manual_required_reason ? (
                  <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    {detail.manual_required_reason}
                  </div>
                ) : null}
              </section>

              <section className="rounded-xl border border-[#e4e8f0] bg-white p-4">
                <h3 className="text-xs font-bold text-[#1a1f2e]">标签与风险</h3>
                <div className="mt-3 space-y-3">
                  <div className="flex flex-wrap gap-1.5">
                    {tags.length > 0 ? tags.map((tag) => <Chip key={tag} tone="blue">{tag}</Chip>) : <span className="text-xs text-[#8b95a6]">暂无标签</span>}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {riskFlags.length > 0 ? (
                      riskFlags.map((flag) => <Chip key={flag} tone="red">{RISK_FLAG_LABELS[flag] || flag}</Chip>)
                    ) : (
                      <Chip tone="emerald">无风险标记</Chip>
                    )}
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-[#e4e8f0] bg-white p-4">
                <h3 className="text-xs font-bold text-[#1a1f2e]">知识来源</h3>
                <div className="mt-3">
                  <SourceList sources={ragSources.length > 0 ? ragSources : sourceChunks} />
                </div>
              </section>

              <section className="rounded-xl border border-[#e4e8f0] bg-white p-4">
                <h3 className="text-xs font-bold text-[#1a1f2e]">调试信息</h3>
                <div className="mt-3 grid gap-2 text-xs text-[#475467] md:grid-cols-2">
                  <div>RAG：{detail.rag_used ? "已使用" : "未使用"}</div>
                  <div>LLM：{detail.llm_used ? "已使用" : "未使用"}</div>
                  <div>模型：{detail.model || "-"}</div>
                  <div>发送来源：{detail.send_source || "-"}</div>
                  <div>决策版本：{detail.decision_version || "-"}</div>
                  <div>实发时间：{displaySendTime(detail) ? formatDateTimeLocal(displaySendTime(detail)) : "-"}</div>
                  <div>决策时间：{formatDateTimeLocal(detail.created_at)}</div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {allowedCategoryKeys.length > 0 ? (
                    allowedCategoryKeys.map((key) => <Chip key={key}>{key}</Chip>)
                  ) : (
                    <span className="text-xs text-[#8b95a6]">暂无分类权限记录</span>
                  )}
                </div>
              </section>
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          {detail ? (
            <>
              <button
                onClick={() => void onMarkEffectiveness(detail.id, true)}
                className="h-9 rounded-xl bg-emerald-600 px-4 text-xs font-semibold text-white hover:bg-emerald-700"
              >
                标记有效
              </button>
              <button
                onClick={() => void onMarkEffectiveness(detail.id, false)}
                className="h-9 rounded-xl bg-red-600 px-4 text-xs font-semibold text-white hover:bg-red-700"
              >
                标记无效
              </button>
            </>
          ) : null}
          <button
            onClick={onClose}
            className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151] hover:bg-[#f8fafc]"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AiReplyDecisionLogsPage() {
  const [items, setItems] = useState<AiReplyDecisionLogListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");
  const [manualRequired, setManualRequired] = useState("all");
  const [intent, setIntent] = useState("all");
  const [leadLevel, setLeadLevel] = useState("all");
  const [ragUsed, setRagUsed] = useState("all");
  const [llmUsed, setLlmUsed] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AiReplyDecisionLogDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const loadLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAiReplyDecisionLogs({
        page,
        page_size: PAGE_SIZE,
        keyword,
        manual_required: manualRequired === "all" ? null : manualRequired === "true",
        intent: intent === "all" ? undefined : intent,
        lead_level: leadLevel === "all" ? undefined : leadLevel,
        rag_used: ragUsed === "all" ? null : ragUsed === "true",
        llm_used: llmUsed === "all" ? null : llmUsed === "true",
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
      setPage(data.page || page);
    } catch (err) {
      setItems([]);
      setTotal(0);
      setError(resolveErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, intent, keyword, leadLevel, llmUsed, manualRequired, page, ragUsed]);

  useEffect(() => {
    void loadLogs();
  }, [loadLogs]);

  useEffect(() => {
    if (detailId === null) return;
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    getAiReplyDecisionLogDetail(detailId)
      .then(setDetail)
      .catch((err) => setDetailError(resolveErrorMessage(err)))
      .finally(() => setDetailLoading(false));
  }, [detailId]);

  // 超管人工标记 AI 实发回复有效性
  const markEffectiveness = async (id: number, isEffective: boolean) => {
    const reason = window.prompt(isEffective ? "请输入标记为有效的原因" : "请输入标记为无效的原因");
    if (reason === null) return;
    const text = reason.trim();
    if (!text) {
      setDetailError("请填写标记原因");
      return;
    }
    setDetailLoading(true);
    setDetailError(null);
    try {
      const updated = await patchAiReplyDecisionLogEffectiveness(id, {
        is_effective: isEffective,
        effectiveness_reason: text,
      });
      setDetail(updated);
      await loadLogs();
    } catch (err) {
      setDetailError(resolveErrorMessage(err));
    } finally {
      setDetailLoading(false);
    }
  };

  const hasFilters = useMemo(
    () =>
      Boolean(keyword.trim()) ||
      manualRequired !== "all" ||
      intent !== "all" ||
      leadLevel !== "all" ||
      ragUsed !== "all" ||
      llmUsed !== "all" ||
      Boolean(dateFrom) ||
      Boolean(dateTo),
    [dateFrom, dateTo, intent, keyword, leadLevel, llmUsed, manualRequired, ragUsed],
  );

  const resetFilters = () => {
    setKeyword("");
    setManualRequired("all");
    setIntent("all");
    setLeadLevel("all");
    setRagUsed("all");
    setLlmUsed("all");
    setDateFrom("");
    setDateTo("");
    setPage(1);
  };

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <BotIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">AI实发记录</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">
              展示 AI 自动回复和 AI 辅助发送的最终实发内容，支持超管标记回复有效性
            </p>
          </div>
        </div>
        <button
          onClick={() => void loadLogs()}
          disabled={loading}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#475467] disabled:opacity-60"
        >
          <RefreshCwIcon size={14} className={loading ? "animate-spin" : ""} />
          刷新
        </button>
      </header>

      <div className="border-b border-[#dbe3ef] bg-[#f8fafc] px-5 py-3 text-xs font-semibold text-[#475467]">
        内容来自发送流水，已包含发送前统一处理结果。
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[#e4e8f0] bg-white px-5 py-3">
        <label className="relative w-[260px] shrink-0">
          <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
          <input
            value={keyword}
            onChange={(event) => {
              setKeyword(event.target.value);
              setPage(1);
            }}
            placeholder="搜索客户消息或实发内容"
            className="h-9 w-full rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          />
        </label>

        <select value={manualRequired} onChange={(event) => { setManualRequired(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none">
          <option value="all">全部人工状态</option>
          <option value="true">需要人工确认</option>
          <option value="false">不需要人工确认</option>
        </select>
        <select value={intent} onChange={(event) => { setIntent(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none">
          <option value="all">全部意图</option>
          {Object.entries(INTENT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select value={leadLevel} onChange={(event) => { setLeadLevel(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none">
          <option value="all">全部意向</option>
          {Object.entries(LEAD_LEVEL_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select value={ragUsed} onChange={(event) => { setRagUsed(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none">
          <option value="all">RAG全部</option>
          <option value="true">RAG已使用</option>
          <option value="false">RAG未使用</option>
        </select>
        <select value={llmUsed} onChange={(event) => { setLlmUsed(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none">
          <option value="all">LLM全部</option>
          <option value="true">LLM已使用</option>
          <option value="false">LLM未使用</option>
        </select>
        <input type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none" />
        <input type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none" />
        {hasFilters ? (
          <button onClick={resetFilters} className="h-9 rounded-xl px-3 text-xs font-semibold text-[#2563eb] hover:bg-[#eff6ff]">
            重置
          </button>
        ) : null}
      </div>

      <main className="min-h-0 flex-1 overflow-auto bg-white">
        {error ? (
          <div className="m-5 flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-600">
            <AlertCircleIcon size={14} />
            {error}
          </div>
        ) : loading && items.length === 0 ? (
          <div className="grid h-full place-items-center text-sm text-[#8b95a6]">加载中...</div>
        ) : items.length === 0 ? (
          <div className="grid h-full place-items-center text-center">
            <div>
              <BotIcon size={30} className="mx-auto text-[#cbd5e1]" />
              <p className="mt-2 text-xs text-[#8b95a6]">暂无 AI 实发记录</p>
            </div>
          </div>
        ) : (
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-[#f8fafc] text-[#64748b]">
              <tr>
                <th className="w-[18%] px-4 py-3 font-semibold">客户消息</th>
                <th className="w-[22%] px-4 py-3 font-semibold">AI实发内容</th>
                <th className="w-[10%] px-4 py-3 font-semibold">意图</th>
                <th className="w-[10%] px-4 py-3 font-semibold">意向</th>
                <th className="w-[10%] px-4 py-3 font-semibold">人工确认</th>
                <th className="w-[12%] px-4 py-3 font-semibold">风险/标签</th>
                <th className="w-[10%] px-4 py-3 font-semibold">状态</th>
                <th className="w-[8%] px-4 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const riskFlags = safeArray(item.risk_flags);
                const tags = safeArray(item.tags);
                return (
                  <tr key={item.id} className="border-t border-[#f0f2f7] hover:bg-[#f8fafc]">
                    <td className="px-4 py-3">
                      <div className="line-clamp-2 text-[#374151]" title={item.latest_message_summary || undefined}>
                        {item.latest_message_summary || "-"}
                      </div>
                      <div className="mt-1 text-[10px] text-[#8b95a6]">{displaySendTime(item) ? formatDateTimeLocal(displaySendTime(item)) : "-"}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="line-clamp-2 text-[#374151]" title={item.sent_content_summary || undefined}>
                        {item.sent_content_summary || "-"}
                      </div>
                      <div className="mt-1 text-[10px] text-[#8b95a6]">{item.agent_name || item.agent_id || "-"}</div>
                    </td>
                    <td className="px-4 py-3 text-[#374151]">{labelFromMap(item.intent, INTENT_LABELS)}</td>
                    <td className="px-4 py-3 text-[#374151]">{labelFromMap(item.lead_level, LEAD_LEVEL_LABELS)}</td>
                    <td className="px-4 py-3">
                      <Chip tone={item.manual_required ? "amber" : "emerald"}>{item.manual_required ? "需要" : "不需要"}</Chip>
                      {item.manual_required_reason ? (
                        <div className="mt-1 line-clamp-1 text-[10px] text-[#8b95a6]" title={item.manual_required_reason}>
                          {item.manual_required_reason}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {riskFlags.slice(0, 2).map((flag) => <Chip key={flag} tone="red">{RISK_FLAG_LABELS[flag] || flag}</Chip>)}
                        {riskFlags.length === 0 && tags.slice(0, 2).map((tag) => <Chip key={tag} tone="blue">{tag}</Chip>)}
                        {riskFlags.length === 0 && tags.length === 0 ? <span className="text-[#8b95a6]">-</span> : null}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="space-y-1">
                        <Chip tone={sendStatusTone(item.send_status)}>{sendStatusLabel(item.send_status)}</Chip>
                        <div className="text-[10px] text-[#8b95a6]">
                          模型 {item.model || "-"} / {effectivenessLabel(item.is_effective)}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => setDetailId(item.id)}
                        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#e4e8f0] bg-white px-2.5 text-[11px] font-semibold text-[#2563eb] hover:bg-[#eff6ff]"
                      >
                        <EyeIcon size={13} />
                        查看
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </main>

      <footer className="flex shrink-0 items-center justify-between border-t border-[#e4e8f0] bg-white px-5 py-3 text-xs text-[#8b95a6]">
        <span>
          共 <b className="text-[#2563eb]">{total}</b> 条，第 {page}/{totalPages} 页
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPage((value) => Math.max(1, value - 1))}
            disabled={page <= 1 || loading}
            className="grid h-8 w-8 place-items-center rounded-lg border border-[#e4e8f0] bg-white text-[#64748b] disabled:opacity-40"
            aria-label="上一页"
          >
            <ChevronLeftIcon size={14} />
          </button>
          <button
            onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
            disabled={page >= totalPages || loading}
            className="grid h-8 w-8 place-items-center rounded-lg border border-[#e4e8f0] bg-white text-[#64748b] disabled:opacity-40"
            aria-label="下一页"
          >
            <ChevronRightIcon size={14} />
          </button>
        </div>
      </footer>

      {detailId !== null ? (
        <DetailModal
          detail={detail}
          loading={detailLoading}
          error={detailError}
          onClose={() => {
            setDetailId(null);
            setDetail(null);
            setDetailError(null);
          }}
          onMarkEffectiveness={(id, isEffective) => void markEffectiveness(id, isEffective)}
        />
      ) : null}
    </section>
  );
}
