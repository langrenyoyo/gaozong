import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircleIcon,
  BotIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  EyeIcon,
  FileJsonIcon,
  SearchIcon,
  ShieldCheckIcon,
  XIcon,
} from "lucide-react";

import { getAiAutoReplyRunDetail, getAiAutoReplyRuns } from "../api";
import type {
  AiAutoReplyRunDetail,
  AiAutoReplyRunListItem,
  AiAutoReplyRunQueryParams,
  AiAutoReplyRunSendRecord,
} from "../types";
import { formatDateTimeLocal } from "../../../lib/datetime";

const PAGE_SIZE = 20;
const ALL_STATUS = "all";

const STATUS_LABELS: Record<string, string> = {
  skipped: "未进入决策",
  blocked: "门禁阻断",
  decided: "已决策",
  failed: "决策失败",
  sent: "已自动发送",
  send_failed: "发送失败",
  send_skipped: "发送前跳过",
};

const STATUS_TONES: Record<string, "slate" | "blue" | "amber" | "red" | "emerald"> = {
  skipped: "slate",
  blocked: "amber",
  decided: "blue",
  failed: "red",
  sent: "emerald",
  send_failed: "red",
  send_skipped: "amber",
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

function displayText(value?: string | number | null): string {
  if (value === undefined || value === null || value === "") return "-";
  return String(value);
}

function trimInput(value: string): string | undefined {
  const text = value.trim();
  return text || undefined;
}

function statusLabel(value?: string | null): string {
  if (!value) return "未知";
  return STATUS_LABELS[value] || value;
}

function compactId(value?: string | number | null): string {
  if (value === undefined || value === null) return "-";
  const text = String(value);
  return text.length > 22 ? `${text.slice(0, 10)}...${text.slice(-8)}` : text;
}

function formatJson(value: unknown): string {
  if (value === undefined || value === null) return "{}";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function booleanText(value?: boolean | number | null): string {
  if (value === true || value === 1) return "是";
  if (value === false || value === 0) return "否";
  return "-";
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

function Field({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div>
      <div className="text-[11px] font-semibold text-slate-500">{label}</div>
      <div className="mt-1 break-all text-xs font-semibold text-slate-800">{displayText(value)}</div>
    </div>
  );
}

function SendRecordBlock({ sendRecord }: { sendRecord?: AiAutoReplyRunSendRecord | null }) {
  if (!sendRecord) {
    return (
      <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 px-3 py-4 text-xs text-slate-500">
        暂无发送流水关联。
      </div>
    );
  }

  return (
    <div className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs md:grid-cols-2">
      <Field label="发送流水 ID" value={sendRecord.id} />
      <Field label="发送状态" value={sendRecord.send_status} />
      <Field label="发送来源" value={sendRecord.send_source} />
      <Field label="自动发送标记" value={booleanText(sendRecord.auto_send)} />
      <Field label="人工确认标记" value={booleanText(sendRecord.manual_confirmed)} />
      <Field label="上游消息 ID" value={sendRecord.upstream_msg_id} />
      <Field label="发送时间" value={formatDateTimeLocal(sendRecord.sent_at)} />
      <Field label="错误信息" value={sendRecord.error_message} />
    </div>
  );
}

function DetailModal({
  detail,
  loading,
  error,
  onClose,
}: {
  detail: AiAutoReplyRunDetail | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/35 p-6 backdrop-blur-sm">
      <div className="flex max-h-[88vh] w-full max-w-[900px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-[0_24px_80px_rgba(15,23,42,0.22)]">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="text-sm font-bold text-slate-900">自动回复运行详情</h2>
            <p className="mt-1 text-xs text-slate-500">只读审计信息，不包含原始模型响应。</p>
          </div>
          <button
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-md text-slate-500 hover:bg-slate-100"
            aria-label="关闭详情"
          >
            <XIcon size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="grid min-h-[280px] place-items-center text-sm text-slate-500">详情加载中...</div>
          ) : error ? (
            <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">
              <AlertCircleIcon size={14} />
              {error}
            </div>
          ) : detail ? (
            <div className="space-y-4">
              <section className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-blue-800">
                  <ShieldCheckIcon size={15} />
                  <span>此详情只展示运行结果，不提供任何写入操作入口。</span>
                  <Chip tone={STATUS_TONES[detail.status] || "slate"}>{statusLabel(detail.status)}</Chip>
                </div>
              </section>

              <section className="rounded-md border border-slate-200 bg-white p-4">
                <h3 className="text-xs font-bold text-slate-900">基础信息</h3>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <Field label="运行 ID" value={detail.id} />
                  <Field label="企业号" value={detail.account_open_id} />
                  <Field label="会话" value={detail.conversation_short_id} />
                  <Field label="客户" value={detail.customer_open_id} />
                  <Field label="Agent" value={detail.agent_id} />
                  <Field label="模式" value={detail.mode} />
                  <Field label="触发事件 ID" value={detail.trigger_event_id} />
                  <Field label="触发事件 Key" value={detail.trigger_event_key} />
                  <Field label="触发消息 ID" value={detail.trigger_server_message_id} />
                  <Field label="决策日志 ID" value={detail.decision_log_id} />
                  <Field label="创建时间" value={formatDateTimeLocal(detail.created_at)} />
                  <Field label="更新时间" value={formatDateTimeLocal(detail.updated_at)} />
                </div>
              </section>

              <div className="grid gap-4 lg:grid-cols-2">
                <section className="rounded-md border border-slate-200 bg-white p-4">
                  <h3 className="text-xs font-bold text-slate-900">最新客户消息</h3>
                  <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-slate-600">
                    {detail.latest_message || "-"}
                  </p>
                </section>
                <section className="rounded-md border border-slate-200 bg-white p-4">
                  <h3 className="text-xs font-bold text-slate-900">拟回复内容</h3>
                  <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-slate-600">
                    {detail.would_send_content || "-"}
                  </p>
                </section>
              </div>

              <section className="rounded-md border border-slate-200 bg-white p-4">
                <h3 className="text-xs font-bold text-slate-900">原因与错误</h3>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <Field label="跳过原因" value={detail.skip_reason} />
                  <Field label="阻断原因" value={detail.block_reason} />
                  <Field label="错误信息" value={detail.error_message} />
                </div>
              </section>

              <section className="rounded-md border border-slate-200 bg-white p-4">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-900">
                  <FileJsonIcon size={15} />
                  门禁结果
                </div>
                <pre className="mt-3 max-h-[260px] overflow-auto rounded-md bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                  {formatJson(detail.gate_results)}
                </pre>
              </section>

              <section className="rounded-md border border-slate-200 bg-white p-4">
                <h3 className="text-xs font-bold text-slate-900">发送流水</h3>
                <div className="mt-3">
                  <SendRecordBlock sendRecord={detail.send_record} />
                </div>
              </section>
            </div>
          ) : null}
        </div>

        <div className="flex justify-end border-t border-slate-200 px-5 py-4">
          <button
            onClick={onClose}
            className="h-9 rounded-md border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

export default function DouyinAutoReplyRunsPage() {
  const [items, setItems] = useState<AiAutoReplyRunListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState(ALL_STATUS);
  const [accountOpenId, setAccountOpenId] = useState("");
  const [conversationShortId, setConversationShortId] = useState("");
  const [customerOpenId, setCustomerOpenId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AiAutoReplyRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const queryParams = useMemo<AiAutoReplyRunQueryParams>(
    () => ({
      page,
      page_size: PAGE_SIZE,
      status: status === ALL_STATUS ? undefined : status,
      account_open_id: trimInput(accountOpenId),
      conversation_short_id: trimInput(conversationShortId),
      customer_open_id: trimInput(customerOpenId),
      agent_id: trimInput(agentId),
      keyword: trimInput(keyword),
      created_from: createdFrom || undefined,
      created_to: createdTo || undefined,
    }),
    [accountOpenId, agentId, conversationShortId, createdFrom, createdTo, customerOpenId, keyword, page, status],
  );

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAiAutoReplyRuns(queryParams);
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
  }, [page, queryParams]);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (detailId === null) return;
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    getAiAutoReplyRunDetail(detailId)
      .then(setDetail)
      .catch((err) => setDetailError(resolveErrorMessage(err)))
      .finally(() => setDetailLoading(false));
  }, [detailId]);

  const hasFilters = useMemo(
    () =>
      status !== ALL_STATUS ||
      Boolean(accountOpenId.trim()) ||
      Boolean(conversationShortId.trim()) ||
      Boolean(customerOpenId.trim()) ||
      Boolean(agentId.trim()) ||
      Boolean(keyword.trim()) ||
      Boolean(createdFrom) ||
      Boolean(createdTo),
    [accountOpenId, agentId, conversationShortId, createdFrom, createdTo, customerOpenId, keyword, status],
  );

  const resetFilters = () => {
    setStatus(ALL_STATUS);
    setAccountOpenId("");
    setConversationShortId("");
    setCustomerOpenId("");
    setAgentId("");
    setKeyword("");
    setCreatedFrom("");
    setCreatedTo("");
    setPage(1);
  };

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <BotIcon size={21} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">自动回复运行记录</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">
              查看 webhook 自动回复链路运行结果、门禁原因和发送流水关联，页面仅提供只读查询。
            </p>
          </div>
        </div>
      </header>

      <div className="border-b border-blue-200 bg-blue-50 px-5 py-3 text-xs leading-6 text-blue-800">
        <div className="flex items-start gap-2">
          <ShieldCheckIcon size={15} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-bold">此页面只展示自动回复运行结果，不提供任何写入操作入口。</div>
            <div>真实发送只可能由新私信 webhook 触发，并由后端门禁控制；sent 表示已发送，blocked / skipped 表示被门禁阻断或跳过。</div>
          </div>
        </div>
      </div>

      <div className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-3">
        <div className="grid gap-2 xl:grid-cols-[150px_190px_190px_190px_130px_minmax(180px,1fr)_170px_170px_auto_auto]">
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs font-semibold text-slate-700 outline-none focus:border-blue-300 focus:bg-white"
          >
            <option value={ALL_STATUS}>全部状态</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <input
            value={accountOpenId}
            onChange={(event) => {
              setAccountOpenId(event.target.value);
              setPage(1);
            }}
            placeholder="企业号 account_open_id"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs outline-none focus:border-blue-300 focus:bg-white"
          />
          <input
            value={conversationShortId}
            onChange={(event) => {
              setConversationShortId(event.target.value);
              setPage(1);
            }}
            placeholder="会话 conversation_short_id"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs outline-none focus:border-blue-300 focus:bg-white"
          />
          <input
            value={customerOpenId}
            onChange={(event) => {
              setCustomerOpenId(event.target.value);
              setPage(1);
            }}
            placeholder="客户 customer_open_id"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs outline-none focus:border-blue-300 focus:bg-white"
          />
          <input
            value={agentId}
            onChange={(event) => {
              setAgentId(event.target.value);
              setPage(1);
            }}
            placeholder="Agent ID"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs outline-none focus:border-blue-300 focus:bg-white"
          />
          <label className="relative">
            <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={keyword}
              onChange={(event) => {
                setKeyword(event.target.value);
                setPage(1);
              }}
              placeholder="关键词"
              className="h-9 w-full rounded-md border border-slate-200 bg-slate-50 pl-8 pr-3 text-xs outline-none focus:border-blue-300 focus:bg-white"
            />
          </label>
          <input
            type="datetime-local"
            value={createdFrom}
            onChange={(event) => {
              setCreatedFrom(event.target.value);
              setPage(1);
            }}
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs text-slate-700 outline-none focus:border-blue-300 focus:bg-white"
          />
          <input
            type="datetime-local"
            value={createdTo}
            onChange={(event) => {
              setCreatedTo(event.target.value);
              setPage(1);
            }}
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs text-slate-700 outline-none focus:border-blue-300 focus:bg-white"
          />
          <button
            onClick={() => void loadRuns()}
            disabled={loading}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-blue-600 px-4 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            <SearchIcon size={14} />
            查询
          </button>
          {hasFilters ? (
            <button
              onClick={resetFilters}
              className="h-9 rounded-md border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              重置
            </button>
          ) : (
            <button
              onClick={resetFilters}
              className="h-9 rounded-md border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-400"
            >
              重置
            </button>
          )}
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-auto bg-white">
        {error ? (
          <div className="m-5 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">
            <AlertCircleIcon size={14} />
            {error}
          </div>
        ) : loading && items.length === 0 ? (
          <div className="grid h-full place-items-center text-sm text-slate-500">加载中...</div>
        ) : items.length === 0 ? (
          <div className="grid h-full place-items-center text-center">
            <div>
              <BotIcon size={30} className="mx-auto text-slate-300" />
              <p className="mt-2 text-xs text-slate-500">暂无自动回复运行记录</p>
            </div>
          </div>
        ) : (
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="w-[70px] px-4 py-3 font-semibold">ID</th>
                <th className="w-[15%] px-4 py-3 font-semibold">企业号</th>
                <th className="w-[13%] px-4 py-3 font-semibold">会话</th>
                <th className="w-[13%] px-4 py-3 font-semibold">客户</th>
                <th className="w-[10%] px-4 py-3 font-semibold">状态</th>
                <th className="w-[12%] px-4 py-3 font-semibold">原因</th>
                <th className="w-[15%] px-4 py-3 font-semibold">最新消息</th>
                <th className="w-[15%] px-4 py-3 font-semibold">拟回复</th>
                <th className="w-[90px] px-4 py-3 font-semibold">决策日志</th>
                <th className="w-[120px] px-4 py-3 font-semibold">创建时间</th>
                <th className="w-[90px] px-4 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-3 font-semibold text-slate-800">{item.id}</td>
                  <td className="px-4 py-3 font-mono text-[11px] text-slate-600" title={item.account_open_id || undefined}>
                    {compactId(item.account_open_id)}
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px] text-slate-600" title={item.conversation_short_id || undefined}>
                    {compactId(item.conversation_short_id)}
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px] text-slate-600" title={item.customer_open_id || undefined}>
                    {compactId(item.customer_open_id)}
                  </td>
                  <td className="px-4 py-3">
                    <Chip tone={STATUS_TONES[item.status] || "slate"}>{statusLabel(item.status)}</Chip>
                  </td>
                  <td className="px-4 py-3">
                    <div className="line-clamp-2 text-slate-600" title={item.skip_reason || item.block_reason || item.error_message || undefined}>
                      {item.skip_reason || item.block_reason || item.error_message || "-"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="line-clamp-2 text-slate-600" title={item.latest_message_summary || undefined}>
                      {item.latest_message_summary || "-"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="line-clamp-2 text-slate-600" title={item.would_send_content_summary || undefined}>
                      {item.would_send_content_summary || "-"}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{displayText(item.decision_log_id)}</td>
                  <td className="px-4 py-3 text-[11px] text-slate-500">{formatDateTimeLocal(item.created_at)}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setDetailId(item.id)}
                      className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 text-[11px] font-semibold text-blue-600 hover:bg-blue-50"
                    >
                      <EyeIcon size={13} />
                      查看详情
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>

      <footer className="flex shrink-0 items-center justify-between border-t border-slate-200 bg-white px-5 py-3 text-xs text-slate-500">
        <span>
          共 <b className="text-blue-600">{total}</b> 条，第 {page}/{totalPages} 页
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPage((value) => Math.max(1, value - 1))}
            disabled={page <= 1 || loading}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 disabled:opacity-40"
          >
            <ChevronLeftIcon size={14} />
            上一页
          </button>
          <button
            onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
            disabled={page >= totalPages || loading}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 disabled:opacity-40"
          >
            下一页
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
        />
      ) : null}
    </section>
  );
}
