import {
  AlertCircleIcon,
  CheckIcon,
  ClipboardIcon,
  DatabaseIcon,
  ShieldCheckIcon,
  TagIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import type { ReplySourceChunk, ReplySuggestionResponse } from "../../../api/douyinAiCsClient";

export type ReplyDecisionPanelProps = {
  reply: ReplySuggestionResponse;
  copied: boolean;
  onCopy: () => void;
  onManualSend: () => void;
  manualSendDisabled?: boolean;
};

const INTENT_TEXT: Record<string, string> = {
  price: "询价",
  inventory: "库存",
  test_drive: "试驾",
  contact: "留资/联系",
  complaint: "投诉",
  unknown: "未知",
};

const LEAD_LEVEL_TEXT: Record<string, string> = {
  high: "高意向",
  medium: "中意向",
  low: "低意向",
  unknown: "未知",
};

const RISK_FLAG_TEXT: Record<string, string> = {
  price_commitment: "价格承诺风险",
  no_rag_source: "知识库无命中",
  llm_json_parse_failed: "结构化解析失败",
  llm_requested_auto_send: "模型请求自动发送",
  proxy_forced_auto_send_false: "代理已强制关闭自动发送",
  prompt_injection: "提示词注入风险",
};

const CONTACT_KEY_TEXT: Record<string, string> = {
  phone: "手机号",
  wechat: "微信",
};

function displayText(value: string | null | undefined, fallback = "未知") {
  if (!value || !String(value).trim()) return fallback;
  return String(value).trim();
}

function mappedText(value: string | null | undefined, mapping: Record<string, string>) {
  const raw = displayText(value, "unknown");
  return mapping[raw] || raw;
}

function normalizeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" || typeof item === "number" ? String(item).trim() : ""))
    .filter(Boolean);
}

function normalizeConfidence(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未知";
  const normalized = value > 1 ? Math.min(100, Math.max(0, value)) : Math.min(100, Math.max(0, value * 100));
  return `${Math.round(normalized)}%`;
}

function normalizeContacts(value: ReplySuggestionResponse["detected_contacts"]): string[] {
  if (Array.isArray(value)) {
    return normalizeStringArray(value);
  }
  if (!value || typeof value !== "object") {
    return [];
  }
  return Object.entries(value)
    .map(([key, rawValue]) => {
      const label = CONTACT_KEY_TEXT[key] || key;
      if (typeof rawValue === "boolean") return `${label}: ${rawValue ? "是" : "否"}`;
      if (rawValue === null || rawValue === undefined || rawValue === "") return `${label}: 未识别`;
      return `${label}: ${String(rawValue)}`;
    })
    .filter(Boolean);
}

function sourceList(reply: ReplySuggestionResponse): ReplySourceChunk[] {
  if (Array.isArray(reply.rag_sources) && reply.rag_sources.length > 0) {
    return reply.rag_sources;
  }
  return Array.isArray(reply.source_chunks) ? reply.source_chunks : [];
}

function Chip({
  children,
  tone = "slate",
}: {
  children: ReactNode;
  tone?: "slate" | "blue" | "amber" | "emerald" | "red";
}) {
  const classes = {
    slate: "border-slate-200 bg-slate-50 text-slate-600",
    blue: "border-blue-200 bg-blue-50 text-blue-700",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-700",
    red: "border-red-200 bg-red-50 text-red-700",
  };
  return (
    <span className={`inline-flex min-h-6 items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold ${classes[tone]}`}>
      {children}
    </span>
  );
}

