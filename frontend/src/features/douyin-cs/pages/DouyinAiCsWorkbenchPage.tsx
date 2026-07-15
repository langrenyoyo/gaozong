import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircleIcon,
  BotIcon,
  CheckIcon,
  ClipboardIcon,
  DownloadIcon,
  ImagePlusIcon,
  LoaderIcon,
  MessageCircleMoreIcon,
  PaperclipIcon,
  PlusIcon,
  QrCodeIcon,
  RefreshCwIcon,
  SearchIcon,
  SmileIcon,
  VideoIcon,
  WrenchIcon,
  XIcon,
  UserRoundIcon,
} from "lucide-react";

import {
  bindAuthorizedOpenId,
  fetchDouyinLiveCheckAuthUrl,
  fetchDouyinLiveCheckStatus,
} from "../api";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { formatDateTimeLocal } from "../../../lib/datetime";
import type {
  DouyinLiveCheckAuthUrlData,
  DouyinLiveCheckStatusData,
} from "../types";
import {
  bindAgentToDouyinAccount,
  downloadDouyinResource,
  getAiAutoReplyRunDetail,
  getAiAutoReplyRuns,
  getDouyinAutoReplySetting,
  getDouyinConversationAutopilot,
  getDouyinAccountAgents,
  getDouyinAccountConversations,
  getDouyinConversationProfileFrom9000,
  getDouyinConversationMessages,
  listDouyinAccounts,
  markDouyinConversationRead,
  resumeDouyinConversationAutopilot,
  sendDouyinManualMessage,
  unbindAgentFromDouyinAccount,
  updateDouyinAutoReplyMode,
  uploadDouyinImage,
  type DouyinAccountItem,
  type DouyinAgentItem,
  type DouyinConversationItem,
  type DouyinConversationProfile,
  type DouyinMessageItem,
  type DouyinAutoReplyMode,
  type DouyinConversationAutopilotState,
  type AiAutoReplyRunDetail,
  type AiAutoReplyRunListItem,
  type UploadDouyinImageResponse,
} from "../api";

const MAX_UPLOAD_IMAGE_BYTES = 10 * 1024 * 1024;
const ALLOWED_UPLOAD_IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/bmp", "image/webp"];
const ALLOWED_UPLOAD_IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".bmp", ".webp"];
const UPLOAD_IMAGE_VALIDATION_MESSAGE =
  "请选择 jpg/jpeg/png/bmp/webp 格式图片，且大小不超过 10MB。";
const AUTH_POLLING_INTERVAL_MS = 2000;
const AUTH_POLLING_TIMEOUT_MS = 120000;
const AUTH_SUCCESS_AUTO_CLOSE_MS = 1500;
const AUTO_REPLY_RUN_POLLING_INTERVAL_MS = 4000;

type ConversationFilterKey = "all" | "manual_required" | "high_intent" | "retained_contact" | "follow_up";
type ChatAssistMode = "ai_auto_reply" | "manual_takeover";
type AutoReplyRunViewItem = AiAutoReplyRunListItem & Pick<Partial<AiAutoReplyRunDetail>, "would_send_content">;

const CONVERSATION_FILTERS: Array<{ key: ConversationFilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "manual_required", label: "需人工" },
  { key: "high_intent", label: "高意向" },
  { key: "retained_contact", label: "已留资" },
  { key: "follow_up", label: "待回访" },
];

const LIVE_CHECK_DISABLED_MESSAGE =
  "抖音授权联调未开启，请在后端设置 DY_LIVE_CHECK_ENABLED=true 后重启服务。";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function liveCheckErrorMessage(err: unknown): string {
  if (!isRecord(err)) return "无法连接 9000 授权服务，请确认主后端已启动。";
  const response = isRecord(err.response) ? err.response : null;
  const status = typeof response?.status === "number" ? response.status : undefined;
  const data = response && isRecord(response.data) ? response.data : null;
  const rawDetail = data?.detail;
  const detail =
    typeof rawDetail === "string"
      ? rawDetail
      : isRecord(rawDetail)
        ? JSON.stringify(rawDetail)
        : "";

  if (status === 403 && detail.toLowerCase().includes("disabled")) {
    return LIVE_CHECK_DISABLED_MESSAGE;
  }
  if (status === 400 && detail) {
    return `抖音授权信息不完整：${detail}`;
  }
  if (status === 502 && detail) {
    return `抖音授权上游接口失败：${detail}`;
  }
  if (status) {
    return `抖音授权接口请求失败，HTTP ${status}`;
  }
  return "无法连接 9000 授权服务，请确认主后端已启动。";
}

function formatTime(value?: string | null) {
  return formatDateTimeLocal(value);
}

function timeValue(value?: string | null) {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function conversationCacheKey(accountOpenId: string | null | undefined, conversationId: string | number | null | undefined) {
  if (!accountOpenId || conversationId === null || conversationId === undefined) return "";
  return `${accountOpenId}::${String(conversationId)}`;
}

function conversationWatermark(conversation: DouyinConversationItem | null | undefined) {
  if (!conversation) return "";
  return [
    conversation.last_message_at || "",
    conversation.last_message || "",
    conversation.conversation_short_id || "",
    conversation.conversation_key || "",
  ].join("|");
}

type ConversationReadWatermark = {
  readAt: number;
  lastMessageAt: string | null;
  lastMessageWatermark: string;
  unreadCount: number;
};

function applyReadWatermarks(
  accountOpenId: string,
  items: DouyinConversationItem[],
  readWatermarks: Record<string, ConversationReadWatermark>,
) {
  return items.map((item) => {
    const key = conversationCacheKey(accountOpenId, item.id);
    const read = key ? readWatermarks[key] : undefined;
    if (!read) return item;
    const itemTime = timeValue(item.last_message_at);
    const readTime = timeValue(read.lastMessageAt);
    const sameWatermark = conversationWatermark(item) === read.lastMessageWatermark;
    if (sameWatermark || itemTime <= readTime) {
      return { ...item, unread_count: 0 };
    }
    return item;
  });
}

function accountUnreadFromConversations(accountOpenId: string, items: DouyinConversationItem[]) {
  return items
    .filter((item) => (item.account_open_id || accountOpenId) === accountOpenId)
    .reduce((sum, item) => sum + Number(item.unread_count || 0), 0);
}

function statusText(value?: string | null) {
  if (value === "active") return "在线";
  if (value === "pending") return "新线索";
  if (value === "assigned") return "跟进中";
  if (value === "replied") return "已回复";
  if (value === "timeout") return "已失效";
  if (value === "closed") return "已成交";
  if (value === "captured") return "已留资";
  if (value === "new") return "新会话";
  return value || "未知";
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="grid min-h-[180px] place-items-center px-6 text-center text-xs text-slate-500">
      {text}
    </div>
  );
}

function conversationTagText(tag: string) {
  if (tag === "manual_required") return "需人工";
  if (tag === "high_intent") return "高意向";
  if (tag === "retained_contact") return "已留资";
  if (tag === "follow_up") return "待回访";
  if (tag === "need_followup") return "待回访";
  if (tag === "captured" || tag === "captured_lead" || tag === "has_lead" || tag === "lead_captured") return "已留资";
  return tag;
}

const LEAD_CAPTURE_TAG_VALUES = new Set([
  "retained_contact",
  "captured_lead",
  "captured",
  "has_lead",
  "lead_captured",
  "已留资",
]);

const STATUS_DUPLICATE_TAG_VALUES = new Set([
  "待跟进",
  "已留资",
  "高意向",
  "需人工",
  "pending",
  "follow_up",
  "need_followup",
  "retained_contact",
  "captured_lead",
  "captured",
  "has_lead",
  "lead_captured",
  "manual_required",
  "high_intent",
]);

function isLeadCaptureTag(tag?: string | null) {
  const value = String(tag || "").trim();
  return LEAD_CAPTURE_TAG_VALUES.has(value);
}

function isStatusDuplicateTag(tag?: string | null, leadStatus?: string | null) {
  const value = String(tag || "").trim();
  if (!value) return true;
  if (isLeadCaptureTag(value)) return isCapturedLeadStatus(leadStatus);
  if (value === "pending") return true;
  if (!STATUS_DUPLICATE_TAG_VALUES.has(value)) return false;
  const tagText = conversationTagText(value);
  const status = statusText(leadStatus);
  return tagText === status || value === leadStatus;
}

function visibleConversationTags(tags?: string[] | null, leadStatus?: string | null) {
  const result: string[] = [];
  const seen = new Set<string>();
  (tags || []).forEach((tag) => {
    const value = String(tag || "").trim();
    if (!value || isStatusDuplicateTag(value, leadStatus)) return;
    const label = conversationTagText(value);
    if (seen.has(label)) return;
    seen.add(label);
    result.push(value);
  });
  return result;
}

function isCapturedLeadStatus(value?: string | null) {
  const normalized = String(value || "").trim();
  return normalized === "captured" || normalized === "已留资";
}

const CONVERSATION_FILTER_TAG_VALUES: Record<Exclude<ConversationFilterKey, "all">, Set<string>> = {
  manual_required: new Set(["manual_required", "need_human", "需人工"]),
  high_intent: new Set(["high_intent", "高意向"]),
  retained_contact: LEAD_CAPTURE_TAG_VALUES,
  follow_up: new Set(["follow_up", "need_followup", "待回访"]),
};

function conversationMatchesFilter(conversation: DouyinConversationItem, filter: ConversationFilterKey) {
  if (filter === "all") return true;
  if (filter === "retained_contact" && isCapturedLeadStatus(conversation.lead_status)) return true;
  const values = CONVERSATION_FILTER_TAG_VALUES[filter];
  return (conversation.tags || []).some((tag) => values.has(String(tag || "").trim()));
}

function conversationLeadStatusForList(
  conversation: DouyinConversationItem,
  accountOpenId: string | null | undefined,
  profileCache: Record<string, DouyinConversationProfile | null>,
) {
  const cacheKey = conversationCacheKey(accountOpenId || conversation.account_open_id, conversation.id);
  const cachedProfile = cacheKey ? profileCache[cacheKey] : null;
  return cachedProfile?.lead?.status || conversation.lead_status || null;
}

function isCustomerMessage(message: DouyinMessageItem) {
  return (
    message.direction === "inbound" ||
    message.sender_type === "customer" ||
    message.sender_type === "user" ||
    message.message_type === "customer" ||
    message.message_type === "user"
  );
}

function isManualMessage(message: DouyinMessageItem) {
  return (
    message.direction === "outbound" ||
    message.sender_type === "staff" ||
    message.sender_type === "manual" ||
    message.message_type === "im_send_msg" ||
    message.message_type === "manual"
  );
}

function isAiAutoReplyMessage(message: DouyinMessageItem) {
  return (
    message.send_source === "ai_auto" ||
    message.operator_id === "ai_auto_reply" ||
    message.auto_send === true ||
    message.auto_send === 1 ||
    Boolean(message.auto_reply_run_id)
  );
}

function messageRoleLabel(message: DouyinMessageItem) {
  if (isCustomerMessage(message)) return "客户";
  if (isAiAutoReplyMessage(message)) return "AI 自动回复";
  if (isManualMessage(message)) return "人工客服";
  return "系统";
}

function messageLayoutClass(message: DouyinMessageItem) {
  if (isCustomerMessage(message)) return "justify-start";
  if (isManualMessage(message)) return "justify-end";
  return "justify-center";
}

function messageBubbleClass(message: DouyinMessageItem) {
  if (isCustomerMessage(message)) return "bg-white text-slate-800";
  if (isManualMessage(message)) return "bg-blue-600 text-white";
  return "max-w-[82%] border border-slate-200 bg-slate-100 text-slate-500 shadow-none";
}

function messageMetaClass(message: DouyinMessageItem) {
  if (isManualMessage(message)) return "text-blue-100";
  return "text-slate-400";
}

function chatModeTitle(mode: ChatAssistMode, enabled: boolean) {
  if (!enabled) return "AI 自动回复未开启。";
  return mode === "manual_takeover"
    ? "人工接管中，AI 不会自动回复。"
    : "AI 自动回复已开启，客户新消息将由 AI 自动回复。";
}

function chatModeSubtitle(mode: ChatAssistMode) {
  return mode === "manual_takeover"
    ? "人工接管后可手动发送消息。"
    : "如需人工发送请先切换到人工接管。";
}

function conversationAutopilotText(state: DouyinConversationAutopilotState | null) {
  if (!state) return "";
  if (state.mode === "manual") {
    return "人工接管中，AI 不会自动回复。";
  }
  return "";
}

function chatModeFromAccountMode(mode?: DouyinAutoReplyMode | null): ChatAssistMode {
  return mode === "ai_auto" ? "ai_auto_reply" : "manual_takeover";
}

function accountModeFromChatMode(mode: ChatAssistMode): DouyinAutoReplyMode {
  return mode === "ai_auto_reply" ? "ai_auto" : "manual_takeover";
}

function profileFieldText(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "暂无";
  return String(value);
}

function onlineStatusText(value?: string | null) {
  if (value === "online") return "在线";
  if (value === "offline") return "离线";
  if (value === "unknown") return "状态未知";
  return value || "状态未知";
}

function clampLeadScore(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Math.max(0, Math.min(100, Math.round(Number(value))));
}

function compactOpenId(value?: string | null) {
  if (!value) return "-";
  if (value.length <= 18) return value;
  return `${value.slice(0, 8)}...${value.slice(-6)}`;
}

function accountIdentityText(account: DouyinAccountItem): string {
  return account.account_open_id ? `账号标识 ${compactOpenId(account.account_open_id)}` : "账号标识 -";
}

function profileTagsText(profile: DouyinConversationProfile | null, fallback?: string[] | null) {
  const tags = (profile?.tags?.length ? profile.tags : fallback || []).filter(Boolean);
  if (!tags.length) return [];
  return tags.map((tag) => conversationTagText(tag));
}

function traceItems(profile: DouyinConversationProfile | null) {
  if (!profile?.trace) return [];
  return [
    ["事件键", profile.trace.event_key],
    ["会话短 ID", profile.trace.conversation_short_id],
    ["消息 ID", profile.trace.server_message_id],
    ["来源", profile.trace.source],
    ["时间", formatTime(profile.trace.created_at)],
  ].filter((item): item is [string, string] => Boolean(item[1]));
}

function ErrorBanner({ message, onRetry }: { message: string | null; onRetry?: () => void }) {
  if (!message) return null;
  return (
    <div className="mx-4 mt-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
      <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
      <span>{message}</span>
      {onRetry ? (
        <button onClick={onRetry} className="ml-auto inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-amber-300 bg-white px-3 text-[11px] font-semibold text-amber-800 hover:bg-amber-50">
          <RefreshCwIcon size={12} />
          重试
        </button>
      ) : null}
    </div>
  );
}

