import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircleIcon,
  BotIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  EyeIcon,
  ExternalLinkIcon,
  FileJsonIcon,
  LoaderIcon,
  RefreshCwIcon,
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
import { userFacingError } from "../../../lib/userFacingError";

const PAGE_SIZE = 20;
const ALL_STATUS = "all";

const STATUS_LABELS: Record<string, string> = {
  skipped: "已跳过",
  blocked: "已阻断",
  decided: "已生成",
  running: "处理中",
  failed: "生成失败",
  sent: "已自动回复",
  send_failed: "发送失败",
  send_skipped: "发送前跳过",
};

const MODE_LABELS: Record<string, string> = {
  ai_auto_reply: "AI自动回复",
  manual_takeover: "人工接管",
  dry_run: "演练",
};

const DIAGNOSTIC_KEY_LABELS: Record<string, string> = {
  status: "状态",
  result: "结果",
  reason: "原因",
  failure_stage: "失败阶段",
  blocked_reason: "阻断原因",
  skip_reason: "跳过原因",
  agent_name: "智能体名称",
  agent_id: "智能体编号",
  prompt_chars: "提示词长度",
  prompt_sha256: "提示词校验值",
  model: "模型",
  llm_used: "是否使用智能生成",
  rag_used: "是否使用知识库",
  send_status: "发送状态",
  send_source: "发送来源",
  send_gate_passed: "发送安全检查通过",
};

const STATUS_TONES: Record<string, "slate" | "blue" | "amber" | "red" | "emerald"> = {
  skipped: "slate",
  blocked: "amber",
  running: "blue",
  decided: "blue",
  failed: "red",
  sent: "emerald",
  send_failed: "red",
  send_skipped: "amber",
};

function resolveErrorMessage(error: unknown): string {
  return userFacingError(error, "数据加载失败，请稍后重试");
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
  return STATUS_LABELS[value] || "未知状态";
}

function modeLabel(value?: string | null): string {
  return value ? MODE_LABELS[value] || "其他模式" : "未知模式";
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordValue(source: unknown, key: string): unknown {
  if (!isRecord(source)) return undefined;
  return source[key];
}

function textValue(source: unknown, key: string): string | null {
  const value = recordValue(source, key);
  if (value === undefined || value === null || value === "") return null;
  return String(value);
}

function numberValue(source: unknown, key: string): number | null {
  const value = recordValue(source, key);
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function firstRecord(source: unknown, keys: string[]): Record<string, unknown> | null {
  if (!isRecord(source)) return null;
  for (const key of keys) {
    const value = source[key];
    if (isRecord(value)) return value;
  }
  return null;
}

function agentGate(source: unknown): Record<string, unknown> | null {
  return firstRecord(source, ["agent", "agent_gate", "agent_result"]);
}

function sendRecordFromItem(item: AiAutoReplyRunListItem): AiAutoReplyRunSendRecord | null {
  const value = recordValue(item, "send_record");
  return isRecord(value) ? (value as unknown as AiAutoReplyRunSendRecord) : null;
}

function gateResultsFromItem(item: AiAutoReplyRunListItem): Record<string, unknown> | null {
  const value = recordValue(item, "gate_results");
  return isRecord(value) ? value : null;
}

function agentNameFromGate(gate: Record<string, unknown> | null, fallback?: string | number | null): string {
  return textValue(gate, "agent_name") || textValue(gate, "name") || displayText(fallback);
}

function promptHashFromGate(gate: Record<string, unknown> | null): string {
  return textValue(gate, "prompt_sha256") || "-";
}

function promptCharsFromGate(gate: Record<string, unknown> | null): string {
  const chars = numberValue(gate, "prompt_chars");
  return chars === null ? "-" : String(chars);
}

function gateStatusText(gate: Record<string, unknown> | null): string {
  return textValue(gate, "status") || textValue(gate, "result") || "-";
}

function blockReasonText(item: AiAutoReplyRunListItem): string {
  return item.block_reason || item.skip_reason || "-";
}

function buildConversationHref(item: {
  account_open_id?: string | null;
  conversation_short_id?: string | null;
  customer_open_id?: string | null;
}) {
  if (!item.account_open_id || !item.conversation_short_id) return "";
  const params = new URLSearchParams();
  params.set("account_open_id", item.account_open_id);
  params.set("conversation_short_id", item.conversation_short_id);
  if (item.customer_open_id) params.set("open_id", item.customer_open_id);
  return `/douyin-ai-cs?${params.toString()}`;
}

function redactSensitiveDiagnostics(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactSensitiveDiagnostics);
  if (!isRecord(value)) return value;
  const allowKeys = new Set(["prompt_chars", "prompt_sha256"]);
  const sensitiveKeys = new Set([
    "prompt",
    "agent_prompt",
    "system_prompt",
    "user_prompt",
    "knowledge_base_text",
    "raw_response_json",
    "response_body_json",
    "request_body_json",
  ]);
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => {
      const normalized = key.toLowerCase();
      if (!allowKeys.has(normalized) && sensitiveKeys.has(normalized)) return [key, "已隐藏"];
      return [key, redactSensitiveDiagnostics(item)];
    }),
  );
}