export function ReplyDecisionPanel({
  reply,
  copied,
  onCopy,
  onManualSend,
  manualSendDisabled,
}: ReplyDecisionPanelProps) {
  const tags = normalizeStringArray(reply.tags);
  const riskFlags = normalizeStringArray(reply.risk_flags);
  const contacts = normalizeContacts(reply.detected_contacts);
  const sources = sourceList(reply);
  const manualRequired = Boolean(reply.manual_required);

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-800">
        <div className="flex flex-wrap items-center gap-2">
          <ShieldCheckIcon size={15} className="shrink-0" />
          <span className="font-bold">仅生成建议，不会自动发送</span>
          <Chip tone="emerald">auto_send={String(Boolean(reply.auto_send))}</Chip>
        </div>
      </div>

      <div className="rounded-md border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-800">
        {reply.reply_text || "暂无建议内容"}
      </div>

      <div className="grid gap-2 text-xs text-slate-600 sm:grid-cols-4">
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="text-[11px] text-slate-500">客户意图</div>
          <div className="mt-1 font-bold text-[#172033]">{mappedText(reply.intent, INTENT_TEXT)}</div>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="text-[11px] text-slate-500">意向等级</div>
          <div className="mt-1 font-bold text-[#172033]">{mappedText(reply.lead_level, LEAD_LEVEL_TEXT)}</div>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="text-[11px] text-slate-500">置信度</div>
          <div className="mt-1 font-bold text-[#172033]">{normalizeConfidence(reply.confidence)}</div>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="text-[11px] text-slate-500">人工确认</div>
          <div className={manualRequired ? "mt-1 font-bold text-amber-700" : "mt-1 font-bold text-emerald-700"}>
            {manualRequired ? "需要" : "不需要"}
          </div>
        </div>
      </div>

      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
        <div className="mb-2 flex items-center gap-2 text-xs font-bold text-slate-700">
          <TagIcon size={14} />
          标签与识别
        </div>
        <div className="flex flex-wrap gap-2">
          {tags.map((tag) => (
            <Chip key={`tag-${tag}`} tone="blue">{tag}</Chip>
          ))}
          {reply.detected_vehicle ? <Chip tone="slate">车型: {reply.detected_vehicle}</Chip> : null}
          {contacts.map((contact) => (
            <Chip key={`contact-${contact}`} tone="slate">{contact}</Chip>
          ))}
          {!tags.length && !reply.detected_vehicle && !contacts.length ? (
            <span className="text-xs text-slate-500">暂无标签或识别信息</span>
          ) : null}
        </div>
      </div>

      {reply.manual_required_reason ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          <span className="font-bold">人工确认原因：</span>
          {reply.manual_required_reason}
        </div>
      ) : null}

      {riskFlags.length ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2">
          <div className="mb-2 flex items-center gap-2 text-xs font-bold text-red-700">
            <AlertCircleIcon size={14} />
            风险提示
          </div>
          <div className="flex flex-wrap gap-2">
            {riskFlags.map((flag) => (
              <Chip key={`risk-${flag}`} tone="red">{RISK_FLAG_TEXT[flag] || flag}</Chip>
            ))}
          </div>
        </div>
      ) : null}

      {reply.warnings?.length ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {reply.warnings.join("，")}
        </div>
      ) : null}

      <div className="rounded-md border border-slate-200">
        <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-2 text-xs font-bold text-slate-600">
          <DatabaseIcon size={14} />
          命中知识来源
        </div>
        {sources.length ? (
          <div className="divide-y divide-slate-100">
            {sources.map((chunk, index) => (
              <div key={`${chunk.document_id}-${chunk.chunk_id}-${index}`} className="px-3 py-2 text-xs text-slate-600">
                #{chunk.chunk_id} · 文档 {chunk.document_id} · {chunk.title} · score {chunk.score}
              </div>
            ))}
          </div>
        ) : (
          <div className="px-3 py-2 text-xs text-slate-500">暂无 RAG 来源。</div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span>decision_version: {reply.decision_version || "unknown"}</span>
        <span>llm_used: {String(reply.llm_used)}</span>
        <span>rag_used: {String(reply.rag_used)}</span>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={onCopy}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50"
        >
          <ClipboardIcon size={14} />
          {copied ? "已复制" : "复制回复"}
        </button>
        <button
          onClick={onManualSend}
          disabled={manualSendDisabled}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <CheckIcon size={14} />
          人工确认发送
        </button>
      </div>
    </div>
  );
}