function autoReplyRunReasonText(run: AutoReplyRunViewItem | null) {
  const reason = run?.block_reason || run?.skip_reason || run?.error_message || "";
  const key = `${run?.status || ""}:${reason}`;
  const exact: Record<string, string> = {
    "send_skipped:manual_takeover_blocked": "未发送：当前会话处于人工接管",
    "send_skipped:manual_takeover": "未发送：当前会话处于人工接管",
    "send_skipped:autoreply_disabled": "未发送：AI 自动回复未开启",
    "send_skipped:agent_not_bound": "未发送：企业号未绑定智能体",
    "send_skipped:no_bound_agent": "未发送：企业号未绑定智能体",
    "send_skipped:send_context_unavailable": "未发送：发送上下文不可用",
    "send_skipped:upstream_send_failed": "未发送：抖音接口发送失败",
    "send_skipped:douyin_api_error": "未发送：抖音接口发送失败",
    "send_skipped:send_msg_failed": "未发送：抖音接口发送失败",
    "blocked:manual_takeover": "未发送：当前会话处于人工接管",
    "blocked:manual_takeover_blocked": "未发送：当前会话处于人工接管",
    "blocked:autoreply_disabled": "未发送：AI 自动回复未开启",
    "blocked:agent_not_bound": "未发送：企业号未绑定智能体",
    "blocked:no_bound_agent": "未发送：企业号未绑定智能体",
    "failed:send_context_unavailable": "未发送：发送上下文不可用",
    "failed:upstream_send_failed": "未发送：抖音接口发送失败",
    "failed:douyin_api_error": "未发送：抖音接口发送失败",
    "failed:send_msg_failed": "未发送：抖音接口发送失败",
    "send_failed:upstream_send_failed": "未发送：抖音接口发送失败",
    "send_failed:douyin_api_error": "未发送：抖音接口发送失败",
    "send_failed:send_msg_failed": "未发送：抖音接口发送失败",
    "skipped:autoreply_disabled": "未发送：AI 自动回复未开启",
  };
  if (exact[key]) return exact[key];
  if (reason === "manual_takeover" || reason === "manual_takeover_blocked") return "未发送：当前会话处于人工接管";
  if (reason === "autoreply_disabled") return "未发送：AI 自动回复未开启";
  if (reason === "agent_not_bound" || reason === "no_bound_agent") return "未发送：企业号未绑定智能体";
  if (reason === "send_context_unavailable") return "未发送：发送上下文不可用";
  if (reason === "upstream_send_failed" || reason === "douyin_api_error" || reason === "send_msg_failed") {
    return "未发送：抖音接口发送失败";
  }
  if (reason) return "未发送：发送上下文不可用";
  if (run?.status === "send_skipped" || run?.status === "blocked" || run?.status === "skipped") return "未发送：发送上下文不可用";
  if (run?.status === "failed" || run?.status === "send_failed") return "未发送：抖音接口发送失败";
  if (run?.status === "sent") return "AI 已自动回复";
  if (run?.status === "decided") return "未发送：发送上下文不可用";
  return "暂无自动回复运行结果。";
}

function isSameConversationAutopilotState(
  prev: DouyinConversationAutopilotState | null,
  next: DouyinConversationAutopilotState | null,
) {
  if (!prev && !next) return true;
  if (!prev || !next) return false;
  return (
    prev.mode === next.mode &&
    prev.manual_takeover_until === next.manual_takeover_until &&
    prev.last_human_message_at === next.last_human_message_at &&
    prev.updated_at === next.updated_at
  );
}

function autoReplyRunTitle(run: AutoReplyRunViewItem | null) {
  if (!run) return "AI 自动回复状态：暂无记录";
  if (run.status === "send_skipped" && (run.would_send_content_summary || run.reply_text)) {
    return "AI 自动回复未发送";
  }
  if (run.status === "blocked" || run.status === "skipped") return "AI 自动回复未发送";
  if (run.status === "failed" || run.status === "send_failed") return "AI 自动回复未发送";
  if (run.status === "sent") return "AI 已自动回复";
  if (run.status === "decided") return "AI 已生成回复";
  return "AI 自动回复状态";
}

function autoReplyGeneratedContent(run: AutoReplyRunViewItem | null) {
  return run?.would_send_content || run?.would_send_content_summary || run?.reply_text || "";
}

function shouldShowAutoReplyRunReason(run: AutoReplyRunViewItem | null, hasError: boolean) {
  if (hasError) return true;
  return Boolean(run && run.status !== "sent");
}

function visibleAutoReplyGeneratedContent(run: AutoReplyRunViewItem | null) {
  if (run?.status === "sent") return "";
  return autoReplyGeneratedContent(run);
}

function autoReplyRunCacheKey(accountOpenId?: string | null, conversationShortId?: string | number | null) {
  if (!accountOpenId || conversationShortId === undefined || conversationShortId === null) return null;
  const conversationKey = String(conversationShortId).trim();
  return conversationKey ? `${accountOpenId}:${conversationKey}` : null;
}

function isSameAutoReplyRun(prev: AutoReplyRunViewItem | null, next: AutoReplyRunViewItem | null) {
  if (!prev && !next) return true;
  if (!prev || !next) return false;
  return (
    prev.id === next.id &&
    prev.status === next.status &&
    prev.skip_reason === next.skip_reason &&
    prev.block_reason === next.block_reason &&
    prev.decision_log_id === next.decision_log_id &&
    prev.would_send_content_summary === next.would_send_content_summary &&
    prev.would_send_content === next.would_send_content &&
    prev.upstream_auto_send === next.upstream_auto_send &&
    prev.final_auto_send === next.final_auto_send &&
    prev.decision_version === next.decision_version &&
    prev.error_message === next.error_message &&
    prev.updated_at === next.updated_at
  );
}

function shouldLoadAutoReplyRunDetail(
  latestRun: AutoReplyRunViewItem | null,
  cachedRun: AutoReplyRunViewItem | null | undefined,
) {
  if (!latestRun?.id || !latestRun.would_send_content_summary) return false;
  return !(
    cachedRun?.id === latestRun.id &&
    cachedRun.updated_at === latestRun.updated_at &&
    Boolean(cachedRun.would_send_content)
  );
}

function shouldShowAutoReplyRunCard(run: AutoReplyRunViewItem | null, loading: boolean, error: string | null) {
  return loading || Boolean(error) || Boolean(run);
}

type MediaDownloadState = {
  loading?: boolean;
  downloadUrl?: string;
  error?: string;
  copied?: boolean;
};

type UploadedImageData = NonNullable<UploadDouyinImageResponse["data"]>;

function mediaTypeForDownload(message: DouyinMessageItem): "image" | "video" | null {
  const value = String(message.media_type || message.message_type || "").toLowerCase();
  if (value === "image" || value === "user_local_image") return "image";
  if (value === "video" || value === "user_local_video") return "video";
  return null;
}

function resourceMissingText(reason?: string | null): string {
  if (reason === "resource_url_not_found") {
    return "暂无资源链接";
  }
  return "暂无资源链接";
}

function downloadErrorMessage(err: unknown): string {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return "资源下载失败，请稍后重试";
}

function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function fileExtension(fileName: string): string {
  const index = fileName.lastIndexOf(".");
  return index >= 0 ? fileName.slice(index).toLowerCase() : "";
}

function validateUploadImageFile(file: File | null): string | null {
  if (!file) {
    return "请选择要上传的图片文件";
  }
  const extension = fileExtension(file.name);
  const mimeAllowed = file.type ? ALLOWED_UPLOAD_IMAGE_MIME_TYPES.includes(file.type) : false;
  const extensionAllowed = ALLOWED_UPLOAD_IMAGE_EXTENSIONS.includes(extension);
  if (!mimeAllowed && !extensionAllowed) {
    return UPLOAD_IMAGE_VALIDATION_MESSAGE;
  }
  if (extension === ".svg" || extension === ".gif" || file.type === "image/svg+xml" || file.type === "image/gif") {
    return UPLOAD_IMAGE_VALIDATION_MESSAGE;
  }
  if (file.size > MAX_UPLOAD_IMAGE_BYTES) {
    return UPLOAD_IMAGE_VALIDATION_MESSAGE;
  }
  return null;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
        return;
      }
      reject(new Error("图片读取失败，请重新选择文件"));
    };
    reader.onerror = () => reject(new Error("图片读取失败，请重新选择文件"));
    reader.readAsDataURL(file);
  });
}