function diagnosticEntries(record: Record<string, unknown> | null): Array<[string, string]> {
  if (!record) return [];
  return Object.entries(record)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value], index) => [
      DIAGNOSTIC_KEY_LABELS[key] || `字段${index + 1}`,
      typeof value === "object"
        ? formatJson(redactSensitiveDiagnostics(value))
        : typeof value === "boolean"
          ? booleanText(value)
          : String(value),
    ]);
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

function DiagnosticGroup({
  title,
  record,
}: {
  title: string;
  record: Record<string, unknown> | null;
}) {
  const entries = diagnosticEntries(record);
  return (
    <section className="rounded-md border border-slate-200 bg-white p-4">
      <h3 className="text-xs font-bold text-slate-900">{title}</h3>
      {entries.length === 0 ? (
        <p className="mt-3 text-xs text-slate-500">暂无</p>
      ) : (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {entries.map(([key, value]) => (
            <Field key={key} label={key} value={value} />
          ))}
        </div>
      )}
    </section>
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
      <Field label="发送流水编号" value={sendRecord.id} />
      <Field label="发送状态" value={statusLabel(sendRecord.send_status)} />
      <Field label="发送来源" value={sendRecord.send_source ? "系统发送" : "-"} />
      <Field label="是否自动发送" value={booleanText(sendRecord.auto_send)} />
      <Field label="是否人工确认" value={booleanText(sendRecord.manual_confirmed)} />
      <Field label="上游消息编号" value={sendRecord.upstream_msg_id} />
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
  onRetry,
}: {
  detail: AiAutoReplyRunDetail | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onRetry?: () => void;
}) {
  const [rawExpanded, setRawExpanded] = useState(false);
  const gateResults = isRecord(detail?.gate_results) ? detail.gate_results : null;
  const agent = agentGate(gateResults);
  const model = firstRecord(gateResults, ["llm", "model", "generation", "post_llm"]);
  const history = firstRecord(gateResults, ["history", "pre_llm", "history_messages"]);
  const manualTakeover = firstRecord(gateResults, ["manual_takeover", "autopilot", "conversation_autopilot"]);
  const sendDecision = firstRecord(gateResults, ["send_decision", "decision", "post_llm"]);
  const sendContext = firstRecord(gateResults, ["send_context", "context"]);

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/35 p-6 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="run-detail-title">
      <div className="flex max-h-[88vh] w-full max-w-[900px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-[0_24px_80px_rgba(15,23,42,0.22)]">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h2 id="run-detail-title" className="text-sm font-bold text-slate-900">自动回复诊断详情</h2>
            <p className="mt-1 text-xs text-slate-500">只读诊断信息，不包含完整提示词和上游响应原文。</p>
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
            <div className="flex min-h-[280px] flex-col items-center justify-center gap-2 text-sm text-slate-500">
              <LoaderIcon size={18} className="animate-spin" />
              <span>详情加载中...</span>
            </div>
          ) : error ? (
            <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">
              <AlertCircleIcon size={14} />
              {error}
              {onRetry ? (
                <button onClick={onRetry} className="ml-auto inline-flex h-7 items-center gap-1 rounded-md border border-red-300 bg-white px-3 text-[11px] font-semibold text-red-700 hover:bg-red-50">
                  <RefreshCwIcon size={12} />
                  重试
                </button>
              ) : null}
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
                  <Field label="运行编号" value={detail.id} />
                  <Field label="企业号" value={detail.account_open_id} />
                  <Field label="会话" value={detail.conversation_short_id} />
                  <Field label="客户" value={detail.customer_open_id} />
                  <Field label="智能体" value={agentNameFromGate(agent, detail.agent_id)} />
                  <Field label="运行模式" value={modeLabel(detail.mode)} />
                  <Field label="触发事件编号" value={detail.trigger_event_id} />
                  <Field label="触发事件标识" value={detail.trigger_event_key} />
                  <Field label="触发消息编号" value={detail.trigger_server_message_id} />
                  <Field label="决策日志编号" value={detail.decision_log_id} />
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
                  <h3 className="text-xs font-bold text-slate-900">AI 回复内容</h3>
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
                <h3 className="text-xs font-bold text-slate-900">智能体信息</h3>
                <div className="mt-3 grid gap-3 md:grid-cols-4">
                  <Field label="智能体状态" value={gateStatusText(agent)} />
                  <Field label="智能体名称" value={agentNameFromGate(agent, detail.agent_id)} />
                  <Field label="提示词长度" value={promptCharsFromGate(agent)} />
                  <Field label="提示词指纹" value={promptHashFromGate(agent)} />
                </div>
              </section>

              <section className="rounded-md border border-slate-200 bg-white p-4">
                <h3 className="text-xs font-bold text-slate-900">模型信息</h3>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <Field label="智能生成状态" value={gateStatusText(model)} />
                  <Field label="是否使用智能生成" value={booleanText(detail.llm_used)} />
                  <Field label="是否使用知识库" value={booleanText(detail.rag_used)} />
                </div>
              </section>

              <div className="grid gap-4 lg:grid-cols-2">
                <DiagnosticGroup title="历史消息" record={history} />
                <DiagnosticGroup title="智能体" record={agent} />
                <DiagnosticGroup title="模型生成" record={model} />
                <DiagnosticGroup title="人工接管" record={manualTakeover} />
                <DiagnosticGroup title="发送决策" record={sendDecision} />
                <DiagnosticGroup title="发送上下文" record={sendContext} />
              </div>

              <section className="rounded-md border border-slate-200 bg-white p-4">
                <h3 className="text-xs font-bold text-slate-900">发送流水摘要</h3>
                <div className="mt-3">
                  <SendRecordBlock sendRecord={detail.send_record} />
                </div>
              </section>

              <section className="rounded-md border border-slate-200 bg-white p-4">
                <button
                  type="button"
                  onClick={() => setRawExpanded((value) => !value)}
                  className="inline-flex items-center gap-2 text-xs font-bold text-slate-900"
                >
                  <FileJsonIcon size={15} />
                  完整诊断信息
                  <span className="text-[11px] font-semibold text-slate-500">
                    {rawExpanded ? "收起" : "展开"}
                  </span>
                </button>
                {rawExpanded ? (
                  <pre className="mt-3 max-h-[260px] overflow-auto rounded-md bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                    {formatJson(redactSensitiveDiagnostics(detail.gate_results))}
                  </pre>
                ) : null}
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

  const loadDetail = useCallback(() => {
    if (detailId === null) return;
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    getAiAutoReplyRunDetail(detailId)
      .then(setDetail)
      .catch((err) => setDetailError(resolveErrorMessage(err)))
      .finally(() => setDetailLoading(false));
  }, [detailId]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

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
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">自动回复诊断</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">
              查看 AI 自动回复从客户消息、智能体、模型生成到发送结果的链路状态，用于排查未回复、阻断、超时和发送失败问题。
            </p>
          </div>
        </div>
      </header>

      <div className="border-b border-blue-200 bg-blue-50 px-5 py-3 text-xs leading-6 text-blue-800">
        <div className="flex items-start gap-2">
          <ShieldCheckIcon size={15} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-bold">此页面只展示自动回复运行结果，不提供任何写入操作入口。</div>
            <div>真实发送只可能由新私信事件回调触发，并由系统安全检查控制；“已发送”表示发送成功，“已阻断”或“已跳过”表示未执行发送。</div>
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
            aria-label="状态筛选"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs font-semibold text-slate-700 outline-none focus:border-blue-300 focus:bg-white"
          >
            <option value={ALL_STATUS}>全部</option>
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
            placeholder="企业号"
            aria-label="企业号"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs outline-none focus:border-blue-300 focus:bg-white"
          />
          <input
            value={conversationShortId}
            onChange={(event) => {
              setConversationShortId(event.target.value);
              setPage(1);
            }}
            placeholder="会话ID"
            aria-label="会话ID"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs outline-none focus:border-blue-300 focus:bg-white"
          />
          <input
            value={customerOpenId}
            onChange={(event) => {
              setCustomerOpenId(event.target.value);
              setPage(1);
            }}
            placeholder="客户标识"
            aria-label="客户标识"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs outline-none focus:border-blue-300 focus:bg-white"
          />
          <input
            value={agentId}
            onChange={(event) => {
              setAgentId(event.target.value);
              setPage(1);
            }}
            placeholder="智能体ID"
            aria-label="智能体ID"
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
              aria-label="关键词"
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
            aria-label="起始时间"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs text-slate-700 outline-none focus:border-blue-300 focus:bg-white"
          />
          <input
            type="datetime-local"
            value={createdTo}
            onChange={(event) => {
              setCreatedTo(event.target.value);
              setPage(1);
            }}
            aria-label="截止时间"
            className="h-9 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs text-slate-700 outline-none focus:border-blue-300 focus:bg-white"
          />
          <button
            onClick={() => void loadRuns()}
            disabled={loading}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-blue-600 px-4 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {loading ? <LoaderIcon size={14} className="animate-spin" /> : <SearchIcon size={14} />}
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
            <button onClick={() => void loadRuns()} className="ml-auto inline-flex h-7 items-center gap-1 rounded-md border border-red-300 bg-white px-3 text-[11px] font-semibold text-red-700 hover:bg-red-50">
              <RefreshCwIcon size={12} />
              重试
            </button>
          </div>
        ) : loading && items.length === 0 ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
            <LoaderIcon size={16} className="animate-spin" />
            加载中...
          </div>
        ) : items.length === 0 ? (
          <div className="grid h-full place-items-center text-center">
            <div>
              <BotIcon size={30} className="mx-auto text-slate-300" />
              {hasFilters ? (
                <>
                  <p className="mt-2 text-xs text-slate-500">未找到符合条件的运行记录</p>
                  <button onClick={resetFilters} className="mt-3 inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                    <RefreshCwIcon size={12} />
                    重置筛选
                  </button>
                </>
              ) : (
                <p className="mt-2 text-xs text-slate-500">暂无自动回复运行记录，AI 自动回复触发后将在此展示</p>
              )}
            </div>
          </div>
        ) : (
          <table className="min-w-[1680px] table-fixed text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="w-[130px] px-4 py-3 font-semibold">时间</th>
                <th className="w-[150px] px-4 py-3 font-semibold">企业号</th>
                <th className="w-[140px] px-4 py-3 font-semibold">客户</th>
                <th className="w-[140px] px-4 py-3 font-semibold">会话编号</th>
                <th className="w-[180px] px-4 py-3 font-semibold">客户最新消息</th>
                <th className="w-[100px] px-4 py-3 font-semibold">运行状态</th>
                <th className="w-[100px] px-4 py-3 font-semibold">运行模式</th>
                <th className="w-[130px] px-4 py-3 font-semibold">阻断原因</th>
                <th className="w-[130px] px-4 py-3 font-semibold">错误原因</th>
                <th className="w-[150px] px-4 py-3 font-semibold">智能体</th>
                <th className="w-[140px] px-4 py-3 font-semibold">提示词指纹</th>
                <th className="w-[110px] px-4 py-3 font-semibold">是否真实发送</th>
                <th className="w-[110px] px-4 py-3 font-semibold">发送状态</th>
                <th className="w-[160px] px-4 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const gate = agentGate(gateResultsFromItem(item));
                const sendRecord = sendRecordFromItem(item);
                const conversationHref = buildConversationHref(item);
                return (
                <tr key={item.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-3 text-[11px] text-slate-500">{formatDateTimeLocal(item.created_at)}</td>
                  <td className="px-4 py-3 font-mono text-[11px] text-slate-600" title={item.account_open_id || undefined}>
                    {compactId(item.account_open_id)}
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px] text-slate-600" title={item.customer_open_id || undefined}>
                    {compactId(item.customer_open_id)}
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px] text-slate-600" title={item.conversation_short_id || undefined}>
                    {compactId(item.conversation_short_id)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="line-clamp-2 text-slate-600" title={item.latest_message_summary || undefined}>
                      {item.latest_message_summary || "-"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Chip tone={STATUS_TONES[item.status] || "slate"}>{statusLabel(item.status)}</Chip>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{modeLabel(item.mode)}</td>
                  <td className="px-4 py-3">
                    <div className="line-clamp-2 text-slate-600" title={blockReasonText(item)}>
                      {blockReasonText(item)}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="line-clamp-2 text-slate-600" title={item.error_message || undefined}>
                      {item.error_message || "-"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="line-clamp-2 text-slate-600" title={agentNameFromGate(gate, item.agent_id)}>
                      {agentNameFromGate(gate, item.agent_id)}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px] text-slate-600" title={promptHashFromGate(gate)}>
                    {compactId(promptHashFromGate(gate))}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {booleanText(sendRecord?.auto_send ?? item.final_auto_send ?? item.upstream_auto_send)}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{statusLabel(sendRecord?.send_status || item.status)}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => setDetailId(item.id)}
                        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 text-[11px] font-semibold text-blue-600 hover:bg-blue-50"
                      >
                        <EyeIcon size={13} />
                        查看详情
                      </button>
                      {conversationHref ? (
                        <a
                          href={conversationHref}
                          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 text-[11px] font-semibold text-slate-700 hover:bg-slate-50"
                        >
                          <ExternalLinkIcon size={13} />
                          跳转会话
                        </a>
                      ) : null}
                    </div>
                  </td>
                </tr>
                );
              })}
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
          onRetry={loadDetail}
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
