import {
  AlertTriangleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  EyeIcon,
  InboxIcon,
  LoaderIcon,
  RefreshCwIcon,
  SearchIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { fetchWebhookEventDetail, fetchWebhookEvents } from "../api";
import type { WebhookEvent, WebhookEventDetail } from "../types";
import { formatDateTimeLocal } from "../../../lib/datetime";

const LEAD_ACTION_OPTIONS = [
  "duplicate_event",
  "valid_lead",
  "non_lead_event",
  "not_lead_event",
  "invalid_content",
  "non_text_message",
  "invalid_contact",
  "contact_not_found",
  "unknown",
] as const;

const EVENT_OPTIONS = ["im_receive_msg", "im_send_msg", "im_enter_direct_msg"] as const;

const EVENT_LABELS: Record<string, string> = {
  im_receive_msg: "客户私信",
  im_send_msg: "企业号发送",
  im_enter_direct_msg: "进入私信会话",
};

const LEAD_ACTION_LABELS: Record<string, string> = {
  duplicate_event: "重复事件",
  valid_lead: "有效线索",
  non_lead_event: "非线索事件",
  not_lead_event: "非线索事件",
  invalid_content: "内容无效",
  non_text_message: "非文本消息",
  invalid_contact: "未提取到联系方式",
  contact_not_found: "未提取到联系方式",
  unknown: "未知状态",
};

const LEAD_ACTION_TONES: Record<string, string> = {
  duplicate_event: "bg-slate-100 text-slate-700 ring-slate-200",
  valid_lead: "bg-emerald-100 text-emerald-700 ring-emerald-200",
  non_lead_event: "bg-blue-100 text-blue-700 ring-blue-200",
  not_lead_event: "bg-blue-100 text-blue-700 ring-blue-200",
  invalid_content: "bg-red-100 text-red-700 ring-red-200",
  non_text_message: "bg-amber-100 text-amber-700 ring-amber-200",
  invalid_contact: "bg-orange-100 text-orange-700 ring-orange-200",
  contact_not_found: "bg-orange-100 text-orange-700 ring-orange-200",
  unknown: "bg-zinc-100 text-zinc-700 ring-zinc-200",
};

const CONTACT_EXTRACT_LABELS: Record<string, string> = {
  matched: "已提取",
  not_matched: "未提取",
  no_contact: "未提取",
  failed: "提取失败",
  parse_failed: "提取失败",
  unknown: "未知",
};

interface Filters {
  event: string;
  leadAction: string;
  isDuplicate: "all" | "true" | "false";
  keyword: string;
  startTime: string;
  endTime: string;
}

const initialFilters: Filters = {
  event: "",
  leadAction: "",
  isDuplicate: "all",
  keyword: "",
  startTime: "",
  endTime: "",
};

function formatTime(value: string | null): string {
  return formatDateTimeLocal(value);
}

function valueOrDash(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function nonEmptyText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function parseRecord(value: unknown): Record<string, unknown> | null {
  if (!value) return null;
  if (typeof value === "string") {
    try {
      return parseRecord(JSON.parse(value) as unknown);
    } catch {
      return null;
    }
  }
  if (typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function objectValue(source: unknown, key: string): unknown {
  const record = parseRecord(source);
  return record?.[key];
}

function summarize(value: string | null, max = 52): string {
  if (!value) return "-";
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

function shortId(value: string, head = 10, tail = 6): string {
  return value.length > head + tail + 3 ? `${value.slice(0, head)}...${value.slice(-tail)}` : value;
}

const LONG_ID_FIELDS = new Set([
  "event_key",
  "server_message_id",
  "conversation_short_id",
  "from_user_id",
  "to_user_id",
]);

function duplicateLabel(value: boolean | string | number | null | undefined): string {
  if (value === true || value === "true" || value === "是") return "是";
  if (value === false || value === "false" || value === "否") return "否";
  return valueOrDash(value);
}

function contactExtractDisplay(value: string | number | boolean | null | undefined): { text: string; title?: string } {
  const raw = valueOrDash(value);
  if (raw === "-") return { text: "-" };
  return { text: CONTACT_EXTRACT_LABELS[raw] || `其他状态（${raw}）`, title: raw };
}

function contactExtractLabel(value: string | null): string {
  return contactExtractDisplay(value).text;
}

function fieldDisplay(
  key: string,
  value: string | number | boolean | null | undefined,
): { text: string; title?: string } {
  const text = valueOrDash(value);
  if (key === "event") {
    return eventDisplay(value);
  }
  if (key === "lead_action") {
    return leadActionDisplay(value);
  }
  if (key === "contact_extract_status") {
    return contactExtractDisplay(value);
  }
  if (key === "is_duplicate") {
    return { text: duplicateLabel(value) };
  }
  if (key === "lead_id" && text === "-") {
    return { text: "未生成" };
  }
  if (text !== "-" && LONG_ID_FIELDS.has(key)) {
    return { text: shortId(text), title: text };
  }
  return { text };
}

function eventDisplay(value: string | number | boolean | null | undefined): { text: string; title?: string } {
  const raw = valueOrDash(value);
  if (raw === "-") return { text: "-" };
  return { text: EVENT_LABELS[raw] || `其他事件（${raw}）`, title: raw };
}

function eventLabel(value: string | null): string {
  return eventDisplay(value).text;
}

function leadActionDisplay(value: string | number | boolean | null | undefined): { text: string; title?: string } {
  const raw = valueOrDash(value);
  if (raw === "-") return { text: "-" };
  return { text: LEAD_ACTION_LABELS[raw] || `其他状态（${raw}）`, title: raw };
}

function leadActionLabel(value: string | null): string {
  return leadActionDisplay(value).text;
}

function leadActionClass(value: string): string {
  return LEAD_ACTION_TONES[value] || "bg-slate-100 text-slate-700 ring-slate-200";
}

function rawBodyText(event: WebhookEventDetail, key: string): string | null {
  return nonEmptyText(objectValue(event.raw_body, key)) || nonEmptyText(objectValue(objectValue(event.raw_body, "content"), key));
}

function findNameForUserId(value: unknown, userId: string | null): string | null {
  if (!value || !userId) return null;
  const record = parseRecord(value);
  if (!record) return null;
  const relatedIds = [
    record.open_id,
    record.user_id,
    record.from_user_id,
    record.to_user_id,
    record.account_open_id,
  ];
  const name =
    nonEmptyText(record.nick_name) ||
    nonEmptyText(record.nickname) ||
    nonEmptyText(record.douyin_nick_name) ||
    nonEmptyText(record.display_name) ||
    nonEmptyText(record.customer_name);
  if (name && relatedIds.some((item) => item === userId)) return name;

  for (const child of Object.values(record)) {
    if (Array.isArray(child)) {
      for (const item of child) {
        const found = findNameForUserId(item, userId);
        if (found) return found;
      }
    } else if (typeof child === "object" || typeof child === "string") {
      const found = findNameForUserId(child, userId);
      if (found) return found;
    }
  }
  return null;
}

function partyRole(event: WebhookEventDetail, userId: string | null, side: "from" | "to"): "customer" | "business" | "unknown" {
  if (event.event === "im_receive_msg") return side === "from" ? "customer" : "business";
  if (event.event === "im_send_msg") return side === "from" ? "business" : "customer";

  const customerIds = [event.body_open_id, event.content_open_id, rawBodyText(event, "open_id")];
  const businessIds = [event.body_account_open_id, event.content_account_open_id, rawBodyText(event, "account_open_id")];
  if (userId && customerIds.includes(userId)) return "customer";
  if (userId && businessIds.includes(userId)) return "business";
  return "unknown";
}

function getPartyDisplayName(event: WebhookEventDetail, userId: string | null, side: "from" | "to"): { text: string; title?: string } {
  const role = partyRole(event, userId, side);
  const nickname = findNameForUserId(event.raw_body, userId);
  if (nickname) return { text: nickname, title: userId || undefined };
  if (role === "customer" && event.customer_contact) return { text: `客户 ${event.customer_contact}`, title: userId || undefined };
  if (role === "customer" && event.lead_id) return { text: "客户（已生成线索）", title: userId || undefined };
  if (role === "customer") return { text: "客户", title: userId || undefined };
  if (role === "business") return { text: "企业号", title: userId || undefined };
  return { text: userId ? "未知账号" : "未知账号", title: userId || undefined };
}

function toApiDateTime(value: string): string | undefined {
  if (!value) return undefined;
  return new Date(value).toISOString();
}

function rawBodyPreview(rawBody: Record<string, unknown> | null): string {
  if (!rawBody) return "原始内容为空或解析失败";
  try {
    return JSON.stringify(rawBody, null, 2);
  } catch {
    return "原始内容无法序列化";
  }
}

function FieldRow({
  label,
  fieldKey,
  value,
}: {
  label: string;
  fieldKey: string;
  value: string | number | boolean | null | undefined;
}) {
  const display = fieldDisplay(fieldKey, value);
  return (
    <div className="flex min-w-0 justify-between gap-4 border-b border-[#eef2f7] py-2 last:border-b-0">
      <span className="shrink-0 text-[#8b95a6]">{label}</span>
      <strong className="min-w-0 break-words text-right font-semibold text-[#334155]" title={display.title}>
        {display.text}
      </strong>
    </div>
  );
}

function DisplayRow({ label, text, title }: { label: string; text: string; title?: string }) {
  return (
    <div className="flex min-w-0 justify-between gap-4 border-b border-[#eef2f7] py-2 last:border-b-0">
      <span className="shrink-0 text-[#8b95a6]">{label}</span>
      <strong className="min-w-0 break-words text-right font-semibold text-[#334155]" title={title}>
        {text}
      </strong>
    </div>
  );
}

function DetailPanel({
  event,
  loading,
  error,
}: {
  event: WebhookEventDetail | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <aside className="flex h-full min-h-0 flex-col overflow-hidden border-l border-[#e4e8f0] bg-white">
        <div className="grid h-full place-items-center text-xs text-[#8b95a6]">
          <span className="inline-flex items-center gap-2">
            <LoaderIcon size={14} className="animate-spin" />
            加载事件详情
          </span>
        </div>
      </aside>
    );
  }

  if (error) {
    return (
      <aside className="flex h-full min-h-0 flex-col overflow-hidden border-l border-[#e4e8f0] bg-white">
        <div className="grid h-full place-items-center px-5 text-center">
          <div>
            <AlertTriangleIcon className="mx-auto text-red-500" size={24} />
            <p className="mt-3 text-sm font-bold text-[#1a1f2e]">{error}</p>
          </div>
        </div>
      </aside>
    );
  }

  if (!event) {
    return (
      <aside className="flex h-full min-h-0 flex-col overflow-hidden border-l border-[#e4e8f0] bg-white">
        <div className="grid h-full place-items-center px-5 text-center text-xs text-[#8b95a6]">
          选择一条事件查看详情
        </div>
      </aside>
    );
  }

  const fromParty = getPartyDisplayName(event, event.from_user_id, "from");
  const toParty = getPartyDisplayName(event, event.to_user_id, "to");

  return (
    <aside className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden border-l border-[#e4e8f0] bg-white">
      <header className="shrink-0 border-b border-[#e4e8f0] px-5 py-4">
        <p className="text-[11px] font-semibold text-[#8b95a6]">事件详情</p>
        <div className="mt-2 flex items-center justify-between gap-3">
          <h2 className="text-base font-bold text-[#1a1f2e]">#{event.id}</h2>
          <span
            className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ${leadActionClass(event.lead_action)}`}
            title={event.lead_action || undefined}
          >
            {leadActionLabel(event.lead_action)}
          </span>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-5 py-4 text-xs">
        <section className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-3">
          <p className="mb-2 font-bold text-[#1a1f2e]">基础字段</p>
          <FieldRow label="事件类型" fieldKey="event" value={event.event} />
          <FieldRow label="线索结果" fieldKey="lead_action" value={event.lead_action} />
          <FieldRow label="是否重复" fieldKey="is_duplicate" value={event.is_duplicate} />
          <FieldRow label="线索ID" fieldKey="lead_id" value={event.lead_id} />
          <FieldRow label="接收时间" fieldKey="created_at" value={formatTime(event.created_at)} />
          <DisplayRow label="发送方" text={fromParty.text} title={fromParty.title} />
          <DisplayRow label="接收方" text={toParty.text} title={toParty.title} />
        </section>

        <section className="mt-3 rounded-xl border border-[#e4e8f0] bg-white p-3">
          <p className="mb-2 font-bold text-[#1a1f2e]">解析摘要</p>
          <FieldRow label="提取状态" fieldKey="contact_extract_status" value={event.contact_extract_status} />
          <FieldRow label="联系方式" fieldKey="customer_contact" value={event.customer_contact} />
          <FieldRow label="失败原因" fieldKey="failure_reason" value={event.failure_reason} />
          <p className="mt-3 text-[10px] font-semibold text-[#8b95a6]">消息内容</p>
          <div className="mt-3 max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-[#f8fafc] p-3 leading-6 text-[#475569]">
            {event.message_text || "无消息文本"}
          </div>
        </section>

        <details className="mt-3 rounded-xl border border-[#e4e8f0] bg-[#f8fafc]">
          <summary className="cursor-pointer px-3 py-3 text-xs font-bold text-[#334155]">调试信息</summary>
          <div className="border-t border-[#e4e8f0] px-3 py-2">
            <FieldRow label="from_user_id" fieldKey="from_user_id" value={event.from_user_id} />
            <FieldRow label="to_user_id" fieldKey="to_user_id" value={event.to_user_id} />
            <FieldRow label="event_key" fieldKey="event_key" value={event.event_key} />
            <FieldRow label="server_message_id" fieldKey="server_message_id" value={event.server_message_id} />
            <FieldRow label="conversation_short_id" fieldKey="conversation_short_id" value={event.conversation_short_id} />
          </div>
        </details>

        <details className="mt-3 rounded-xl border border-[#e4e8f0] bg-[#0f172a] text-white">
          <summary className="cursor-pointer px-3 py-3 text-xs font-bold">原始内容</summary>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words border-t border-white/10 p-3 text-[11px] leading-5 text-slate-200">
            {rawBodyPreview(event.raw_body)}
          </pre>
        </details>
      </div>
    </aside>
  );
}

export default function WebhookEventsPage() {
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [appliedFilters, setAppliedFilters] = useState<Filters>(initialFilters);
  const [events, setEvents] = useState<WebhookEvent[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<WebhookEventDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages);

  const hasActiveFilters = useMemo(
    () => Object.values(appliedFilters).some((value) => value !== "" && value !== "all"),
    [appliedFilters],
  );

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchWebhookEvents({
        page,
        page_size: pageSize,
        event: appliedFilters.event.trim() || undefined,
        lead_action: appliedFilters.leadAction || undefined,
        is_duplicate:
          appliedFilters.isDuplicate === "all" ? undefined : appliedFilters.isDuplicate === "true",
        keyword: appliedFilters.keyword.trim() || undefined,
        start_time: toApiDateTime(appliedFilters.startTime),
        end_time: toApiDateTime(appliedFilters.endTime),
      });
      const items = result.data.items || [];
      setEvents(items);
      setTotal(result.data.total || 0);
      setSelectedId((current) => {
        if (current && !items.some((item) => item.id === current)) {
          setDetail(null);
          return null;
        }
        return current;
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "原始事件加载失败";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [appliedFilters, page, pageSize]);

  const loadDetail = useCallback(async (eventId: number) => {
    setSelectedId(eventId);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const result = await fetchWebhookEventDetail(eventId);
      setDetail(result.data);
    } catch (err: unknown) {
      const maybeStatus = (err as { response?: { status?: number } }).response?.status;
      const message = maybeStatus === 404 ? "事件不存在" : err instanceof Error ? err.message : "详情加载失败";
      setDetail(null);
      setDetailError(message);
      toast.error(message);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadEvents();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadEvents]);

  const applyFilters = () => {
    setPage(1);
    setAppliedFilters(filters);
  };

  const resetFilters = () => {
    setFilters(initialFilters);
    setAppliedFilters(initialFilters);
    setPage(1);
  };

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">原始事件 / 无效事件</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">
              只读查看系统收到的原始事件，未形成有效线索的事件不会进入有效线索列表。
            </p>
          </div>
          <button
            onClick={loadEvents}
            disabled={loading}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-[#dbe3ef] bg-white px-3 text-xs font-semibold text-[#374151] shadow-[0_1px_2px_rgba(15,23,42,0.04)] disabled:opacity-60"
          >
            {loading ? <LoaderIcon size={14} className="animate-spin" /> : <RefreshCwIcon size={14} />}
            刷新
          </button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px] max-[1240px]:grid-cols-1">
        <main className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-white">
          <div className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-3">
            <div className="grid grid-cols-[160px_180px_120px_minmax(180px,1fr)_170px_170px_auto_auto] gap-2 text-xs max-[1320px]:grid-cols-4">
              <select
                value={filters.event}
                aria-label="事件类型筛选"
                onChange={(event) => setFilters((prev) => ({ ...prev, event: event.target.value }))}
                className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 font-semibold text-[#374151] outline-none"
              >
                <option value="">全部事件类型</option>
                {EVENT_OPTIONS.map((item) => (
                  <option key={item} value={item}>
                    {eventLabel(item)}
                  </option>
                ))}
              </select>
              <select
                value={filters.leadAction}
                aria-label="线索结果筛选"
                onChange={(event) => setFilters((prev) => ({ ...prev, leadAction: event.target.value }))}
                className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 font-semibold text-[#374151] outline-none"
              >
                <option value="">全部线索结果</option>
                {LEAD_ACTION_OPTIONS.map((item) => (
                  <option key={item} value={item}>
                    {leadActionLabel(item)}
                  </option>
                ))}
              </select>
              <select
                value={filters.isDuplicate}
                aria-label="重复事件筛选"
                onChange={(event) =>
                  setFilters((prev) => ({ ...prev, isDuplicate: event.target.value as Filters["isDuplicate"] }))
                }
                className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 font-semibold text-[#374151] outline-none"
              >
                <option value="all">重复：全部</option>
                <option value="true">重复：是</option>
                <option value="false">重复：否</option>
              </select>
              <label className="relative">
                <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
                <input
                  value={filters.keyword}
                  onChange={(event) => setFilters((prev) => ({ ...prev, keyword: event.target.value }))}
                  aria-label="搜索事件键或原始内容"
                  placeholder="关键词：事件键 / 原始内容"
                  className="h-9 w-full rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                />
              </label>
              <input
                type="datetime-local"
                aria-label="开始时间"
                value={filters.startTime}
                onChange={(event) => setFilters((prev) => ({ ...prev, startTime: event.target.value }))}
                className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none"
              />
              <input
                type="datetime-local"
                aria-label="结束时间"
                value={filters.endTime}
                onChange={(event) => setFilters((prev) => ({ ...prev, endTime: event.target.value }))}
                className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none"
              />
              <button
                onClick={applyFilters}
                className="h-9 rounded-xl bg-[#2563eb] px-4 font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.18)]"
              >
                查询
              </button>
              <button
                onClick={resetFilters}
                className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 font-semibold text-[#374151]"
              >
                重置
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {loading ? (
              <div className="grid h-full place-items-center text-xs text-[#8b95a6]">
                <span className="inline-flex items-center gap-2">
                  <LoaderIcon size={14} className="animate-spin" />
                  加载原始事件
                </span>
              </div>
            ) : error ? (
              <div className="grid h-full place-items-center px-8 text-center">
                <div>
                  <AlertTriangleIcon className="mx-auto text-red-500" size={24} />
                  <p className="mt-3 text-sm font-semibold text-[#1a1f2e]">数据加载失败</p>
                  <p className="mt-2 text-xs text-[#8b95a6]">{error}</p>
                </div>
              </div>
            ) : events.length === 0 ? (
              <div className="grid h-full place-items-center px-8 text-center">
                <div>
                  <InboxIcon className="mx-auto text-[#94a3b8]" size={28} />
                  <p className="mt-3 text-sm font-semibold text-[#1a1f2e]">
                    {hasActiveFilters ? "没有匹配的原始事件" : "暂无原始事件"}
                  </p>
                </div>
              </div>
            ) : (
              <table className="w-full table-fixed text-left text-xs">
                <thead className="sticky top-0 z-10 bg-[#f8fafc] text-[#64748b] shadow-[inset_0_-1px_0_#e4e8f0]">
                  <tr>
                    <th className="w-[70px] px-4 py-3 font-semibold">事件ID</th>
                    <th className="w-[130px] px-4 py-3 font-semibold">事件类型</th>
                    <th className="w-[150px] px-4 py-3 font-semibold">线索结果</th>
                    <th className="w-[86px] px-4 py-3 font-semibold">是否重复</th>
                    <th className="w-[90px] px-4 py-3 font-semibold">线索ID</th>
                    <th className="w-[150px] px-4 py-3 font-semibold">消息ID</th>
                    <th className="w-[150px] px-4 py-3 font-semibold">会话ID</th>
                    <th className="w-[260px] px-4 py-3 font-semibold">消息内容</th>
                    <th className="w-[130px] px-4 py-3 font-semibold">提取状态</th>
                    <th className="w-[130px] px-4 py-3 font-semibold">联系方式</th>
                    <th className="w-[150px] px-4 py-3 font-semibold">失败原因</th>
                    <th className="w-[120px] px-4 py-3 font-semibold">接收时间</th>
                    <th className="w-[96px] px-4 py-3 font-semibold">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((item) => {
                    const active = selectedId === item.id;
                    return (
                      <tr
                        key={item.id}
                        onClick={() => loadDetail(item.id)}
                        className={`cursor-pointer border-t border-[#f0f2f7] transition-smooth ${
                          active ? "bg-[#eff6ff]" : "hover:bg-[#f8fafc]"
                        }`}
                      >
                        <td className="px-4 py-3 font-bold text-[#1a1f2e]">#{item.id}</td>
                        <td className="px-4 py-3 text-[#334155]" title={item.event || undefined}>
                          {eventLabel(item.event)}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ${leadActionClass(item.lead_action)}`}
                            title={item.lead_action || undefined}
                          >
                            {leadActionLabel(item.lead_action)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-[#334155]">{duplicateLabel(item.is_duplicate)}</td>
                        <td className="px-4 py-3 text-[#334155]">{valueOrDash(item.lead_id)}</td>
                        <td className="truncate px-4 py-3 text-[#475569]" title={item.server_message_id || undefined}>
                          {item.server_message_id ? shortId(item.server_message_id) : "-"}
                        </td>
                        <td className="truncate px-4 py-3 text-[#475569]" title={item.conversation_short_id || undefined}>
                          {item.conversation_short_id ? shortId(item.conversation_short_id) : "-"}
                        </td>
                        <td className="px-4 py-3 text-[#475569]" title={item.message_text || ""}>
                          {summarize(item.message_text)}
                        </td>
                        <td className="px-4 py-3 text-[#334155]" title={item.contact_extract_status || undefined}>
                          {contactExtractLabel(item.contact_extract_status)}
                        </td>
                        <td className="px-4 py-3 text-[#334155]">{valueOrDash(item.customer_contact)}</td>
                        <td className="px-4 py-3 text-[#64748b]">{valueOrDash(item.failure_reason)}</td>
                        <td className="px-4 py-3 text-[#64748b]">{formatTime(item.created_at)}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={(event) => {
                              event.stopPropagation();
                              loadDetail(item.id);
                            }}
                            className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#f8fafc] px-2 text-[11px] font-semibold text-[#2563eb] ring-1 ring-[#e4e8f0] hover:bg-white"
                          >
                            <EyeIcon size={12} />
                            查看
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          <footer className="flex shrink-0 items-center justify-between border-t border-[#e4e8f0] bg-white px-5 py-3 text-xs">
            <div className="flex items-center gap-3 text-[#64748b]">
              <span>
                共 <b className="text-[#2563eb]">{total}</b> 条
              </span>
              <label className="flex items-center gap-1.5">
                每页
                <select
                  value={pageSize}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    setPage(1);
                  }}
                  className="h-8 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs font-semibold text-[#374151] outline-none"
                >
                  {[10, 20, 50, 100].map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
                条
              </label>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                disabled={safePage === 1}
                aria-label="上一页"
                className="grid h-8 w-8 place-items-center rounded-lg border border-[#e4e8f0] bg-white text-[#64748b] enabled:hover:bg-[#f8fafc] disabled:cursor-not-allowed disabled:opacity-45"
              >
                <ChevronLeftIcon size={14} />
              </button>
              <span className="px-2 font-semibold text-[#334155]">
                {safePage} / {totalPages}
              </span>
              <button
                onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                disabled={safePage === totalPages}
                aria-label="下一页"
                className="grid h-8 w-8 place-items-center rounded-lg border border-[#e4e8f0] bg-white text-[#64748b] enabled:hover:bg-[#f8fafc] disabled:cursor-not-allowed disabled:opacity-45"
              >
                <ChevronRightIcon size={14} />
              </button>
            </div>
          </footer>
        </main>

        <div className="min-h-0 overflow-hidden max-[1240px]:hidden">
          <DetailPanel event={detail} loading={detailLoading} error={detailError} />
        </div>
      </div>
    </section>
  );
}