function uploadImageResponseMessage(response: UploadDouyinImageResponse): string {
  const detail = response.detail;
  if (detail && typeof detail === "object" && typeof detail.safe_message === "string") {
    return detail.safe_message;
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (response.error?.safe_message) {
    return response.error.safe_message;
  }
  if (response.error?.message) {
    return response.error.message;
  }
  return response.message || "图片上传失败，请稍后重试";
}

function authorizationStatusText(value?: string | null): string {
  if (value === "authorized") return "已授权";
  if (value === "unauthorized") return "未授权";
  if (value === "deleted") return "已删除";
  if (value === "invalid") return "已失效";
  return value || "未知";
}

function hasActiveAgentBinding(account: DouyinAccountItem | null): boolean {
  return Boolean(
    account?.bound_agent_id &&
      account.bound_agent_status === "active" &&
      account.binding_status === "active" &&
      account.authorization_status === "authorized",
  );
}

function searchParamText(params: URLSearchParams, key: string): string | null {
  const value = params.get(key);
  return value && value.trim() ? value.trim() : null;
}

function readConversationJumpParams(): {
  accountOpenId: string;
  conversationShortId: string;
  openId: string;
} | null {
  const params = new URLSearchParams(window.location.search);
  const accountOpenId = searchParamText(params, "account_open_id");
  const conversationShortId = searchParamText(params, "conversation_short_id");
  const openId = searchParamText(params, "open_id");
  if (!accountOpenId || !conversationShortId || !openId) return null;
  return { accountOpenId, conversationShortId, openId };
}

/** 读取 auth-redirect 302 回跳携带的授权结果 query。 */
function readAuthRedirectParams(): {
  auth: string;
  openId: string;
  nickName: string | null;
  avatar: string | null;
} | null {
  const params = new URLSearchParams(window.location.search);
  const auth = searchParamText(params, "auth");
  const openId = searchParamText(params, "open_id");
  if (!auth || !openId) return null;
  return {
    auth,
    openId,
    nickName: searchParamText(params, "nick_name") || searchParamText(params, "nickname"),
    avatar: searchParamText(params, "avatar") || searchParamText(params, "avatar_url"),
  };
}

/** 从绑定接口的错误响应中提取错误码。 */
function extractBindErrorCode(err: unknown): string | null {
  if (!isRecord(err)) return null;
  const response = isRecord(err.response) ? err.response : null;
  const data = response && isRecord(response.data) ? response.data : null;
  const detail = data?.detail;
  if (isRecord(detail) && typeof detail.code === "string") return detail.code;
  return null;
}

/** 从绑定接口的错误响应中提取可读文案。 */
function extractBindErrorText(err: unknown): string {
  if (!isRecord(err)) return "绑定抖音号失败，请稍后重试。";
  const response = isRecord(err.response) ? err.response : null;
  const data = response && isRecord(response.data) ? response.data : null;
  const detail = data?.detail;
  if (isRecord(detail) && typeof detail.message === "string" && detail.message) return detail.message;
  if (typeof detail === "string" && detail) return detail;
  const status = typeof response?.status === "number" ? response.status : undefined;
  if (status) return `绑定抖音号失败，HTTP ${status}。`;
  return "绑定抖音号失败，请稍后重试。";
}

function conversationIdText(value: string | number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function matchDeepLinkedConversation(
  conversations: DouyinConversationItem[],
  params: { conversationShortId: string; openId: string },
): DouyinConversationItem | null {
  const candidates = conversations.filter((item) => {
    const matchesConversation =
      item.conversation_short_id === params.conversationShortId ||
      item.conversation_key === params.conversationShortId ||
      conversationIdText(item.id) === params.conversationShortId;
    const matchesCustomer =
      item.open_id === params.openId ||
      item.customer_open_id === params.openId;
    return matchesConversation && matchesCustomer;
  });
  return candidates.length === 1 ? candidates[0] : null;
}

export default function DouyinAiCsWorkbenchPage() {
  const [accounts, setAccounts] = useState<DouyinAccountItem[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<DouyinConversationItem[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | number | null>(null);
  const [messages, setMessages] = useState<DouyinMessageItem[]>([]);
  const [profile, setProfile] = useState<DouyinConversationProfile | null>(null);
  const [draftReplyText, setDraftReplyText] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [autoReplyRun, setAutoReplyRun] = useState<AutoReplyRunViewItem | null>(null);
  const [loadingAutoReplyRun, setLoadingAutoReplyRun] = useState(false);
  const [autoReplyRunError, setAutoReplyRunError] = useState<string | null>(null);
  const [autoReplyCopied, setAutoReplyCopied] = useState(false);
  const composingReplyRef = useRef(false);
  const [mediaDownloads, setMediaDownloads] = useState<Record<string, MediaDownloadState>>({});
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadedImageData | null>(null);
  // ponytail: 客户画像在窄桌面（<1500px）折叠为右侧抽屉，宽桌面（>=1500px）保持四栏内联；布局切换走 CSS，仅 open 状态走 JS
  const [profileDrawerOpen, setProfileDrawerOpen] = useState(false);
  const [uploadImageIdCopied, setUploadImageIdCopied] = useState(false);
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accountListSource, setAccountListSource] = useState<string | null>(null);
  const [conversationSearch, setConversationSearch] = useState("");
  const [conversationFilter, setConversationFilter] = useState<ConversationFilterKey>("all");
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authUrlInfo, setAuthUrlInfo] = useState<DouyinLiveCheckAuthUrlData | null>(null);
  const [authStatus, setAuthStatus] = useState<DouyinLiveCheckStatusData | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [authStatusLoading, setAuthStatusLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authFrameFailed, setAuthFrameFailed] = useState(false);
  const [authAccountRefreshDone, setAuthAccountRefreshDone] = useState(false);
  const [authPollingTimedOut, setAuthPollingTimedOut] = useState(false);
  const [chatAssistMode, setChatAssistMode] = useState<ChatAssistMode>("manual_takeover");
  const [loadingAccountMode, setLoadingAccountMode] = useState(false);
  const [savingAccountMode, setSavingAccountMode] = useState(false);
  const [accountModeError, setAccountModeError] = useState<string | null>(null);
  const [accountModeMessage, setAccountModeMessage] = useState<string | null>(null);
  const [conversationAutopilotState, setConversationAutopilotState] =
    useState<DouyinConversationAutopilotState | null>(null);
  const [loadingConversationAutopilot, setLoadingConversationAutopilot] = useState(false);
  const [conversationAutopilotError, setConversationAutopilotError] = useState<string | null>(null);
  const [agentConfigAccount, setAgentConfigAccount] = useState<DouyinAccountItem | null>(null);
  const [agentOptions, setAgentOptions] = useState<DouyinAgentItem[]>([]);
  const [selectedAgentIdForConfig, setSelectedAgentIdForConfig] = useState<string>("");
  const [loadingAgentConfig, setLoadingAgentConfig] = useState(false);
  const [savingAgentConfig, setSavingAgentConfig] = useState(false);
  const [agentConfigError, setAgentConfigError] = useState<string | null>(null);
  const [conversationJumpParams] = useState(() => readConversationJumpParams());
  const [conversationJumpHandled, setConversationJumpHandled] = useState(false);
  // auth-redirect 302 回跳（?auth=success&open_id=xxx）触发的自动绑定状态
  const [authRedirectParams] = useState(() => readAuthRedirectParams());
  const [authRedirectBinding, setAuthRedirectBinding] = useState(false);
  const [authRedirectMessage, setAuthRedirectMessage] = useState<{
    text: string;
    tone: "success" | "error";
  } | null>(null);
  const [authRedirectHandled, setAuthRedirectHandled] = useState(false);
  const conversationsCacheRef = useRef<Record<string, DouyinConversationItem[]>>({});
  const messagesCacheRef = useRef<Record<string, DouyinMessageItem[]>>({});
  const profileCacheRef = useRef<Record<string, DouyinConversationProfile | null>>({});
  const readWatermarksRef = useRef<Record<string, ConversationReadWatermark>>({});
  const markReadWatermarksRef = useRef<Record<string, string>>({});
  const selectedAccountOpenIdRef = useRef<string | null>(null);
  const selectedConversationIdRef = useRef<string | number | null>(null);
  const accountModeCacheRef = useRef<Record<string, ChatAssistMode>>({});
  const accountRequestSeqRef = useRef(0);
  const conversationRequestSeqRef = useRef(0);
  const detailRequestSeqRef = useRef(0);
  const autoReplyRunRequestSeqRef = useRef(0);
  const autoReplyRunCacheRef = useRef<Record<string, AutoReplyRunViewItem | null>>({});
  const autoReplyRunActiveKeyRef = useRef<string | null>(null);
  const conversationAutopilotCacheRef = useRef<Record<string, DouyinConversationAutopilotState | null>>({});
  const conversationAutopilotActiveKeyRef = useRef<string | null>(null);
  const conversationAutopilotRequestSeqRef = useRef(0);
  const accountModeRequestSeqRef = useRef(0);
  const conversationAbortRef = useRef<AbortController | null>(null);
  const detailAbortRef = useRef<AbortController | null>(null);
  const conversationInFlightRef = useRef<Record<string, Promise<DouyinConversationItem[]>>>({});
  const messageInFlightRef = useRef<Record<string, Promise<DouyinMessageItem[]>>>({});
  const profileInFlightRef = useRef<Record<string, Promise<DouyinConversationProfile | null>>>({});
  const pollInFlightRef = useRef(false);
  const autoReplyRunPollInFlightRef = useRef(false);
  const authPollingStartedAtRef = useRef<number>(0);
  const authAutoCloseTimerRef = useRef<number | null>(null);

  const selectedAccount = accounts.find((item) => item.id === selectedAccountId) || null;
  const selectedConversation =
    conversations.find((item) => item.id === selectedConversationId) || null;
  const activeBindingReady = hasActiveAgentBinding(selectedAccount);
  const effectiveChatAssistMode: ChatAssistMode = activeBindingReady ? chatAssistMode : "manual_takeover";
  const authPolling = authStatus?.auth_polling || null;
  const authCallback = authStatus?.last_oauth_callback || null;
  const authOpenId = authPolling ? authPolling.open_id : authCallback?.open_id || null;
  const authNickname = authPolling ? authPolling.nickname : authCallback?.nick_name || null;
  const authReceivedAt = authPolling ? authPolling.received_at : authCallback?.received_at || null;
  const authAuthorized = authPolling ? authPolling.status === "authorized" : Boolean(authOpenId);
  const authStatusText = authPollingTimedOut
    ? "授权超时"
    : authPolling?.status === "failed" || authCallback?.error
      ? "授权失败"
      : authAuthorized
        ? "授权成功"
        : "授权中";
  useEffect(() => {
    selectedAccountOpenIdRef.current = selectedAccount?.account_open_id || null;
  }, [selectedAccount?.account_open_id]);

  useEffect(() => {
    const accountOpenId = selectedAccount?.account_open_id || null;
    const requestSeq = accountModeRequestSeqRef.current + 1;
    accountModeRequestSeqRef.current = requestSeq;
    setAccountModeError(null);
    if (!accountOpenId) {
      setChatAssistMode("manual_takeover");
      setLoadingAccountMode(false);
      return;
    }
    const cachedMode = accountModeCacheRef.current[accountOpenId];
    if (cachedMode) setChatAssistMode(cachedMode);
    setLoadingAccountMode(!cachedMode);

    void getDouyinAutoReplySetting(accountOpenId)
      .then((setting) => {
        if (
          accountModeRequestSeqRef.current !== requestSeq ||
          selectedAccountOpenIdRef.current !== accountOpenId
        ) {
          return;
        }
        const nextMode = chatModeFromAccountMode(setting.mode);
        accountModeCacheRef.current[accountOpenId] = nextMode;
        setChatAssistMode(nextMode);
      })
      .catch((err) => {
        if (
          accountModeRequestSeqRef.current !== requestSeq ||
          selectedAccountOpenIdRef.current !== accountOpenId
        ) {
          return;
        }
        setAccountModeError(err instanceof Error ? err.message : "企业号托管模式加载失败");
        if (!cachedMode) setChatAssistMode("manual_takeover");
      })
      .finally(() => {
        if (
          accountModeRequestSeqRef.current === requestSeq &&
          selectedAccountOpenIdRef.current === accountOpenId
        ) {
          setLoadingAccountMode(false);
        }
      });
  }, [selectedAccount?.account_open_id]);

  useEffect(() => {
    selectedConversationIdRef.current = selectedConversationId;
  }, [selectedConversationId]);

  useEffect(() => {
    return () => {
      conversationAbortRef.current?.abort();
      detailAbortRef.current?.abort();
    };
  }, []);

  const filteredConversations = useMemo(() => {
    const keyword = conversationSearch.trim().toLowerCase();
    return conversations.filter((conversation) => {
      const matchesKeyword =
        !keyword ||
        [
          conversation.nickname,
          conversation.last_message,
          conversation.open_id,
          conversation.lead_status || "",
        ]
          .join(" ")
          .toLowerCase()
          .includes(keyword);
      return matchesKeyword && conversationMatchesFilter(conversation, conversationFilter);
    });
  }, [conversationFilter, conversationSearch, conversations]);
  const profileNickname = profile?.nickname || selectedConversation?.nickname || selectedConversation?.open_id || "未知客户";
  const profileAvatar = profile?.avatar || selectedConversation?.avatar || null;
  const profileOpenId = profile?.open_id || selectedConversation?.open_id || null;
  const profileTags = profileTagsText(profile, selectedConversation?.tags);
  const profileLeadScore = clampLeadScore(profile?.lead_score);
  const profileTraceItems = traceItems(profile);
  const profileSummary = profile
    ? [
        profile.intent_car ? `意向 ${profile.intent_car}` : null,
        profile.budget ? `预算 ${profile.budget}` : null,
        onlineStatusText(profile.online_status),
      ].filter(Boolean).join(" / ")
    : loadingProfile
      ? "客户画像加载中"
      : "暂无客户画像";

  const loadAccounts = useCallback(async (preferredOpenId?: string | null) => {
    const requestSeq = accountRequestSeqRef.current + 1;
    accountRequestSeqRef.current = requestSeq;
    setLoadingAccounts(true);
    setError(null);
    try {
      const data = await listDouyinAccounts();
      if (accountRequestSeqRef.current !== requestSeq) return data.items;
      const mapped = data.items;
      setAccounts(mapped);
      setAccountListSource("official_bindings");
      setSelectedAccountId((current) => {
        const preferred = preferredOpenId
          ? mapped.find((item) => item.account_open_id === preferredOpenId)
          : null;
        if (preferred) return preferred.id;
        if (current && mapped.some((item) => item.id === current)) return current;
        return mapped[0]?.id || null;
      });
      return mapped;
    } catch (err) {
      if (accountRequestSeqRef.current !== requestSeq) return [];
      setAccounts([]);
      setSelectedAccountId(null);
      setAccountListSource(null);
      setError(err instanceof Error ? err.message : "抖音企业号列表加载失败");
      return [];
    } finally {
      if (accountRequestSeqRef.current === requestSeq) setLoadingAccounts(false);
    }
  }, []);

  const loadConversations = useCallback(async (
    account: DouyinAccountItem,
    options?: { skipDefaultSelection?: boolean; background?: boolean },
  ) => {
    const accountOpenId = account.account_open_id;
    const cached = conversationsCacheRef.current[accountOpenId];
    const hasCached = Boolean(cached);
    const requestSeq = conversationRequestSeqRef.current + 1;
    conversationRequestSeqRef.current = requestSeq;
    if (hasCached && !options?.background) {
      setConversations(cached);
    }
    if (!options?.background && !hasCached) setLoadingConversations(true);
    setError(null);
    if (!options?.background) {
      conversationAbortRef.current?.abort();
      conversationInFlightRef.current = {};
    }
    const controller = new AbortController();
    conversationAbortRef.current = controller;
    const inflightKey = accountOpenId;
    try {
      const request =
        conversationInFlightRef.current[inflightKey] ||
        getDouyinAccountConversations(account.id, {
          account_open_id: accountOpenId,
          signal: controller.signal,
        })
          .then((data) => data.items)
          .finally(() => {
            delete conversationInFlightRef.current[inflightKey];
          });
      conversationInFlightRef.current[inflightKey] = request;
      const items = await request;
      if (
        conversationRequestSeqRef.current !== requestSeq ||
        selectedAccountOpenIdRef.current !== accountOpenId
      ) {
        return items;
      }
      const mergedItems = applyReadWatermarks(accountOpenId, items, readWatermarksRef.current);
      conversationsCacheRef.current[accountOpenId] = mergedItems;
      setConversations(mergedItems);
      setAccounts((current) =>
        current.map((item) =>
          item.account_open_id === accountOpenId
            ? { ...item, unread_count: accountUnreadFromConversations(accountOpenId, mergedItems) }
            : item,
        ),
      );
      if (!options?.skipDefaultSelection) {
        setSelectedConversationId((current) => {
          if (current && mergedItems.some((item) => item.id === current)) return current;
          return mergedItems[0]?.id || null;
        });
      }
      return mergedItems;
    } catch (err) {
      if (controller.signal.aborted) return cached || [];
      if (
        conversationRequestSeqRef.current !== requestSeq ||
        selectedAccountOpenIdRef.current !== accountOpenId
      ) {
        return [];
      }
      if (!hasCached) {
        setConversations([]);
        setSelectedConversationId(null);
      }
      setError(err instanceof Error ? err.message : "会话列表加载失败");
      return [];
    } finally {
      if (conversationRequestSeqRef.current === requestSeq && selectedAccountOpenIdRef.current === accountOpenId) {
        setLoadingConversations(false);
      }
    }
  }, []);

  const loadConversationDetail = useCallback(async (
    conversationId: string | number,
    options?: { background?: boolean },
  ) => {
    const accountOpenId = selectedAccount?.account_open_id || null;
    const accountId = selectedAccount?.id || null;
    const cacheKey = conversationCacheKey(accountOpenId, conversationId);
    const cachedMessages = cacheKey ? messagesCacheRef.current[cacheKey] : undefined;
    const cachedProfile = cacheKey ? profileCacheRef.current[cacheKey] : undefined;
    const requestSeq = detailRequestSeqRef.current + 1;
    detailRequestSeqRef.current = requestSeq;
    if (cachedMessages && !options?.background) setMessages(cachedMessages);
    if (cachedProfile !== undefined && !options?.background) setProfile(cachedProfile);
    if (!options?.background && !cachedMessages) setLoadingMessages(true);
    if (!options?.background && cachedProfile === undefined) setLoadingProfile(true);
    setError(null);
    setProfileError(null);
    if (!options?.background) {
      detailAbortRef.current?.abort();
      messageInFlightRef.current = {};
      profileInFlightRef.current = {};
    }
    const controller = new AbortController();
    detailAbortRef.current = controller;
    const isCurrentRequest = () =>
      detailRequestSeqRef.current === requestSeq &&
      selectedAccountOpenIdRef.current === accountOpenId &&
      selectedConversationIdRef.current === conversationId;
    const messageKey = cacheKey ? `message::${cacheKey}` : "";
    const profileKey = cacheKey ? `profile::${cacheKey}` : "";

    const messageRequest =
      (messageKey && messageInFlightRef.current[messageKey]) ||
      getDouyinConversationMessages(conversationId, {
        account_open_id: accountOpenId || undefined,
        signal: controller.signal,
      })
        .then((data) => data.items)
        .finally(() => {
          if (messageKey) delete messageInFlightRef.current[messageKey];
        });
    if (messageKey) messageInFlightRef.current[messageKey] = messageRequest;

    const profileRequest =
      accountId === null || cachedProfile !== undefined
        ? Promise.resolve(cachedProfile ?? null)
        : (profileKey && profileInFlightRef.current[profileKey]) ||
          getDouyinConversationProfileFrom9000(accountId, conversationId, {
            account_open_id: accountOpenId || undefined,
            signal: controller.signal,
          })
            .then((data) => data)
            .finally(() => {
              if (profileKey) delete profileInFlightRef.current[profileKey];
            });
    if (profileKey) profileInFlightRef.current[profileKey] = profileRequest;

    const messageTask = messageRequest
      .then((items) => {
      if (
        !isCurrentRequest()
      ) {
        return;
      }
      if (cacheKey) messagesCacheRef.current[cacheKey] = items;
      setMessages(items);
    })
      .catch((err) => {
        if (controller.signal.aborted || !isCurrentRequest()) return;
        if (!cachedMessages) setMessages([]);
        setError(err instanceof Error ? err.message : "聊天详情加载失败");
      })
      .finally(() => {
        if (isCurrentRequest()) setLoadingMessages(false);
      });

    const profileTask = profileRequest
      .then((profileData) => {
        if (!isCurrentRequest()) return;
        if (cacheKey) profileCacheRef.current[cacheKey] = profileData;
        setProfile(profileData);
      })
      .catch((profileErr) => {
        if (controller.signal.aborted || !isCurrentRequest()) return;
        if (cacheKey) profileCacheRef.current[cacheKey] = null;
        setProfile(null);
        setProfileError(profileErr instanceof Error ? profileErr.message : "客户画像加载失败");
      })
      .finally(() => {
        if (isCurrentRequest()) setLoadingProfile(false);
      });

    await Promise.allSettled([messageTask, profileTask]);
  }, [selectedAccount]);

  const loadLatestAutoReplyRun = useCallback(async (
    conversation: DouyinConversationItem | null,
    account: DouyinAccountItem | null,
    options: { background?: boolean } = {},
  ) => {
    const requestSeq = autoReplyRunRequestSeqRef.current + 1;
    autoReplyRunRequestSeqRef.current = requestSeq;
    const background = Boolean(options.background);
    if (!conversation || !account?.account_open_id || !conversation.conversation_short_id) {
      setAutoReplyRun(null);
      setLoadingAutoReplyRun(false);
      setAutoReplyRunError(null);
      return;
    }
    const cacheKey = autoReplyRunCacheKey(account.account_open_id, conversation.conversation_short_id);
    const cachedRun = cacheKey ? autoReplyRunCacheRef.current[cacheKey] : undefined;
    if (!background) {
      setAutoReplyRunError(null);
      setAutoReplyCopied(false);
      if (cachedRun !== undefined) {
        setAutoReplyRun((current) => (isSameAutoReplyRun(current, cachedRun) ? current : cachedRun));
        setLoadingAutoReplyRun(false);
      } else {
        setLoadingAutoReplyRun(true);
      }
    }
    try {
      const data = await getAiAutoReplyRuns({
        account_open_id: account.account_open_id,
        conversation_short_id: String(conversation.conversation_short_id),
        page_size: 1,
      });
      if (
        autoReplyRunRequestSeqRef.current !== requestSeq ||
        selectedAccountOpenIdRef.current !== account.account_open_id ||
        selectedConversationIdRef.current !== conversation.id
      ) {
        return;
      }
      let latestRun: AutoReplyRunViewItem | null = data.items[0] || null;
      if (shouldLoadAutoReplyRunDetail(latestRun, cachedRun)) {
        try {
          const detail = await getAiAutoReplyRunDetail(latestRun.id);
          latestRun = {
            ...latestRun,
            would_send_content: detail.would_send_content,
          };
        } catch {
          // 详情加载失败不影响状态卡片展示，保留列表摘要。
        }
      } else if (
        latestRun &&
        cachedRun?.id === latestRun.id &&
        cachedRun.updated_at === latestRun.updated_at &&
        cachedRun.would_send_content
      ) {
        latestRun = {
          ...latestRun,
          would_send_content: cachedRun.would_send_content,
        };
      }
      if (cacheKey) {
        autoReplyRunCacheRef.current[cacheKey] = latestRun;
      }
      setAutoReplyRun((current) => (isSameAutoReplyRun(current, latestRun) ? current : latestRun));
      setAutoReplyRunError(null);
    } catch (err) {
      if (
        autoReplyRunRequestSeqRef.current !== requestSeq ||
        selectedAccountOpenIdRef.current !== account.account_open_id ||
        selectedConversationIdRef.current !== conversation.id
      ) {
        return;
      }
      setAutoReplyRunError(err instanceof Error ? err.message : "自动回复状态加载失败");
    } finally {
      if (
        autoReplyRunRequestSeqRef.current === requestSeq &&
        selectedAccountOpenIdRef.current === account.account_open_id &&
        selectedConversationIdRef.current === conversation.id
      ) {
        setLoadingAutoReplyRun(false);
      }
    }
  }, []);

  const loadConversationAutopilotState = useCallback(async (
    conversation: DouyinConversationItem | null,
    account: DouyinAccountItem | null,
    options: { background?: boolean } = {},
  ) => {
    const requestSeq = conversationAutopilotRequestSeqRef.current + 1;
    conversationAutopilotRequestSeqRef.current = requestSeq;
    const background = Boolean(options.background);
    if (!conversation || !account?.account_open_id || !conversation.conversation_short_id) {
      setConversationAutopilotState(null);
      setLoadingConversationAutopilot(false);
      return;
    }
    const cacheKey = conversationCacheKey(account.account_open_id, conversation.conversation_short_id);
    const cachedState = cacheKey ? conversationAutopilotCacheRef.current[cacheKey] : undefined;
    if (!background) {
      setConversationAutopilotError(null);
      if (cachedState !== undefined) {
        setConversationAutopilotState((current) =>
          isSameConversationAutopilotState(current, cachedState) ? current : cachedState,
        );
        setLoadingConversationAutopilot(false);
      } else {
        setConversationAutopilotState(null);
        setLoadingConversationAutopilot(true);
      }
    }
    try {
      const state = await getDouyinConversationAutopilot(
        account.account_open_id,
        conversation.conversation_short_id,
      );
      if (
        conversationAutopilotRequestSeqRef.current !== requestSeq ||
        selectedAccountOpenIdRef.current !== account.account_open_id ||
        selectedConversationIdRef.current !== conversation.id
      ) {
        return;
      }
      if (cacheKey) {
        conversationAutopilotCacheRef.current[cacheKey] = state;
      }
      setConversationAutopilotState((current) =>
        isSameConversationAutopilotState(current, state) ? current : state,
      );
      setConversationAutopilotError(null);
    } catch (err) {
      if (
        conversationAutopilotRequestSeqRef.current !== requestSeq ||
        selectedAccountOpenIdRef.current !== account.account_open_id ||
        selectedConversationIdRef.current !== conversation.id
      ) {
        return;
      }
      setConversationAutopilotError(err instanceof Error ? err.message : "会话托管状态加载失败");
    } finally {
      if (
        conversationAutopilotRequestSeqRef.current === requestSeq &&
        selectedAccountOpenIdRef.current === account.account_open_id &&
        selectedConversationIdRef.current === conversation.id
      ) {
        setLoadingConversationAutopilot(false);
      }
    }
  }, []);

  const markConversationReadLocally = useCallback((conversation: DouyinConversationItem) => {
    const accountOpenId = selectedAccount?.account_open_id || conversation.account_open_id;
    if (!accountOpenId) return;
    const cacheKey = conversationCacheKey(accountOpenId, conversation.id);
    if (!cacheKey) return;
    const unreadCount = Number(conversation.unread_count || 0);
    const watermark = conversationWatermark(conversation);
    const existing = readWatermarksRef.current[cacheKey];
    if (unreadCount <= 0 && existing?.lastMessageWatermark === watermark) return;
    readWatermarksRef.current[cacheKey] = {
      readAt: Date.now(),
      lastMessageAt: conversation.last_message_at || null,
      lastMessageWatermark: watermark,
      unreadCount,
    };
    setConversations((current) => {
      const next = current.map((item) => (item.id === conversation.id ? { ...item, unread_count: 0 } : item));
      conversationsCacheRef.current[accountOpenId] = next;
      return next;
    });
    if (unreadCount > 0) {
      setAccounts((current) =>
        current.map((item) =>
          item.account_open_id === accountOpenId
            ? { ...item, unread_count: Math.max(0, Number(item.unread_count || 0) - unreadCount) }
            : item,
        ),
      );
    }
  }, [selectedAccount?.account_open_id]);

  const persistConversationRead = useCallback(async (conversation: DouyinConversationItem) => {
    const accountOpenId = selectedAccount?.account_open_id || conversation.account_open_id;
    if (!accountOpenId) return;
    const cacheKey = conversationCacheKey(accountOpenId, conversation.id);
    if (!cacheKey) return;
    const watermark = conversationWatermark(conversation);
    if (markReadWatermarksRef.current[cacheKey] === watermark) return;
    markReadWatermarksRef.current[cacheKey] = watermark;
    try {
      await markDouyinConversationRead({
        account_open_id: accountOpenId,
        conversation_key: String(conversation.conversation_key || conversation.id),
        conversation_short_id: conversation.conversation_short_id || null,
        customer_open_id: conversation.customer_open_id || conversation.open_id || null,
      });
    } catch (err) {
      delete markReadWatermarksRef.current[cacheKey];
      console.warn("会话已读状态保存失败", err);
    }
  }, [selectedAccount?.account_open_id]);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    if (selectedAccount) {
      const cachedConversations = conversationsCacheRef.current[selectedAccount.account_open_id];
      if (cachedConversations) setConversations(cachedConversations);
      void loadConversations(selectedAccount, {
        skipDefaultSelection: Boolean(conversationJumpParams && !conversationJumpHandled),
        background: Boolean(cachedConversations),
      });
    } else {
      setConversations([]);
      setSelectedConversationId(null);
    }
  }, [conversationJumpHandled, conversationJumpParams, loadConversations, selectedAccount, selectedAccountId]);

  useEffect(() => {
    if (!selectedConversation || !selectedAccount?.account_open_id || loadingMessages || messages.length === 0) {
      return;
    }
    markConversationReadLocally(selectedConversation);
    void persistConversationRead(selectedConversation);
  }, [
    loadingMessages,
    markConversationReadLocally,
    messages.length,
    persistConversationRead,
    selectedAccount?.account_open_id,
    selectedConversation,
  ]);

  useEffect(() => {
    if (!conversationJumpParams || conversationJumpHandled || loadingAccounts) return;
    const account = accounts.find((item) => item.account_open_id === conversationJumpParams.accountOpenId);
    if (!account) {
      if (accounts.length) {
        setError("会话不属于当前账号或无权限访问");
        setSelectedConversationId(null);
        setConversationJumpHandled(true);
      }
      return;
    }

    let cancelled = false;
    async function locateConversation() {
      const items = await loadConversations(account, { skipDefaultSelection: true });
      if (cancelled) return;
      const matched = matchDeepLinkedConversation(items, conversationJumpParams);
      if (matched) {
        setSelectedAccountId(account.id);
        setConversationSearch("");
        setConversationFilter("all");
        setSelectedConversationId(matched.id);
      } else {
        setSelectedConversationId(null);
        setError("未找到匹配会话，请手动搜索客户");
      }
      setConversationJumpHandled(true);
    }

    void locateConversation();
    return () => {
      cancelled = true;
    };
  }, [accounts, conversationJumpHandled, conversationJumpParams, loadConversations, loadingAccounts]);

  useEffect(() => {
    if (selectedConversationId) {
      const target = conversations.find((item) => item.id === selectedConversationId);
      if (target) markConversationReadLocally(target);
      void loadConversationDetail(selectedConversationId);
      const nextAutoReplyKey = autoReplyRunCacheKey(
        selectedAccount?.account_open_id,
        target?.conversation_short_id,
      );
      const backgroundAutoReplyRefresh =
        Boolean(nextAutoReplyKey) && autoReplyRunActiveKeyRef.current === nextAutoReplyKey;
      autoReplyRunActiveKeyRef.current = nextAutoReplyKey;
      const nextAutopilotKey = conversationCacheKey(
        selectedAccount?.account_open_id,
        target?.conversation_short_id,
      );
      const backgroundAutopilotRefresh =
        Boolean(nextAutopilotKey) && conversationAutopilotActiveKeyRef.current === nextAutopilotKey;
      conversationAutopilotActiveKeyRef.current = nextAutopilotKey || null;
      void loadLatestAutoReplyRun(target || null, selectedAccount, { background: backgroundAutoReplyRefresh });
      void loadConversationAutopilotState(target || null, selectedAccount, {
        background: backgroundAutopilotRefresh,
      });
    } else {
      autoReplyRunActiveKeyRef.current = null;
      conversationAutopilotActiveKeyRef.current = null;
      setConversationAutopilotState(null);
      setConversationAutopilotError(null);
      setLoadingConversationAutopilot(false);
      if (!conversations.length) {
        setMessages([]);
        setProfile(null);
      }
      setAutoReplyRun(null);
      setAutoReplyRunError(null);
      setLoadingAutoReplyRun(false);
      setProfileError(null);
      setLoadingProfile(false);
    }
  }, [conversations, loadConversationAutopilotState, loadConversationDetail, loadLatestAutoReplyRun, markConversationReadLocally, selectedAccount, selectedConversationId]);

  useEffect(() => {
    if (conversationJumpParams && !conversationJumpHandled) return;
    if (!filteredConversations.length) {
      setSelectedConversationId(null);
      return;
    }
    if (!selectedConversationId || !filteredConversations.some((item) => item.id === selectedConversationId)) {
      setSelectedConversationId(filteredConversations[0].id);
    }
  }, [conversationJumpHandled, conversationJumpParams, filteredConversations, selectedConversationId]);

  useEffect(() => {
    if (!selectedAccount) return undefined;

    const poll = async () => {
      if (document.visibilityState !== "visible") return;
      if (pollInFlightRef.current || loadingConversations || loadingMessages) return;
      pollInFlightRef.current = true;
      const currentAccount = selectedAccount;
      const currentConversationId = selectedConversationIdRef.current;
      try {
        const before = currentConversationId
          ? conversationsCacheRef.current[currentAccount.account_open_id]?.find((item) => item.id === currentConversationId)
          : null;
        const beforeWatermark = conversationWatermark(before);
        const beforeUnread = Number(before?.unread_count || 0);
        const items = await loadConversations(currentAccount, {
          skipDefaultSelection: true,
          background: true,
        });
        if (selectedAccountOpenIdRef.current !== currentAccount.account_open_id || !currentConversationId) return;
        const after = items.find((item) => item.id === currentConversationId) || null;
        const afterWatermark = conversationWatermark(after);
        const afterUnread = Number(after?.unread_count || 0);
        if (after && (afterWatermark !== beforeWatermark || afterUnread !== beforeUnread)) {
          void loadConversationDetail(currentConversationId, { background: true });
          void loadLatestAutoReplyRun(after, currentAccount, { background: true });
        }
      } finally {
        pollInFlightRef.current = false;
      }
    };

    const timer = window.setInterval(() => {
      void poll();
    }, 8000);
    return () => window.clearInterval(timer);
  }, [loadConversationDetail, loadConversations, loadLatestAutoReplyRun, loadingConversations, loadingMessages, selectedAccount]);

  useEffect(() => {
    if (!selectedAccount || !selectedConversation?.conversation_short_id) return undefined;

    const poll = async () => {
      if (document.visibilityState !== "visible") return;
      if (autoReplyRunPollInFlightRef.current) return;
      autoReplyRunPollInFlightRef.current = true;
      try {
        await loadLatestAutoReplyRun(selectedConversation, selectedAccount, { background: true });
      } finally {
        autoReplyRunPollInFlightRef.current = false;
      }
    };

    const timer = window.setInterval(() => {
      void poll();
    }, AUTO_REPLY_RUN_POLLING_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadLatestAutoReplyRun, selectedAccount, selectedConversation]);

  const refreshAuthStatus = useCallback(async () => {
    if (
      authPollingStartedAtRef.current &&
      Date.now() - authPollingStartedAtRef.current >= AUTH_POLLING_TIMEOUT_MS
    ) {
      setAuthPollingTimedOut(true);
      setAuthError("授权超时，请重新扫码");
      return null;
    }
    setAuthStatusLoading(true);
    try {
      const result = await fetchDouyinLiveCheckStatus();
      setAuthStatus(result.data);
      if (result.data.auth_polling?.status === "failed") {
        setAuthError("授权失败，请重新扫码");
      } else if (result.data.last_oauth_callback?.error) {
        setAuthError(result.data.last_oauth_callback.error_description || result.data.last_oauth_callback.error);
      } else {
        setAuthError(null);
      }
      return result.data;
    } catch (err) {
      const message = liveCheckErrorMessage(err);
      setAuthError(message);
      return null;
    } finally {
      setAuthStatusLoading(false);
    }
  }, []);

  async function openAuthModal() {
    setAuthModalOpen(true);
    setAuthLoading(true);
    setAuthError(null);
    setAuthUrlInfo(null);
    setAuthStatus(null);
    setAuthFrameFailed(false);
    setAuthAccountRefreshDone(false);
    setAuthPollingTimedOut(false);
    authPollingStartedAtRef.current = Date.now();
    if (authAutoCloseTimerRef.current) {
      window.clearTimeout(authAutoCloseTimerRef.current);
      authAutoCloseTimerRef.current = null;
    }
    try {
      const [authUrlResult] = await Promise.all([
        fetchDouyinLiveCheckAuthUrl(),
        refreshAuthStatus(),
      ]);
      setAuthUrlInfo(authUrlResult.data);
      if (!authUrlResult.data.configured || !authUrlResult.data.auth_url) {
        setAuthError(
          authUrlResult.data.missing.length
            ? `抖音授权信息不完整：${authUrlResult.data.missing.join("，")}`
            : "未返回可用的抖音授权 URL。",
        );
      }
    } catch (err) {
      setAuthError(liveCheckErrorMessage(err));
    } finally {
      setAuthLoading(false);
    }
  }

  async function refreshAccountsAfterAuth() {
    await loadAccounts(authOpenId);
    setAuthAccountRefreshDone(true);
  }

  useEffect(() => {
    if (!authModalOpen || authAuthorized || authPollingTimedOut) return undefined;
    const timer = window.setInterval(() => {
      void refreshAuthStatus();
    }, AUTH_POLLING_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [authAuthorized, authModalOpen, authPollingTimedOut, refreshAuthStatus]);

  useEffect(() => {
    if (!authModalOpen || !authAuthorized || authAccountRefreshDone) return;
    void refreshAccountsAfterAuth();
  }, [authAccountRefreshDone, authAuthorized, authModalOpen]);

  useEffect(() => {
    if (!authModalOpen || !authAuthorized || !authAccountRefreshDone) return undefined;
    authAutoCloseTimerRef.current = window.setTimeout(() => {
      setAuthModalOpen(false);
      authAutoCloseTimerRef.current = null;
    }, AUTH_SUCCESS_AUTO_CLOSE_MS);
    return () => {
      if (authAutoCloseTimerRef.current) {
        window.clearTimeout(authAutoCloseTimerRef.current);
        authAutoCloseTimerRef.current = null;
      }
    };
  }, [authAccountRefreshDone, authAuthorized, authModalOpen]);

  // 授权成功后（auth-redirect 302 回跳带 ?auth=success&open_id=xxx），
  // 自动把抖音号绑定到当前登录商户，成功后刷新账号列表。merchant_id 由后端从
  // RequestContext 取，前端只传 open_id。仅执行一次。
  useEffect(() => {
    if (authRedirectHandled) return;
    if (!authRedirectParams || authRedirectParams.auth !== "success") return;
    const { openId } = authRedirectParams;
    setAuthRedirectHandled(true);
    setAuthRedirectBinding(true);
    void bindAuthorizedOpenId(openId)
      .then(() => loadAccounts(openId))
      .then(() => {
        setAuthRedirectBinding(false);
        setAuthRedirectMessage({ text: "抖音号已绑定到当前商户，列表已刷新。", tone: "success" });
      })
      .catch((err: unknown) => {
        setAuthRedirectBinding(false);
        const code = extractBindErrorCode(err);
        if (code === "DOUYIN_ACCOUNT_ALREADY_BOUND_TO_OTHER_MERCHANT") {
          setAuthRedirectMessage({ text: "该抖音号已绑定其他商户，无法重复绑定。", tone: "error" });
        } else {
          setAuthRedirectMessage({ text: extractBindErrorText(err), tone: "error" });
        }
      });
  }, [authRedirectHandled, authRedirectParams, loadAccounts]);

  useEffect(() => {
    setDraftReplyText("");
    setSendError(null);
    setAccountModeMessage(null);
    setMediaDownloads({});
    setUploadDialogOpen(false);
    setUploadFile(null);
    setUploadError(null);
    setUploadResult(null);
    setUploadImageIdCopied(false);
  }, [selectedConversationId]);

  function openUploadDialog() {
    if (!selectedConversation || !selectedAccount) return;
    setUploadFile(null);
    setUploadError(null);
    setUploadResult(null);
    setUploadImageIdCopied(false);
    setUploadDialogOpen(true);
  }

  function closeUploadDialog() {
    setUploadDialogOpen(false);
    setUploadFile(null);
    setUploadError(null);
    setUploadResult(null);
    setUploadImageIdCopied(false);
  }

  async function copyAutoReplyContent() {
    const content = autoReplyGeneratedContent(autoReplyRun);
    if (!content) return;
    await navigator.clipboard.writeText(content);
    setAutoReplyCopied(true);
    window.setTimeout(() => setAutoReplyCopied(false), 1600);
  }

  function useAutoReplyAsManualDraft() {
    const content = autoReplyGeneratedContent(autoReplyRun);
    if (!content) return;
    setDraftReplyText(content);
    setSendError(null);
  }

  async function changeAccountMode(nextMode: ChatAssistMode) {
    const accountOpenId = selectedAccount?.account_open_id;
    if (!accountOpenId || savingAccountMode || nextMode === chatAssistMode) return;
    if (nextMode === "ai_auto_reply" && !activeBindingReady) {
      setAccountModeError("请先为该抖音号绑定智能体");
      return;
    }
    const previousMode = chatAssistMode;
    setSavingAccountMode(true);
    setAccountModeError(null);
    setAccountModeMessage(null);
    setChatAssistMode(nextMode);
    accountModeCacheRef.current[accountOpenId] = nextMode;
    try {
      const updated = await updateDouyinAutoReplyMode(accountOpenId, accountModeFromChatMode(nextMode));
      if (selectedAccountOpenIdRef.current !== accountOpenId) return;
      const savedMode = chatModeFromAccountMode(updated.mode);
      accountModeCacheRef.current[accountOpenId] = savedMode;
      setChatAssistMode(savedMode);
      if (savedMode === "ai_auto_reply") {
        setDraftReplyText("");
        setSendError(null);
        if (selectedConversation?.conversation_short_id) {
          try {
            const resumedState = await resumeDouyinConversationAutopilot(
              accountOpenId,
              selectedConversation.conversation_short_id,
              selectedConversation.customer_open_id || selectedConversation.open_id || null,
            );
            setConversationAutopilotState(resumedState);
            setConversationAutopilotError(null);
            if (
              selectedAccountOpenIdRef.current === accountOpenId &&
              selectedConversationIdRef.current === selectedConversation.id
            ) {
              setAccountModeMessage("已切换为 AI 自动回复，后续客户新消息将由 AI 处理。");
            }
          } catch {
            if (
              selectedAccountOpenIdRef.current === accountOpenId &&
              selectedConversationIdRef.current === selectedConversation.id
            ) {
              setAccountModeError("AI 自动回复模式已保存，但当前会话人工接管解除失败，请刷新或重试。");
            }
          }
        } else {
          setAccountModeMessage("已切换为 AI 自动回复。");
        }
      } else {
        setAccountModeMessage("已切换为人工接管。");
      }
    } catch (err) {
      accountModeCacheRef.current[accountOpenId] = previousMode;
      if (selectedAccountOpenIdRef.current === accountOpenId) {
        setChatAssistMode(previousMode);
        setAccountModeError(err instanceof Error ? err.message : "企业号托管模式保存失败");
      }
    } finally {
      if (selectedAccountOpenIdRef.current === accountOpenId) {
        setSavingAccountMode(false);
      }
    }
  }

  async function openAgentConfig(account: DouyinAccountItem) {
    setAgentConfigAccount(account);
    setAgentOptions([]);
    setSelectedAgentIdForConfig(account.bound_agent_id || "");
    setAgentConfigError(null);
    setLoadingAgentConfig(true);
    try {
      const data = await getDouyinAccountAgents(account.account_open_id);
      setAgentOptions(data.items || []);
      setSelectedAgentIdForConfig(data.default_agent_id || account.bound_agent_id || "");
    } catch (err) {
      setAgentConfigError(err instanceof Error ? err.message : "智能体列表加载失败");
    } finally {
      setLoadingAgentConfig(false);
    }
  }

  function closeAgentConfig() {
    if (savingAgentConfig) return;
    setAgentConfigAccount(null);
    setAgentOptions([]);
    setSelectedAgentIdForConfig("");
    setAgentConfigError(null);
  }

  function updateAccountAgentState(
    accountOpenId: string,
    patch: Pick<DouyinAccountItem, "bound_agent_id" | "bound_agent_name" | "bound_agent_status" | "binding_status">,
  ) {
    setAccounts((current) =>
      current.map((item) =>
        item.account_open_id === accountOpenId
          ? { ...item, ...patch }
          : item,
      ),
    );
    setAgentConfigAccount((current) =>
      current && current.account_open_id === accountOpenId
        ? { ...current, ...patch }
        : current,
    );
  }

  async function saveAgentConfig() {
    if (!agentConfigAccount || !selectedAgentIdForConfig || savingAgentConfig) return;
    const selectedAgent = agentOptions.find((item) => item.agent_id === selectedAgentIdForConfig);
    setSavingAgentConfig(true);
    setAgentConfigError(null);
    try {
      await bindAgentToDouyinAccount(agentConfigAccount.account_open_id, selectedAgentIdForConfig);
      updateAccountAgentState(agentConfigAccount.account_open_id, {
        bound_agent_id: selectedAgentIdForConfig,
        bound_agent_name: selectedAgent?.agent_name || selectedAgentIdForConfig,
        bound_agent_status: "active",
        binding_status: "active",
      });
    } catch (err) {
      setAgentConfigError(err instanceof Error ? err.message : "智能体绑定保存失败");
    } finally {
      setSavingAgentConfig(false);
    }
  }

  async function unbindAgentConfig() {
    if (!agentConfigAccount || savingAgentConfig) return;
    setSavingAgentConfig(true);
    setAgentConfigError(null);
    try {
      await unbindAgentFromDouyinAccount(agentConfigAccount.account_open_id);
      updateAccountAgentState(agentConfigAccount.account_open_id, {
        bound_agent_id: null,
        bound_agent_name: null,
        bound_agent_status: null,
        binding_status: "unbound",
      });
      if (selectedAccountOpenIdRef.current === agentConfigAccount.account_open_id) {
        setChatAssistMode("manual_takeover");
        setAccountModeError("当前抖音号已解绑智能体，请重新绑定后再开启 AI 自动回复");
      }
      setSelectedAgentIdForConfig("");
    } catch (err) {
      setAgentConfigError(err instanceof Error ? err.message : "智能体解绑失败");
    } finally {
      setSavingAgentConfig(false);
    }
  }

  function handleUploadFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] || null;
    const errorMessage = validateUploadImageFile(file);
    setUploadFile(errorMessage ? null : file);
    setUploadResult(null);
    setUploadImageIdCopied(false);
    setUploadError(errorMessage);
    event.target.value = "";
  }

  async function confirmUploadImage() {
    if (!selectedConversation || !selectedAccount) return;
    const errorMessage = validateUploadImageFile(uploadFile);
    if (errorMessage || !uploadFile) {
      setUploadError(errorMessage || UPLOAD_IMAGE_VALIDATION_MESSAGE);
      return;
    }

    setUploadingImage(true);
    setUploadError(null);
    setUploadResult(null);
    setUploadImageIdCopied(false);
    try {
      const imageBase64 = await readFileAsDataUrl(uploadFile);
      const result = await uploadDouyinImage({
        file_name: uploadFile.name,
        image_base64: imageBase64,
        open_id: selectedConversation.open_id,
      });
      if (result.success === false) {
        setUploadError(uploadImageResponseMessage(result));
        return;
      }
      setUploadResult(result.data || {});
      setUploadFile(null);
    } catch (err) {
      setUploadError(
        err instanceof Error && err.message ? err.message : "图片上传失败，请稍后重试",
      );
    } finally {
      setUploadingImage(false);
    }
  }

  async function confirmManualSend() {
    if (effectiveChatAssistMode !== "manual_takeover") return;
    if (!selectedConversation || !selectedAccount) return;
    const content = draftReplyText.trim();
    if (!content) {
      setSendError("请输入要发送的文本内容");
      return;
    }
    const conversationShortId = selectedConversation.conversation_short_id;
    if (!conversationShortId) {
      setSendError("当前会话缺少 conversation_short_id，无法发送");
      return;
    }
    setSendingMessage(true);
    setSendError(null);
    try {
      await sendDouyinManualMessage({
        conversation_short_id: String(conversationShortId),
        customer_open_id: selectedConversation.open_id,
        content,
        manual_confirmed: true,
      });
      setDraftReplyText("");
      await loadConversationDetail(selectedConversation.id);
      await loadConversations(selectedAccount);
    } catch (err) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : "发送失败";
      setSendError(message);
    } finally {
      setSendingMessage(false);
    }
  }

  function handleManualReplyKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || composingReplyRef.current || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    if (!sendingMessage && draftReplyText.trim()) {
      void confirmManualSend();
    }
  }

  async function downloadMessageResource(message: DouyinMessageItem) {
    const stateKey = String(message.id);
    const mediaType = mediaTypeForDownload(message);
    const conversationShortId = message.conversation_short_id || selectedConversation?.conversation_short_id;
    if (!message.downloadable_resource) {
      setMediaDownloads((current) => ({
        ...current,
        [stateKey]: { error: resourceMissingText(message.resource_missing_reason) },
      }));
      return;
    }
    if (!mediaType) {
      setMediaDownloads((current) => ({
        ...current,
        [stateKey]: { error: "当前消息不是图片或视频资源" },
      }));
      return;
    }
    if (!conversationShortId || !message.server_message_id) {
      setMediaDownloads((current) => ({
        ...current,
        [stateKey]: { error: "当前消息缺少下载所需的会话或消息标识" },
      }));
      return;
    }

    setMediaDownloads((current) => ({
      ...current,
      [stateKey]: { ...current[stateKey], loading: true, error: undefined },
    }));
    try {
      const result = await downloadDouyinResource({
        conversation_short_id: String(conversationShortId),
        server_message_id: String(message.server_message_id),
        media_type: mediaType,
      });
      const downloadUrl = result.data.download_url;
      setMediaDownloads((current) => ({
        ...current,
        [stateKey]: {
          loading: false,
          downloadUrl: downloadUrl || "",
          error: downloadUrl ? undefined : "后端未返回资源链接",
        },
      }));
    } catch (err) {
      setMediaDownloads((current) => ({
        ...current,
        [stateKey]: {
          loading: false,
          error: downloadErrorMessage(err),
        },
      }));
    }
  }

  async function copyDownloadUrl(messageId: string | number, downloadUrl: string) {
    const stateKey = String(messageId);
    try {
      await navigator.clipboard.writeText(downloadUrl);
      setMediaDownloads((current) => ({
        ...current,
        [stateKey]: { ...current[stateKey], copied: true },
      }));
      window.setTimeout(() => {
        setMediaDownloads((current) => ({
          ...current,
          [stateKey]: { ...current[stateKey], copied: false },
        }));
      }, 1600);
    } catch {
      setMediaDownloads((current) => ({
        ...current,
        [stateKey]: { ...current[stateKey], error: "复制链接失败，请手动复制" },
      }));
    }
  }

  async function copyUploadedImageId() {
    const imageId = uploadResult?.image_id;
    if (!imageId) return;
    try {
      await navigator.clipboard.writeText(imageId);
      setUploadImageIdCopied(true);
      window.setTimeout(() => setUploadImageIdCopied(false), 1600);
    } catch {
      setUploadError("复制 image_id 失败，请手动复制");
    }
  }

  // ponytail: 客户画像 body 提取复用——宽桌面内联第四栏与窄桌面 Sheet 抽屉共用同一份内容，消除重复 DOM
  const profileAsideBody = selectedConversation ? (
    <div className="min-h-0 flex-1 overflow-auto p-4">
      {loadingProfile ? (
        <div className="mb-3 inline-flex items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
          <LoaderIcon size={14} className="animate-spin" />
          正在加载客户画像...
        </div>
      ) : null}
      {profileError ? (
        <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
          <span>暂无客户画像，已保留会话基础信息。</span>
        </div>
      ) : null}

      <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center gap-3">
          {profileAvatar ? (
            <img
              src={profileAvatar}
              alt={profileNickname}
              className="h-10 w-10 rounded-md object-cover"
            />
          ) : (
            <span className="grid h-10 w-10 place-items-center rounded-md bg-white text-slate-400 ring-1 ring-slate-200">
              <UserRoundIcon size={18} />
            </span>
          )}
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-[#172033]">{profileNickname}</div>
            <div className="mt-1 truncate font-mono text-[11px] text-slate-500">
              {compactOpenId(profileOpenId)}
            </div>
          </div>
        </div>
        <div className="mt-3 inline-flex rounded bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 ring-1 ring-slate-200">
          {onlineStatusText(profile?.online_status)}
        </div>
      </div>

      <div className="mt-4 space-y-3 text-xs">
        <div>
          <div className="font-semibold text-slate-500">基础信息</div>
          <div className="mt-1 grid gap-2 rounded-md bg-white px-3 py-2 text-slate-800 ring-1 ring-slate-200">
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">来源渠道</span>
              <span className="text-right">{profileFieldText(profile?.source_channel)}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">意向车型</span>
              <span className="text-right">{profileFieldText(profile?.intent_car)}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">年份</span>
              <span className="text-right">{profileFieldText(profile?.car_year)}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">预算</span>
              <span className="text-right">{profileFieldText(profile?.budget)}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">城市</span>
              <span className="text-right">{profileFieldText(profile?.city)}</span>
            </div>
          </div>
        </div>
        <div>
          <div className="font-semibold text-slate-500">当前标签</div>
          <div className="mt-1 flex flex-wrap gap-1.5 rounded-md bg-white px-3 py-2 text-slate-800 ring-1 ring-slate-200">
            {profileTags.length ? (
              profileTags.map((tag) => (
                <span key={tag} className="rounded bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-700">
                  {tag}
                </span>
              ))
            ) : (
              <span className="text-slate-500">暂无标签</span>
            )}
          </div>
        </div>
        <div>
          <div className="font-semibold text-slate-500">线索评分</div>
          <div className="mt-1 rounded-md bg-white px-3 py-3 text-slate-800 ring-1 ring-slate-200">
            {profileLeadScore === null ? (
              <div className="text-slate-500">暂无评分</div>
            ) : (
              <>
                <div className="mb-2 flex items-center justify-between">
                  <span className="font-semibold">{profileLeadScore}%</span>
                  <span className="text-[11px] text-slate-500">0-100</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-blue-600"
                    style={{ width: `${profileLeadScore}%` }}
                  />
                </div>
              </>
            )}
          </div>
        </div>
        <div>
          <div className="font-semibold text-slate-500">线索信息</div>
          <div className="mt-1 grid gap-2 rounded-md bg-white px-3 py-2 text-slate-800 ring-1 ring-slate-200">
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">线索 ID</span>
              <span className="text-right">{profileFieldText(profile?.lead?.id)}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">状态</span>
              <span className="text-right">{statusText(profile?.lead?.status || selectedConversation.lead_status)}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">联系方式</span>
              <span className="text-right">{profileFieldText(profile?.lead?.customer_contact)}</span>
            </div>
          </div>
        </div>
        <div>
          <div className="font-semibold text-slate-500">溯源信息</div>
          <div className="mt-1 grid gap-2 rounded-md bg-white px-3 py-2 text-slate-800 ring-1 ring-slate-200">
            {profileTraceItems.length ? (
              profileTraceItems.map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3">
                  <span className="shrink-0 text-slate-500">{label}</span>
                  <span className="min-w-0 break-all text-right font-mono text-[11px]">{value}</span>
                </div>
              ))
            ) : (
              <span className="text-slate-500">暂无溯源信息</span>
            )}
          </div>
        </div>
      </div>
    </div>
  ) : (
    <EmptyState text="暂无客户画像，客户画像信息待后端同步" />
  );

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <MessageCircleMoreIcon size={22} />
          </div>
          <div className="min-w-0">
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">抖音AI小高客服</h1>
            <p className="mt-1 text-xs leading-5 text-[#8b95a6]">
              多抖音号会话工作台，当前支持测试白名单内的 AI 自动回复闭环。
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setProfileDrawerOpen(true)}
            className="hidden max-[1499px]:inline-flex items-center gap-1.5 rounded-md border border-[#dfe5ee] bg-white px-3 py-2 text-xs font-semibold text-[#1a1f2e] hover:bg-[#f3f6fa]"
          >
            <UserRoundIcon size={15} />
            客户画像
          </button>
          <div className="max-w-[420px] rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-semibold leading-5 text-blue-700">
            {chatModeTitle(effectiveChatAssistMode, activeBindingReady)}
          </div>
        </div>
      </header>

      <ErrorBanner message={error} onRetry={() => void loadAccounts()} />

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(200px,260px)_minmax(260px,320px)_minmax(320px,1fr)] overflow-hidden p-4 pt-3 min-[1500px]:grid-cols-[260px_320px_minmax(420px,1fr)_260px]">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-l-lg border border-r-0 border-[#dfe5ee] bg-white">
          <div className="flex h-14 items-center justify-between border-b border-[#edf1f6] px-4">
            <div>
              <div className="text-sm font-bold text-[#172033]">抖音号</div>
              <div className="text-[11px] text-slate-500">商户本地授权管理</div>
            </div>
            <button
              onClick={() => void loadAccounts()}
              className="grid h-8 w-8 place-items-center rounded-md text-slate-500 hover:bg-slate-100"
              aria-label="刷新抖音号"
            >
              <RefreshCwIcon size={15} className={loadingAccounts ? "animate-spin" : ""} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-2">
            {loadingAccounts ? <EmptyState text="正在加载抖音号..." /> : null}
            {!loadingAccounts && accounts.length === 0 ? (
              <EmptyState text="暂无抖音号：请在商户本地授权管理中添加抖音号。" />
            ) : null}
            {accounts.map((account) => {
              const active = account.id === selectedAccountId;
              const accountHasAgent = hasActiveAgentBinding(account);
              return (
                <div
                  key={account.id}
                  onClick={() => setSelectedAccountId(account.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedAccountId(account.id);
                    }
                  }}
                  className={`mb-2 flex w-full cursor-pointer items-center gap-3 rounded-md border px-3 py-3 text-left transition ${
                    active ? "border-blue-200 bg-blue-50" : "border-transparent hover:bg-slate-50"
                  }`}
                >
                  <img
                    src={account.avatar || `https://api.dicebear.com/7.x/initials/svg?seed=${account.id}`}
                    alt={account.account_name}
                    className="h-10 w-10 rounded-md bg-slate-100"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-[#172033]">
                      {account.account_name}
                    </span>
                    <span className="mt-1 inline-flex max-w-full rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-semibold text-blue-700">
                      {authorizationStatusText(account.authorization_status)}
                    </span>
                    <span className="mt-1 block truncate text-[11px] text-slate-500">
                      {accountIdentityText(account)}
                    </span>
                    <span
                      className={`mt-1 inline-flex max-w-full rounded px-1.5 py-0.5 text-[11px] font-semibold ${
                        accountHasAgent
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-amber-50 text-amber-700"
                      }`}
                    >
                      {accountHasAgent ? account.bound_agent_name || "已绑定" : "未绑定智能体"}
                    </span>
                  </span>
                  {account.unread_count ? (
                    <span className="grid h-5 min-w-5 place-items-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                      {account.unread_count}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      void openAgentConfig(account);
                    }}
                    className={`grid h-8 w-8 shrink-0 place-items-center rounded-md ${
                      accountHasAgent
                        ? "text-slate-500 hover:bg-white"
                        : "bg-amber-100 text-amber-700 hover:bg-amber-200"
                    }`}
                    aria-label={`绑定 ${account.account_name} 智能体`}
                    title="绑定智能体"
                  >
                    <WrenchIcon size={15} />
                  </button>
                </div>
              );
            })}
          </div>

          <div className="border-t border-[#edf1f6] p-3">
            <button
              onClick={() => void openAuthModal()}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md border border-blue-200 bg-blue-50 text-xs font-semibold text-blue-700 hover:bg-blue-100"
            >
              <PlusIcon size={15} />
              添加抖音号
            </button>
          </div>
        </aside>

        <aside className="flex min-h-0 flex-col overflow-hidden border border-r-0 border-[#dfe5ee] bg-white">
          <div className="border-b border-[#edf1f6] px-4 py-3">
            <div className="text-sm font-bold text-[#172033]">会话列表</div>
            <div className="mt-0.5 truncate text-[11px] text-slate-500">
              {selectedAccount?.account_name || "未选择抖音号"}
            </div>
            <label className="mt-3 flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs text-slate-500">
              <SearchIcon size={14} />
              <input
                value={conversationSearch}
                onChange={(event) => setConversationSearch(event.target.value)}
                placeholder="搜索客户、联系方式或消息"
                aria-label="搜索会话"
                className="min-w-0 flex-1 bg-transparent text-slate-700 outline-none placeholder:text-slate-400"
              />
            </label>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {CONVERSATION_FILTERS.map((item) => (
                <button
                  key={item.key}
                  onClick={() => setConversationFilter(item.key)}
                  className={`h-7 rounded-md px-2 text-[11px] font-semibold transition ${
                    conversationFilter === item.key
                      ? "bg-blue-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-2">
            {loadingConversations && conversations.length === 0 ? <EmptyState text="正在加载会话..." /> : null}
            {!loadingConversations && conversations.length === 0 ? <EmptyState text="该抖音号暂无私信会话。" /> : null}
            {!loadingConversations && conversations.length > 0 && filteredConversations.length === 0 ? (
              <div className="grid min-h-[180px] place-items-center px-6 text-center text-xs text-slate-500">
                <div>
                  <p>没有符合条件的会话。</p>
                  {(conversationSearch || conversationFilter !== "all") ? (
                    <button
                      onClick={() => { setConversationSearch(""); setConversationFilter("all"); }}
                      className="mt-3 inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      <RefreshCwIcon size={12} />
                      重置筛选
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}
            {filteredConversations.map((conversation) => {
              const active = conversation.id === selectedConversationId;
              const leadStatus = conversationLeadStatusForList(
                conversation,
                selectedAccount?.account_open_id,
                profileCacheRef.current,
              );
              const tags = visibleConversationTags(conversation.tags, leadStatus);
              const captured = isCapturedLeadStatus(leadStatus);
              return (
                <button
                  key={conversation.id}
                  onClick={() => {
                    markConversationReadLocally(conversation);
                    setSelectedConversationId(conversation.id);
                  }}
                  className={`mb-2 w-full rounded-md border px-3 py-3 text-left transition ${
                    active ? "border-blue-200 bg-blue-50" : "border-transparent hover:bg-slate-50"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-sm font-semibold text-[#172033]">
                      {conversation.nickname}
                    </span>
                    <span className="shrink-0 text-[11px] text-slate-400">
                      {formatTime(conversation.last_message_at)}
                    </span>
                  </div>
                  <div className="mt-1 truncate text-xs text-slate-500">{conversation.last_message}</div>
                  {tags.length ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700"
                        >
                          {conversationTagText(tag)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <div className="mt-2 flex items-center justify-between">
                    {captured ? (
                      <span className="rounded bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700">
                        已留资
                      </span>
                    ) : (
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                        {statusText(leadStatus)}
                      </span>
                    )}
                    {conversation.unread_count ? (
                      <span className="text-[11px] font-semibold text-red-500">
                        {conversation.unread_count} 未读
                      </span>
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        <section className="flex min-h-0 flex-col overflow-hidden border border-r-0 border-[#dfe5ee] bg-white">
          <div className="flex min-h-20 items-center justify-between gap-4 border-b border-[#edf1f6] px-5 py-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-bold text-[#172033]">
                {selectedConversation?.nickname || "请选择会话"}
              </div>
              <div className="mt-0.5 truncate text-[11px] text-slate-500">
                {selectedConversation ? profileSummary : "选择会话后查看客户画像"}
              </div>
              <div
                className={`mt-2 flex items-start gap-2 text-[11px] leading-5 ${
                  effectiveChatAssistMode === "manual_takeover" ? "text-amber-700" : "text-blue-700"
                }`}
              >
                <span
                  className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                    effectiveChatAssistMode === "manual_takeover" ? "bg-amber-500" : "bg-blue-500"
                  }`}
                />
                <span>
                  <span className="font-bold">{chatModeTitle(effectiveChatAssistMode, activeBindingReady)}</span>
                  <span className="ml-1 text-slate-500">
                    {activeBindingReady
                      ? chatModeSubtitle(effectiveChatAssistMode)
                      : "当前抖音号未绑定智能体，请先在左侧账号列表点击绑定后再开启 AI 自动回复"}
                  </span>
                  {loadingAccountMode ? <span className="ml-1 text-slate-400">正在同步企业号模式...</span> : null}
                </span>
              </div>
              {accountModeError ? (
                <div className="mt-1 text-[11px] leading-5 text-red-600">{accountModeError}</div>
              ) : null}
              {accountModeMessage ? (
                <div className="mt-1 text-[11px] leading-5 text-emerald-700">{accountModeMessage}</div>
              ) : null}
              {selectedConversation &&
              (loadingConversationAutopilot || conversationAutopilotError || conversationAutopilotText(conversationAutopilotState)) ? (
                <div
                  className={`mt-1 text-[11px] leading-5 ${
                    conversationAutopilotState?.mode === "manual" ? "text-amber-700" : "text-slate-500"
                  }`}
                >
                  {loadingConversationAutopilot
                    ? "正在读取当前会话托管状态..."
                    : conversationAutopilotError || conversationAutopilotText(conversationAutopilotState)}
                </div>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <div className="flex overflow-hidden rounded-md border border-slate-200 bg-slate-50 p-1">
                <button
                  type="button"
                  onClick={() => void changeAccountMode("ai_auto_reply")}
                  disabled={!selectedAccount || !activeBindingReady || savingAccountMode || loadingAccountMode}
                  className={`h-8 rounded px-3 text-[11px] font-semibold ${
                    effectiveChatAssistMode === "ai_auto_reply"
                      ? "bg-blue-600 text-white shadow-sm"
                      : "text-slate-600 hover:bg-white disabled:text-slate-400"
                  }`}
                  title={!activeBindingReady ? "请先为该抖音号绑定智能体" : undefined}
                >
                  {savingAccountMode && chatAssistMode === "ai_auto_reply" ? "保存中..." : "AI 自动回复"}
                </button>
                <button
                  type="button"
                  onClick={() => void changeAccountMode("manual_takeover")}
                  disabled={!selectedAccount || savingAccountMode || loadingAccountMode}
                  className={`h-8 rounded px-3 text-[11px] font-semibold ${
                    effectiveChatAssistMode === "manual_takeover"
                      ? "bg-amber-500 text-white shadow-sm"
                      : "text-slate-600 hover:bg-white disabled:text-slate-400"
                  }`}
                >
                  {savingAccountMode && chatAssistMode === "manual_takeover" ? "保存中..." : "人工接管"}
                </button>
              </div>
            </div>
          </div>

          <div className="grid min-h-0 flex-1 grid-rows-[minmax(220px,1fr)_minmax(270px,42%)]">
            <div className="min-h-0 overflow-auto bg-[#f8fafc] px-5 py-4">
              {loadingMessages && messages.length === 0 ? <EmptyState text="正在加载聊天消息..." /> : null}
              {!loadingMessages && messages.length === 0 ? <EmptyState text="暂无消息。" /> : null}
              <div className="space-y-3">
                {messages.map((message) => {
                  const isCustomer = isCustomerMessage(message);
                  const isManual = isManualMessage(message);
                  const mediaType = mediaTypeForDownload(message);
                  const downloadState = mediaDownloads[String(message.id)] || {};
                  const downloadableResource = Boolean(mediaType && message.downloadable_resource);
                  const canRequestDownload = Boolean(
                    downloadableResource &&
                      (message.conversation_short_id || selectedConversation?.conversation_short_id) &&
                      message.server_message_id,
                  );
                  return (
                    <div
                      key={message.id}
                      className={`flex ${messageLayoutClass(message)}`}
                    >
                      <div
                        className={`max-w-[72%] rounded-lg px-3 py-2 text-sm leading-6 shadow-sm ${
                          messageBubbleClass(message)
                        }`}
                      >
                        <div
                          className={`mb-1 text-[10px] font-semibold ${
                            isManual ? "text-blue-100" : isCustomer ? "text-slate-500" : "text-slate-400"
                          }`}
                        >
                          {messageRoleLabel(message)}
                        </div>
                        <div>{message.content}</div>
                        {mediaType ? (
                          <div
                            className={`mt-2 rounded-md border px-2 py-2 text-xs ${
                              isCustomer
                                ? "border-slate-200 bg-slate-50 text-slate-600"
                                : "border-blue-400/40 bg-blue-500 text-blue-50"
                            }`}
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              {downloadableResource ? (
                                <button
                                  onClick={() => void downloadMessageResource(message)}
                                  disabled={downloadState.loading || !canRequestDownload}
                                  className={`inline-flex h-7 items-center gap-1.5 rounded-md px-2 font-semibold ${
                                    isCustomer
                                      ? "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                                      : "border border-blue-200/50 bg-white/10 text-white hover:bg-white/15"
                                  } disabled:cursor-not-allowed disabled:opacity-60`}
                                >
                                  {downloadState.loading ? (
                                    <LoaderIcon size={13} className="animate-spin" />
                                  ) : (
                                    <DownloadIcon size={13} />
                                  )}
                                  {downloadState.loading ? "下载中..." : "下载资源"}
                                </button>
                              ) : null}
                              <span>{mediaType === "image" ? "图片资源" : "视频资源"}</span>
                            </div>
                            {mediaType && !downloadableResource ? (
                              <div className="mt-1 leading-5">{resourceMissingText(message.resource_missing_reason)}</div>
                            ) : null}
                            {downloadableResource && !canRequestDownload ? (
                              <div className="mt-1 leading-5">当前消息缺少下载所需的会话或消息标识。</div>
                            ) : null}
                            {downloadState.downloadUrl ? (
                              <div className="mt-2 space-y-1">
                                <div className="break-all rounded bg-white/70 px-2 py-1 font-mono text-[10px] text-slate-600">
                                  {downloadState.downloadUrl}
                                </div>
                                <button
                                  onClick={() => void copyDownloadUrl(message.id, downloadState.downloadUrl || "")}
                                  className={`inline-flex h-7 items-center gap-1.5 rounded-md px-2 font-semibold ${
                                    isCustomer
                                      ? "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                                      : "border border-blue-200/50 bg-white/10 text-white hover:bg-white/15"
                                  }`}
                                >
                                  <ClipboardIcon size={13} />
                                  {downloadState.copied ? "已复制" : "复制链接"}
                                </button>
                              </div>
                            ) : null}
                            {downloadState.error ? (
                              <div className="mt-1 leading-5 text-red-500">{downloadState.error}</div>
                            ) : null}
                          </div>
                        ) : null}
                        <div className={`mt-1 text-[10px] ${messageMetaClass(message)}`}>
                          {messageRoleLabel(message)} · {formatTime(message.created_at)}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="min-h-0 overflow-auto border-t border-[#edf1f6] bg-white p-5">
              {/* ponytail: 窄桌面（<1500px，第三列宽度受限）发送区标题与附件操作上下堆叠，避免逐字换行；宽桌面恢复左右布局 */}
              <div className="mb-3 flex flex-col items-start gap-3 min-[1500px]:flex-row min-[1500px]:items-center min-[1500px]:justify-between">
                <div className="flex items-center gap-2">
                  <span className="grid h-8 w-8 place-items-center rounded-md bg-blue-50 text-blue-600">
                    <BotIcon size={16} />
                  </span>
                  <div>
                    <div className="text-sm font-bold text-[#172033]">
                      {effectiveChatAssistMode === "manual_takeover" ? "人工客服" : "AI 自动回复"}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {effectiveChatAssistMode === "manual_takeover"
                        ? "人工接管状态下可手动发送消息"
                        : "AI 托管中，如需人工发送请先切换到人工接管。"}
                    </div>
                  </div>
                </div>
                {effectiveChatAssistMode === "manual_takeover" ? (
                  <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                    <button
                      type="button"
                      disabled
                      title="表情暂未接入"
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs font-semibold text-slate-400"
                    >
                      <SmileIcon size={14} />
                      表情
                    </button>
                    {selectedConversation ? (
                      <button
                        onClick={() => openUploadDialog()}
                        disabled={!selectedAccount}
                        className="inline-flex h-9 items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400"
                      >
                        <ImagePlusIcon size={14} />
                        图片素材
                      </button>
                    ) : null}
                    <button
                      type="button"
                      disabled
                      title="视频暂未接入"
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs font-semibold text-slate-400"
                    >
                      <VideoIcon size={14} />
                      视频
                    </button>
                    <button
                      type="button"
                      disabled
                      title="文件暂未接入"
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs font-semibold text-slate-400"
                    >
                      <PaperclipIcon size={14} />
                      文件
                    </button>
                  </div>
                ) : null}
              </div>

              {effectiveChatAssistMode === "manual_takeover" ? (
                <div className="space-y-3">
                  {shouldShowAutoReplyRunCard(autoReplyRun, loadingAutoReplyRun, autoReplyRunError) ? (
                    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-5 text-amber-900">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="font-bold text-amber-950">
                            {loadingAutoReplyRun ? "正在加载 AI 自动回复状态..." : autoReplyRunTitle(autoReplyRun)}
                          </div>
                          {shouldShowAutoReplyRunReason(autoReplyRun, Boolean(autoReplyRunError)) ? (
                            <div className="mt-1">
                              {autoReplyRunError ? "未发送：自动回复状态加载失败" : autoReplyRunReasonText(autoReplyRun)}
                            </div>
                          ) : null}
                        </div>
                        {loadingAutoReplyRun ? <LoaderIcon size={14} className="mt-0.5 shrink-0 animate-spin" /> : null}
                      </div>
                      {autoReplyRunError ? (
                        <div className="mt-2 text-amber-800">{autoReplyRunError}</div>
                      ) : null}
                      {visibleAutoReplyGeneratedContent(autoReplyRun) ? (
                        <div className="mt-3 rounded-md border border-amber-200 bg-white/75 p-3">
                          <div className="mb-1 font-semibold text-amber-950">AI 已生成的回复内容</div>
                          <div className="whitespace-pre-wrap text-slate-800">
                            {visibleAutoReplyGeneratedContent(autoReplyRun)}
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => void copyAutoReplyContent()}
                              className="inline-flex h-8 items-center gap-2 rounded-md border border-amber-200 bg-white px-2.5 font-semibold text-amber-800 hover:bg-amber-100"
                            >
                              <ClipboardIcon size={13} />
                              {autoReplyCopied ? "已复制" : "复制"}
                            </button>
                            <button
                              type="button"
                              onClick={() => useAutoReplyAsManualDraft()}
                              className="inline-flex h-8 items-center gap-2 rounded-md border border-blue-200 bg-white px-2.5 font-semibold text-blue-700 hover:bg-blue-50"
                            >
                              填入人工草稿
                            </button>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <textarea
                    value={draftReplyText}
                    onChange={(event) => setDraftReplyText(event.target.value)}
                    onKeyDown={handleManualReplyKeyDown}
                    onCompositionStart={() => {
                      composingReplyRef.current = true;
                    }}
                    onCompositionEnd={() => {
                      composingReplyRef.current = false;
                    }}
                    rows={3}
                    className="w-full resize-none rounded-md border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400 focus:border-blue-300"
                    placeholder="输入人工回复内容，Enter 发送，Shift + Enter 换行"
                    aria-label="人工回复内容"
                  />
                  {sendError ? (
                    <div className="mt-2 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
                      <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
                      <span>{sendError}</span>
                    </div>
                  ) : null}
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <span className="text-[11px] text-slate-500">发送前会继续走人工确认安全链路。</span>
                    <button
                      onClick={() => void confirmManualSend()}
                      disabled={sendingMessage || !selectedAccount || !selectedConversation || !draftReplyText.trim()}
                      className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-4 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {sendingMessage ? <LoaderIcon size={14} className="animate-spin" /> : <CheckIcon size={14} />}
                      发送
                    </button>
                  </div>
                </div>
                </div>
              ) : (
                <div className="space-y-3">
                  {shouldShowAutoReplyRunCard(autoReplyRun, loadingAutoReplyRun, autoReplyRunError) ? (
                    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-5 text-amber-900">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="font-bold text-amber-950">
                            {loadingAutoReplyRun ? "正在加载 AI 自动回复状态..." : autoReplyRunTitle(autoReplyRun)}
                          </div>
                          {shouldShowAutoReplyRunReason(autoReplyRun, Boolean(autoReplyRunError)) ? (
                            <div className="mt-1">
                              {autoReplyRunError ? "未发送：自动回复状态加载失败" : autoReplyRunReasonText(autoReplyRun)}
                            </div>
                          ) : null}
                        </div>
                        {loadingAutoReplyRun ? <LoaderIcon size={14} className="mt-0.5 shrink-0 animate-spin" /> : null}
                      </div>
                      {autoReplyRunError ? (
                        <div className="mt-2 text-amber-800">{autoReplyRunError}</div>
                      ) : null}
                      {visibleAutoReplyGeneratedContent(autoReplyRun) ? (
                        <div className="mt-3 rounded-md border border-amber-200 bg-white/75 p-3">
                          <div className="mb-1 font-semibold text-amber-950">AI 已生成的回复内容</div>
                          <div className="whitespace-pre-wrap text-slate-800">
                            {visibleAutoReplyGeneratedContent(autoReplyRun)}
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => void copyAutoReplyContent()}
                              className="inline-flex h-8 items-center gap-2 rounded-md border border-amber-200 bg-white px-2.5 font-semibold text-amber-800 hover:bg-amber-100"
                            >
                              <ClipboardIcon size={13} />
                              {autoReplyCopied ? "已复制" : "复制"}
                            </button>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-xs leading-6 text-blue-800">
                    AI 托管中，如需人工发送请先切换到人工接管。
                    {!activeBindingReady ? " 当前企业号暂未满足自动回复启用条件。" : ""}
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* 宽桌面（>=1500px）：客户画像内联第四栏 */}
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-r-lg border border-[#dfe5ee] bg-white min-[1500px]:flex max-[1499px]:hidden">
          <div className="flex h-14 items-center gap-2 border-b border-[#edf1f6] px-4">
            <span className="grid h-8 w-8 place-items-center rounded-md bg-blue-50 text-blue-600">
              <UserRoundIcon size={16} />
            </span>
            <div>
              <div className="text-sm font-bold text-[#172033]">客户画像</div>
              <div className="text-[11px] text-slate-500">会话辅助信息</div>
            </div>
          </div>
          {profileAsideBody}
        </aside>
      </div>

      {/* 窄桌面（<1500px）：复用 Sheet 抽屉，自带 Esc 关闭、焦点约束、遮罩与对话框语义 */}
      <Sheet open={profileDrawerOpen} onOpenChange={setProfileDrawerOpen}>
        <SheetContent side="right" className="w-[300px] max-w-[300px] gap-0 p-0 sm:max-w-[300px]">
          <SheetHeader className="flex h-14 flex-row items-center gap-2 border-b border-[#edf1f6] px-4">
            <span className="grid h-8 w-8 place-items-center rounded-md bg-blue-50 text-blue-600">
              <UserRoundIcon size={16} />
            </span>
            <div className="flex flex-col gap-0">
              <SheetTitle className="text-sm font-bold text-[#172033]">客户画像</SheetTitle>
              <SheetDescription className="text-[11px] text-slate-500">会话辅助信息</SheetDescription>
            </div>
          </SheetHeader>
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{profileAsideBody}</div>
        </SheetContent>
      </Sheet>

      {agentConfigAccount ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 px-4" role="dialog" aria-modal="true" aria-labelledby="agent-config-title">
          <div className="w-full max-w-xl overflow-hidden rounded-lg bg-white shadow-[0_24px_80px_rgba(15,23,42,0.32)]">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div className="flex items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-amber-50 text-amber-600">
                  <WrenchIcon size={18} />
                </span>
                <div>
                  <h2 id="agent-config-title" className="text-sm font-bold text-[#172033]">绑定智能体</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    {agentConfigAccount.account_name} · {compactOpenId(agentConfigAccount.account_open_id)}
                  </p>
                </div>
              </div>
              <button
                onClick={() => closeAgentConfig()}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-slate-500 hover:bg-slate-100"
                aria-label="关闭智能体绑定弹窗"
              >
                <XIcon size={16} />
              </button>
            </div>

            <div className="space-y-4 p-5 text-xs">
              <div className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-slate-600">
                <div className="flex items-center justify-between gap-3">
                  <span>当前抖音号</span>
                  <span className="truncate text-right font-semibold text-[#172033]">
                    {agentConfigAccount.account_name}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>当前智能体</span>
                  <span className="truncate text-right font-semibold text-[#172033]">
                    {hasActiveAgentBinding(agentConfigAccount)
                      ? agentConfigAccount.bound_agent_name || agentConfigAccount.bound_agent_id
                      : "未绑定"}
                  </span>
                </div>
              </div>

              {agentConfigError ? (
                <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 leading-5 text-red-700">
                  <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
                  <span>{agentConfigError}</span>
                </div>
              ) : null}

              <div>
                <div className="mb-2 font-bold text-[#172033]">选择智能体</div>
                <div className="max-h-64 overflow-auto rounded-md border border-slate-200">
                  {loadingAgentConfig ? (
                    <div className="grid min-h-32 place-items-center text-slate-500">
                      <span className="inline-flex items-center gap-2">
                        <LoaderIcon size={15} className="animate-spin" />
                        正在加载智能体...
                      </span>
                    </div>
                  ) : null}
                  {!loadingAgentConfig && agentOptions.length === 0 ? (
                    <div className="grid min-h-32 place-items-center px-6 text-center leading-5 text-slate-500">
                      当前商户暂无可用 active 智能体，请先在智能体管理中创建并启用。
                    </div>
                  ) : null}
                  {!loadingAgentConfig && agentOptions.map((agent) => (
                    <label
                      key={agent.agent_id}
                      className={`flex cursor-pointer items-start gap-3 border-b border-slate-100 px-3 py-3 last:border-b-0 ${
                        selectedAgentIdForConfig === agent.agent_id ? "bg-blue-50" : "hover:bg-slate-50"
                      }`}
                    >
                      <input
                        type="radio"
                        name="douyin-account-agent"
                        checked={selectedAgentIdForConfig === agent.agent_id}
                        onChange={() => setSelectedAgentIdForConfig(agent.agent_id)}
                        className="mt-1"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-[#172033]">
                          {agent.agent_name}
                        </span>
                        <span className="mt-1 block truncate text-[11px] text-slate-500">
                          {agent.agent_id}
                        </span>
                      </span>
                      {agent.is_default ? (
                        <span className="rounded bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700">
                          当前
                        </span>
                      ) : null}
                    </label>
                  ))}
                </div>
              </div>

              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 leading-5 text-amber-800">
                未绑定智能体的抖音号不能开启 AI 自动回复；人工发送不受智能体绑定限制，但仍需要人工确认。
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => void unbindAgentConfig()}
                  disabled={savingAgentConfig || !hasActiveAgentBinding(agentConfigAccount)}
                  className="h-9 rounded-md border border-red-200 bg-white px-3 font-semibold text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  解绑
                </button>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => closeAgentConfig()}
                    disabled={savingAgentConfig}
                    className="h-9 rounded-md border border-slate-200 bg-white px-3 font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveAgentConfig()}
                    disabled={savingAgentConfig || loadingAgentConfig || !selectedAgentIdForConfig}
                    className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {savingAgentConfig ? <LoaderIcon size={14} className="animate-spin" /> : <CheckIcon size={14} />}
                    保存
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {authModalOpen ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 px-4" role="dialog" aria-modal="true" aria-labelledby="auth-modal-title">
          <div className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-white shadow-[0_24px_80px_rgba(15,23,42,0.32)]">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div className="flex items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-blue-50 text-blue-600">
                  <QrCodeIcon size={18} />
                </span>
                <div>
                  <h2 id="auth-modal-title" className="text-sm font-bold text-[#172033]">添加抖音号</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    请使用抖音 App 扫码授权。授权页在系统内弹出，不会打开外部浏览器。
                  </p>
                </div>
              </div>
              <button
                onClick={() => setAuthModalOpen(false)}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-slate-500 hover:bg-slate-100"
                aria-label="关闭授权弹窗"
              >
                <XIcon size={16} />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-auto p-5">
              {authError ? (
                <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                  <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
                  <span>{authError}</span>
                </div>
              ) : null}

              {authAuthorized ? (
                <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-800">
                  授权成功，{authAccountRefreshDone ? "抖音号列表已刷新，即将关闭弹窗。" : "正在刷新抖音号列表..."}
                </div>
              ) : null}

              {authRedirectBinding || authRedirectMessage ? (
                <div
                  className={
                    authRedirectMessage?.tone === "error"
                      ? "mb-4 flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-800"
                      : "mb-4 flex items-start gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-800"
                  }
                >
                  {authRedirectBinding ? (
                    <LoaderIcon size={15} className="mt-0.5 shrink-0 animate-spin" />
                  ) : authRedirectMessage?.tone === "error" ? (
                    <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
                  ) : (
                    <CheckIcon size={15} className="mt-0.5 shrink-0" />
                  )}
                  <span>
                    {authRedirectBinding
                      ? "正在将抖音号绑定到当前商户..."
                      : authRedirectMessage?.text}
                  </span>
                </div>
              ) : null}

              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_240px]">
                <div className="min-h-[420px] overflow-hidden rounded-md border border-slate-200 bg-slate-50">
                  {authLoading ? (
                    <div className="grid h-[420px] place-items-center text-xs text-slate-500">
                      <span className="inline-flex items-center gap-2">
                        <LoaderIcon size={15} className="animate-spin" />
                        正在获取抖音授权页面...
                      </span>
                    </div>
                  ) : authUrlInfo?.auth_url ? (
                    <>
                      <iframe
                        title="抖音扫码授权"
                        src={authUrlInfo.auth_url}
                        className="h-[420px] w-full bg-white"
                        onError={() => setAuthFrameFailed(true)}
                      />
                      {authFrameFailed ? (
                        <div className="border-t border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                          授权页可能禁止内嵌显示。当前页面不会自动打开外部浏览器，可手动复制下方授权 URL 到受控环境处理。
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div className="grid h-[420px] place-items-center px-6 text-center text-xs leading-6 text-slate-500">
                      暂无可展示的授权页面，请检查 9000 授权信息。
                    </div>
                  )}
                </div>

                <aside className="rounded-md border border-slate-200 bg-white p-3 text-xs">
                  <div className="font-bold text-[#172033]">授权状态</div>
                  <div className="mt-3 space-y-2 text-slate-600">
                    <div className="flex items-center justify-between gap-3">
                      <span>状态轮询</span>
                      <span className="inline-flex items-center gap-1 font-semibold">
                        {authStatusLoading && !authAuthorized && !authPollingTimedOut ? (
                          <LoaderIcon size={12} className="animate-spin" />
                        ) : null}
                        {authStatusText}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>open_id</span>
                      <span className="max-w-[132px] truncate text-right font-mono">
                        {compactOpenId(authOpenId)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>昵称</span>
                      <span className="max-w-[132px] truncate text-right">
                        {authNickname || "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>接收时间</span>
                      <span className="max-w-[132px] text-right">
                        {formatTime(authReceivedAt)}
                      </span>
                    </div>
                  </div>

                  {authUrlInfo?.auth_url ? (
                    <div className="mt-4">
                      <div className="mb-1 font-semibold text-slate-500">授权 URL</div>
                      <div className="max-h-24 overflow-auto break-all rounded-md bg-slate-50 p-2 font-mono text-[10px] leading-4 text-slate-500">
                        {authUrlInfo.auth_url}
                      </div>
                    </div>
                  ) : null}

                  <div className="mt-4 grid gap-2">
                    <button
                      onClick={() => void refreshAuthStatus()}
                      disabled={authStatusLoading}
                      className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-slate-200 bg-white font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                    >
                      <RefreshCwIcon size={14} className={authStatusLoading ? "animate-spin" : ""} />
                      刷新状态
                    </button>
                    <button
                      onClick={() => void refreshAccountsAfterAuth()}
                      className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-blue-600 font-semibold text-white hover:bg-blue-700"
                    >
                      <RefreshCwIcon size={14} className={loadingAccounts ? "animate-spin" : ""} />
                      我已完成授权，刷新抖音号
                    </button>
                    <button
                      onClick={() => setAuthModalOpen(false)}
                      className="h-9 rounded-md border border-slate-200 bg-white font-semibold text-slate-600 hover:bg-slate-50"
                    >
                      取消
                    </button>
                  </div>
                </aside>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {uploadDialogOpen ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 px-4" role="dialog" aria-modal="true" aria-labelledby="upload-dialog-title">
          <div className="w-full max-w-2xl overflow-hidden rounded-lg bg-white shadow-[0_24px_80px_rgba(15,23,42,0.32)]">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div className="flex items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-emerald-50 text-emerald-600">
                  <ImagePlusIcon size={18} />
                </span>
                <div>
                  <h2 id="upload-dialog-title" className="text-sm font-bold text-[#172033]">上传图片</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    图片上传仅用于获取 image_id，不会自动发送私信。
                  </p>
                </div>
              </div>
              <button
                onClick={() => closeUploadDialog()}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-slate-500 hover:bg-slate-100"
                aria-label="关闭图片上传弹窗"
              >
                <XIcon size={16} />
              </button>
            </div>

            <div className="space-y-4 p-5">
              <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                <div className="font-semibold text-slate-700">
                  {selectedConversation?.nickname || "-"} · {selectedConversation?.open_id || "-"}
                </div>
                <div className="mt-1">支持 jpg/jpeg/png/bmp/webp，单张图片不超过 10MB。</div>
              </div>

              <label className="flex cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-slate-300 bg-white px-4 py-6 text-center hover:border-emerald-300 hover:bg-emerald-50/40">
                <input
                  type="file"
                  accept=".jpg,.jpeg,.png,.bmp,.webp,image/jpeg,image/png,image/bmp,image/webp"
                  onChange={handleUploadFileChange}
                  className="hidden"
                />
                <span className="grid h-10 w-10 place-items-center rounded-md bg-emerald-50 text-emerald-600">
                  <ImagePlusIcon size={18} />
                </span>
                <span className="mt-3 text-sm font-semibold text-slate-800">选择本地图片</span>
                <span className="mt-1 text-xs text-slate-500">
                  不支持 svg/gif，图片不会被自动发送。
                </span>
              </label>

              {uploadFile ? (
                <div className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 sm:grid-cols-3">
                  <span className="min-w-0 truncate">文件：{uploadFile.name}</span>
                  <span>大小：{formatFileSize(uploadFile.size)}</span>
                  <span>格式：{uploadFile.type || fileExtension(uploadFile.name) || "未知"}</span>
                </div>
              ) : null}

              {uploadResult ? (
                <div className="space-y-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-3 text-xs leading-5 text-emerald-800">
                  <div className="font-bold">图片上传成功，已获得 image_id。当前不会自动发送图片。</div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <span className="min-w-0 break-all">image_id：{uploadResult.image_id || "-"}</span>
                    <span>状态：{uploadResult.upload_status || "success"}</span>
                    <span>尺寸：{uploadResult.width || "-"} × {uploadResult.height || "-"}</span>
                    <span>md5：{uploadResult.md5 || "-"}</span>
                  </div>
                  {uploadResult.image_id ? (
                    <button
                      onClick={() => void copyUploadedImageId()}
                      className="inline-flex h-8 items-center gap-2 rounded-md border border-emerald-200 bg-white px-2 text-xs font-semibold text-emerald-700 hover:bg-emerald-50"
                    >
                      <ClipboardIcon size={13} />
                      {uploadImageIdCopied ? "已复制 image_id" : "复制 image_id"}
                    </button>
                  ) : null}
                </div>
              ) : null}

              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-5 text-amber-800">
                上传成功后只展示 image_id，不会调用 /messages/send，也不会把 image_id 自动塞入发送接口。
              </div>

              {uploadError ? (
                <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
                  <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
                  <span>{uploadError}</span>
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-2">
                <button
                  onClick={() => closeUploadDialog()}
                  className="h-9 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                >
                  取消
                </button>
                <button
                  onClick={() => void confirmUploadImage()}
                  disabled={uploadingImage || !uploadFile}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-emerald-600 px-3 text-xs font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {uploadingImage ? <LoaderIcon size={14} className="animate-spin" /> : <ImagePlusIcon size={14} />}
                  确认上传
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
