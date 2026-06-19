import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircleIcon,
  BotIcon,
  CheckIcon,
  ClipboardIcon,
  DownloadIcon,
  ImagePlusIcon,
  LoaderIcon,
  PaperclipIcon,
  PlusIcon,
  QrCodeIcon,
  RefreshCwIcon,
  SearchIcon,
  ShieldCheckIcon,
  SmileIcon,
  SparklesIcon,
  Trash2Icon,
  UnlinkIcon,
  VideoIcon,
  XIcon,
  UserRoundIcon,
} from "lucide-react";

import { ReplyDecisionPanel } from "../components/douyin-ai-cs/ReplyDecisionPanel";
import {
  bindAuthorizedOpenId,
  fetchDouyinLiveCheckAuthUrl,
  fetchDouyinLiveCheckStatus,
} from "../api/douyinLiveCheck";
import { formatDateTimeLocal } from "../lib/datetime";
import type {
  DouyinLiveCheckAuthUrlData,
  DouyinLiveCheckStatusData,
} from "../api/types";
import {
  bindAgentToDouyinAccount,
  cancelDouyinAccountAuthorization,
  deleteDouyinAccount,
  downloadDouyinResource,
  getDouyinAccountAgents,
  getDouyinAccountConversations,
  getDouyinConversationProfileFrom9000,
  getDouyinConversationMessages,
  getTrustedReplySuggestion,
  listDouyinAccounts,
  sendDouyinManualMessage,
  unbindAgentFromDouyinAccount,
  uploadDouyinImage,
  type DouyinAccountItem,
  type DouyinAgentItem,
  type DouyinConversationItem,
  type DouyinConversationProfile,
  type DouyinMessageItem,
  type ReplySuggestionResponse,
  type UploadDouyinImageResponse,
} from "../api/douyinAiCsClient";

const MAX_UPLOAD_IMAGE_BYTES = 10 * 1024 * 1024;
const ALLOWED_UPLOAD_IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/bmp", "image/webp"];
const ALLOWED_UPLOAD_IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".bmp", ".webp"];
const UPLOAD_IMAGE_VALIDATION_MESSAGE =
  "请选择 jpg/jpeg/png/bmp/webp 格式图片，且大小不超过 10MB。";

type ConversationFilterKey = "all" | "manual_required" | "high_intent" | "retained_contact" | "follow_up";
type ChatAssistMode = "ai_suggestion" | "manual_takeover";

const CONVERSATION_FILTERS: Array<{ key: ConversationFilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "manual_required", label: "需人工" },
  { key: "high_intent", label: "高意向" },
  { key: "retained_contact", label: "已留资" },
  { key: "follow_up", label: "待回访" },
];

const LIVE_CHECK_DISABLED_MESSAGE =
  "抖音授权联调未开启，请在后端配置 DY_LIVE_CHECK_ENABLED=true 后重启服务。";

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
    return `抖音授权配置不完整：${detail}`;
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
  if (value === "pending") return "待跟进";
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

function conversationMatchesFilter(conversation: DouyinConversationItem, filter: ConversationFilterKey) {
  if (filter === "all") return true;
  return Array.isArray(conversation.tags) && conversation.tags.includes(filter);
}

function conversationTagText(tag: string) {
  if (tag === "manual_required") return "需人工";
  if (tag === "high_intent") return "高意向";
  if (tag === "retained_contact") return "已留资";
  if (tag === "follow_up") return "待回访";
  return tag;
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

function messageRoleLabel(message: DouyinMessageItem) {
  if (isCustomerMessage(message)) return "客户";
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

function chatModeTitle(mode: ChatAssistMode) {
  return mode === "manual_takeover" ? "人工接管中" : "AI正在根据车型和留资意向生成回复建议";
}

function chatModeSubtitle(mode: ChatAssistMode) {
  return mode === "manual_takeover"
    ? "客服确认后发送，AI建议仍可复制参考"
    : "不会自动发送，需人工确认";
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

function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="mx-4 mt-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
      <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
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

function bindingStatusText(value?: string | null): string {
  if (value === "active") return "已绑定";
  if (value === "none") return "未绑定";
  if (value === "invalid") return "绑定失效";
  if (value === "deleted") return "绑定已删除";
  if (value === "unbound") return "已解绑";
  return value || "未绑定";
}

function agentStatusText(value?: string | null): string {
  if (value === "active") return "已启用";
  if (value === "inactive") return "未启用";
  if (value === "deleted") return "已删除";
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
  const [reply, setReply] = useState<ReplySuggestionResponse | null>(null);
  const [agents, setAgents] = useState<DouyinAgentItem[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [bindingBusy, setBindingBusy] = useState(false);
  const [bindingNotice, setBindingNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [draftReplyText, setDraftReplyText] = useState("");
  const [sendDialogOpen, setSendDialogOpen] = useState(false);
  const [sendingMessage, setSendingMessage] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [mediaDownloads, setMediaDownloads] = useState<Record<string, MediaDownloadState>>({});
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadedImageData | null>(null);
  const [uploadImageIdCopied, setUploadImageIdCopied] = useState(false);
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [agentNotice, setAgentNotice] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
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
  const [chatAssistMode, setChatAssistMode] = useState<ChatAssistMode>("ai_suggestion");
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
  const agentsCacheRef = useRef<Record<string, DouyinAgentItem[]>>({});
  const messagesCacheRef = useRef<Record<string, DouyinMessageItem[]>>({});
  const profileCacheRef = useRef<Record<string, DouyinConversationProfile | null>>({});
  const readWatermarksRef = useRef<Record<string, ConversationReadWatermark>>({});
  const selectedAccountOpenIdRef = useRef<string | null>(null);
  const selectedConversationIdRef = useRef<string | number | null>(null);
  const accountRequestSeqRef = useRef(0);
  const conversationRequestSeqRef = useRef(0);
  const agentsRequestSeqRef = useRef(0);
  const detailRequestSeqRef = useRef(0);

  const selectedAccount = accounts.find((item) => item.id === selectedAccountId) || null;
  const selectedConversation =
    conversations.find((item) => item.id === selectedConversationId) || null;
  const selectedAgent = agents.find((item) => item.agent_id === selectedAgentId) || null;
  const boundAgent = selectedAccount?.bound_agent_id
    ? agents.find((item) => item.agent_id === selectedAccount.bound_agent_id) || null
    : null;
  const activeBindingReady = hasActiveAgentBinding(selectedAccount);
  const authCallback = authStatus?.last_oauth_callback || null;
  const authAuthorized = Boolean(authCallback?.open_id);
  const latestMessage = useMemo(() => {
    const inbound = [...messages].reverse().find((item) => item.direction === "inbound");
    return inbound?.content || selectedConversation?.last_message || "";
  }, [messages, selectedConversation]);

  useEffect(() => {
    selectedAccountOpenIdRef.current = selectedAccount?.account_open_id || null;
  }, [selectedAccount?.account_open_id]);

  useEffect(() => {
    selectedConversationIdRef.current = selectedConversationId;
  }, [selectedConversationId]);

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
    try {
      const data = await getDouyinAccountConversations(account.id, {
        account_open_id: accountOpenId,
      });
      if (
        conversationRequestSeqRef.current !== requestSeq ||
        selectedAccountOpenIdRef.current !== accountOpenId
      ) {
        return data.items;
      }
      const mergedItems = applyReadWatermarks(accountOpenId, data.items, readWatermarksRef.current);
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

  const loadAccountAgents = useCallback(async (accountOpenId: string) => {
    const cached = agentsCacheRef.current[accountOpenId];
    const requestSeq = agentsRequestSeqRef.current + 1;
    agentsRequestSeqRef.current = requestSeq;
    if (cached) setAgents(cached);
    if (!cached) setLoadingAgents(true);
    setAgentNotice(null);
    setReply(null);
    try {
      const data = await getDouyinAccountAgents(accountOpenId);
      if (agentsRequestSeqRef.current !== requestSeq || selectedAccountOpenIdRef.current !== accountOpenId) return;
      agentsCacheRef.current[accountOpenId] = data.items;
      setAgents(data.items);
      if (!data.items.length) {
        setSelectedAgentId(null);
        setAgentNotice("当前商户未配置可选智能体，请先配置后再绑定企业号。");
        return;
      }
      setAgentNotice(null);
    } catch (err) {
      if (agentsRequestSeqRef.current !== requestSeq || selectedAccountOpenIdRef.current !== accountOpenId) return;
      if (!cached) {
        setAgents([]);
        setSelectedAgentId(null);
      }
      setAgentNotice(err instanceof Error ? err.message : "智能体列表加载失败");
    } finally {
      if (agentsRequestSeqRef.current === requestSeq && selectedAccountOpenIdRef.current === accountOpenId) {
        setLoadingAgents(false);
      }
    }
  }, []);

  const loadConversationDetail = useCallback(async (
    conversationId: string | number,
    options?: { background?: boolean },
  ) => {
    const accountOpenId = selectedAccount?.account_open_id || null;
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
    if (!options?.background) setReply(null);
    try {
      const messageData = await getDouyinConversationMessages(conversationId, {
        account_open_id: accountOpenId || undefined,
      });
      if (
        detailRequestSeqRef.current !== requestSeq ||
        selectedAccountOpenIdRef.current !== accountOpenId ||
        selectedConversationIdRef.current !== conversationId
      ) {
        return;
      }
      if (cacheKey) messagesCacheRef.current[cacheKey] = messageData.items;
      setMessages(messageData.items);
      if (selectedAccount) {
        try {
          const profileData = await getDouyinConversationProfileFrom9000(selectedAccount.id, conversationId, {
            account_open_id: selectedAccount.account_open_id,
          });
          if (
            detailRequestSeqRef.current !== requestSeq ||
            selectedAccountOpenIdRef.current !== accountOpenId ||
            selectedConversationIdRef.current !== conversationId
          ) {
            return;
          }
          if (cacheKey) profileCacheRef.current[cacheKey] = profileData;
          setProfile(profileData);
        } catch (profileErr) {
          if (
            detailRequestSeqRef.current !== requestSeq ||
            selectedAccountOpenIdRef.current !== accountOpenId ||
            selectedConversationIdRef.current !== conversationId
          ) {
            return;
          }
          if (cacheKey) profileCacheRef.current[cacheKey] = null;
          setProfile(null);
          setProfileError(profileErr instanceof Error ? profileErr.message : "客户画像加载失败");
        }
      } else {
        setProfile(null);
      }
    } catch (err) {
      if (
        detailRequestSeqRef.current !== requestSeq ||
        selectedAccountOpenIdRef.current !== accountOpenId ||
        selectedConversationIdRef.current !== conversationId
      ) {
        return;
      }
      if (!cachedMessages) setMessages([]);
      if (cachedProfile === undefined) setProfile(null);
      setError(err instanceof Error ? err.message : "聊天详情加载失败");
    } finally {
      if (
        detailRequestSeqRef.current === requestSeq &&
        selectedAccountOpenIdRef.current === accountOpenId &&
        selectedConversationIdRef.current === conversationId
      ) {
        setLoadingMessages(false);
        setLoadingProfile(false);
      }
    }
  }, [selectedAccount]);

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

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    if (selectedAccount) {
      const cachedConversations = conversationsCacheRef.current[selectedAccount.account_open_id];
      const cachedAgents = agentsCacheRef.current[selectedAccount.account_open_id];
      if (cachedConversations) setConversations(cachedConversations);
      if (cachedAgents) setAgents(cachedAgents);
      void loadConversations(selectedAccount, {
        skipDefaultSelection: Boolean(conversationJumpParams && !conversationJumpHandled),
        background: Boolean(cachedConversations),
      });
      void loadAccountAgents(selectedAccount.account_open_id);
      setSelectedAgentId(selectedAccount.bound_agent_id || null);
      setBindingNotice(null);
    } else {
      setConversations([]);
      setSelectedConversationId(null);
      setAgents([]);
      setSelectedAgentId(null);
      setAgentNotice(null);
      setBindingNotice(null);
    }
  }, [conversationJumpHandled, conversationJumpParams, loadAccountAgents, loadConversations, selectedAccount, selectedAccountId]);

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
    } else {
      if (!conversations.length) {
        setMessages([]);
        setProfile(null);
      }
      setProfileError(null);
      setLoadingProfile(false);
      setReply(null);
    }
  }, [conversations, loadConversationDetail, markConversationReadLocally, selectedConversationId]);

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
      const currentAccount = selectedAccount;
      const currentConversationId = selectedConversationIdRef.current;
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
      }
    };

    const timer = window.setInterval(() => {
      void poll();
    }, 8000);
    return () => window.clearInterval(timer);
  }, [loadConversationDetail, loadConversations, selectedAccount]);

  const refreshAuthStatus = useCallback(async () => {
    setAuthStatusLoading(true);
    try {
      const result = await fetchDouyinLiveCheckStatus();
      setAuthStatus(result.data);
      if (result.data.last_oauth_callback?.error) {
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
    try {
      const [authUrlResult] = await Promise.all([
        fetchDouyinLiveCheckAuthUrl(),
        refreshAuthStatus(),
      ]);
      setAuthUrlInfo(authUrlResult.data);
      if (!authUrlResult.data.configured || !authUrlResult.data.auth_url) {
        setAuthError(
          authUrlResult.data.missing.length
            ? `抖音授权配置不完整：${authUrlResult.data.missing.join("，")}`
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
    await loadAccounts(authCallback?.open_id);
    setAuthAccountRefreshDone(true);
  }

  useEffect(() => {
    if (!authModalOpen) return undefined;
    const timer = window.setInterval(() => {
      void refreshAuthStatus();
    }, 3500);
    return () => window.clearInterval(timer);
  }, [authModalOpen, refreshAuthStatus]);

  useEffect(() => {
    if (!authModalOpen || !authAuthorized || authAccountRefreshDone) return;
    void refreshAccountsAfterAuth();
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
    setReply(null);
  }, [selectedAccount?.bound_agent_id]);

  useEffect(() => {
    setDraftReplyText(reply?.reply_text || "");
    setSendError(null);
    setSendDialogOpen(false);
    setMediaDownloads({});
    setUploadDialogOpen(false);
    setUploadFile(null);
    setUploadError(null);
    setUploadResult(null);
    setUploadImageIdCopied(false);
  }, [reply?.reply_text, selectedConversationId]);

  async function generateReply() {
    if (!selectedAccount || !selectedConversation || !latestMessage) return;
    if (!activeBindingReady || !selectedAccount.bound_agent_id) {
      setError("请先为当前企业号绑定已启用的智能体，再生成回复建议。");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const data = await getTrustedReplySuggestion(selectedAccount.id, {
        account_id: selectedAccount.id,
        douyin_account_id: selectedAccount.id,
        agent_id: selectedAccount.bound_agent_id,
        latest_message: latestMessage,
      });
      setReply(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成回复建议失败");
    } finally {
      setGenerating(false);
    }
  }

  async function copyReply() {
    if (!reply?.reply_text) return;
    await navigator.clipboard.writeText(reply.reply_text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  async function refreshAccountsKeepingSelection(accountOpenId?: string | null) {
    const refreshed = await loadAccounts(accountOpenId || selectedAccount?.account_open_id || null);
    if (!accountOpenId && selectedAccount?.account_open_id) {
      const next = refreshed.find((item) => item.account_open_id === selectedAccount.account_open_id);
      setSelectedAgentId(next?.bound_agent_id || null);
    }
    return refreshed;
  }

  async function saveAgentBinding() {
    if (!selectedAccount || !selectedAgentId) {
      setBindingNotice("请选择要绑定的智能体后再保存。");
      return;
    }
    setBindingBusy(true);
    setBindingNotice(null);
    setError(null);
    try {
      await bindAgentToDouyinAccount(selectedAccount.account_open_id, selectedAgentId);
      await refreshAccountsKeepingSelection(selectedAccount.account_open_id);
      setReply(null);
      setBindingNotice("绑定已保存。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存绑定失败");
    } finally {
      setBindingBusy(false);
    }
  }

  async function unbindAgent() {
    if (!selectedAccount?.bound_agent_id) return;
    setBindingBusy(true);
    setBindingNotice(null);
    setError(null);
    try {
      await unbindAgentFromDouyinAccount(selectedAccount.account_open_id);
      await refreshAccountsKeepingSelection(selectedAccount.account_open_id);
      setSelectedAgentId(null);
      setReply(null);
      setBindingNotice("已解绑当前企业号智能体。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "解绑失败");
    } finally {
      setBindingBusy(false);
    }
  }

  async function cancelAuthorization() {
    if (!selectedAccount) return;
    const confirmed = window.confirm(`确认取消企业号“${selectedAccount.account_name}”的授权吗？取消后将禁用回复建议。`);
    if (!confirmed) return;
    setBindingBusy(true);
    setBindingNotice(null);
    setError(null);
    try {
      await cancelDouyinAccountAuthorization(selectedAccount.account_open_id);
      await refreshAccountsKeepingSelection(selectedAccount.account_open_id);
      setSelectedAgentId(null);
      setReply(null);
      setBindingNotice("企业号授权已取消，绑定状态已失效。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "取消授权失败");
    } finally {
      setBindingBusy(false);
    }
  }

  async function deleteSelectedAccount() {
    if (!selectedAccount) return;
    const confirmed = window.confirm(`确认删除企业号“${selectedAccount.account_name}”吗？删除后当前会话和绑定展示会被清空。`);
    if (!confirmed) return;
    const deletingOpenId = selectedAccount.account_open_id;
    setBindingBusy(true);
    setBindingNotice(null);
    setError(null);
    try {
      await deleteDouyinAccount(deletingOpenId);
      const refreshed = await loadAccounts();
      if (!refreshed.some((item) => item.account_open_id === deletingOpenId)) {
        setConversations([]);
        setSelectedConversationId(null);
        setMessages([]);
        setProfile(null);
        setReply(null);
        setSelectedAgentId(null);
        setBindingNotice("企业号已删除。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除企业号失败");
    } finally {
      setBindingBusy(false);
    }
  }

  function openSendDialog() {
    if (!selectedConversation || !selectedAccount) return;
    setSendError(null);
    setDraftReplyText((current) => current || reply?.reply_text || "");
    setSendDialogOpen(true);
  }

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
        scene: "im_reply_msg",
      });
      setSendDialogOpen(false);
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

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div>
          <h1 className="text-base font-bold text-[#172033]">抖音AI小高客服</h1>
          <p className="mt-1 text-xs text-[#7b8798]">
            多抖音号会话工作台，当前只生成 AI 回复建议，不自动发送私信。
          </p>
        </div>
        <div className="flex max-w-[460px] items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          <ShieldCheckIcon size={15} className="mt-0.5 shrink-0" />
          <span>当前为安全建议模式：AI只生成回复建议，不会自动发送；所有发送必须由客服人工确认。</span>
        </div>
      </header>

      <ErrorBanner message={error} />

      <div className="grid min-h-0 flex-1 grid-cols-[260px_320px_minmax(460px,1fr)_260px] overflow-hidden p-4 pt-3">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-l-lg border border-r-0 border-[#dfe5ee] bg-white">
          <div className="flex h-14 items-center justify-between border-b border-[#edf1f6] px-4">
            <div>
              <div className="text-sm font-bold text-[#172033]">抖音号</div>
              <div className="text-[11px] text-slate-500">
                {accountListSource ? "正式企业号绑定" : "企业号绑定"}
              </div>
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
              <EmptyState text="暂无抖音号：未发现授权账号或历史私信事件，请扫码授权。" />
            ) : null}
            {accounts.map((account) => {
              const active = account.id === selectedAccountId;
              return (
                <button
                  key={account.id}
                  onClick={() => setSelectedAccountId(account.id)}
                  className={`mb-2 flex w-full items-center gap-3 rounded-md border px-3 py-3 text-left transition ${
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
                      {account.main_account_id || account.account_open_id} · {account.bound_agent_name || "未绑定智能体"}
                    </span>
                  </span>
                  {account.unread_count ? (
                    <span className="grid h-5 min-w-5 place-items-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                      {account.unread_count}
                    </span>
                  ) : null}
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                      account.binding_status === "active"
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-slate-100 text-slate-500"
                    }`}
                  >
                    {bindingStatusText(account.binding_status)}
                  </span>
                </button>
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
              <EmptyState text="没有符合条件的会话。" />
            ) : null}
            {filteredConversations.map((conversation) => {
              const active = conversation.id === selectedConversationId;
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
                  {conversation.tags?.length ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {conversation.tags.map((tag) => (
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
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                      {statusText(conversation.lead_status)}
                    </span>
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
                  chatAssistMode === "manual_takeover" ? "text-amber-700" : "text-blue-700"
                }`}
              >
                <span
                  className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                    chatAssistMode === "manual_takeover" ? "bg-amber-500" : "bg-blue-500"
                  }`}
                />
                <span>
                  <span className="font-bold">{chatModeTitle(chatAssistMode)}</span>
                  <span className="ml-1 text-slate-500">{chatModeSubtitle(chatAssistMode)}</span>
                </span>
              </div>
            </div>
            <div className="flex shrink-0 overflow-hidden rounded-md border border-slate-200 bg-slate-50 p-1">
              <button
                type="button"
                onClick={() => setChatAssistMode("ai_suggestion")}
                className={`h-8 rounded px-3 text-[11px] font-semibold ${
                  chatAssistMode === "ai_suggestion"
                    ? "bg-blue-600 text-white shadow-sm"
                    : "text-slate-600 hover:bg-white"
                }`}
              >
                AI建议模式
              </button>
              <button
                type="button"
                onClick={() => setChatAssistMode("manual_takeover")}
                className={`h-8 rounded px-3 text-[11px] font-semibold ${
                  chatAssistMode === "manual_takeover"
                    ? "bg-amber-500 text-white shadow-sm"
                    : "text-slate-600 hover:bg-white"
                }`}
              >
                人工接管
              </button>
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
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="grid h-8 w-8 place-items-center rounded-md bg-blue-50 text-blue-600">
                    <BotIcon size={16} />
                  </span>
                  <div>
                    <div className="text-sm font-bold text-[#172033]">AI 回复建议</div>
                    <div className="text-[11px] text-slate-500">基于最新客户消息与 RAG 命中生成</div>
                  </div>
                </div>
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
                  {selectedConversation ? (
                    <button
                      onClick={() => openSendDialog()}
                      disabled={!selectedAccount}
                      className="h-9 rounded-md border border-blue-200 bg-blue-50 px-3 text-xs font-semibold text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400"
                    >
                      人工确认发送
                    </button>
                  ) : null}
                  <button
                    onClick={() => void generateReply()}
                    disabled={!selectedConversation || !activeBindingReady || generating}
                    className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {generating ? <LoaderIcon size={14} className="animate-spin" /> : <SparklesIcon size={14} />}
                    生成回复建议
                  </button>
                </div>
              </div>

              <div className="mb-3 rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-bold text-[#172033]">企业号绑定智能体</span>
                  {loadingAgents ? (
                    <span className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                      <LoaderIcon size={12} className="animate-spin" />
                      加载中
                    </span>
                  ) : null}
                  <select
                    value={selectedAgentId || ""}
                    onChange={(event) => setSelectedAgentId(event.target.value || null)}
                    disabled={!selectedAccount || !agents.length || loadingAgents || bindingBusy}
                    className="h-8 min-w-[220px] rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-700 outline-none disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
                  >
                    <option value="">{agents.length ? "请选择 Agent" : "未配置 Agent"}</option>
                    {agents.map((agent) => (
                      <option key={agent.agent_id} value={agent.agent_id}>
                        {agent.agent_name} · {agent.agent_category || "默认客服"}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => void saveAgentBinding()}
                    disabled={!selectedAccount || !selectedAgentId || bindingBusy}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md bg-blue-600 px-2.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {bindingBusy ? <LoaderIcon size={13} className="animate-spin" /> : <CheckIcon size={13} />}
                    保存绑定
                  </button>
                  <button
                    onClick={() => void unbindAgent()}
                    disabled={!selectedAccount?.bound_agent_id || bindingBusy}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <UnlinkIcon size={13} />
                    解绑
                  </button>
                  <button
                    onClick={() => void cancelAuthorization()}
                    disabled={!selectedAccount || bindingBusy || selectedAccount.authorization_status !== "authorized"}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 text-xs font-semibold text-amber-700 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <XIcon size={13} />
                    取消授权
                  </button>
                  <button
                    onClick={() => void deleteSelectedAccount()}
                    disabled={!selectedAccount || bindingBusy}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-red-200 bg-red-50 px-2.5 text-xs font-semibold text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Trash2Icon size={13} />
                    删除企业号
                  </button>
                </div>
                <div className="mt-2 grid gap-2 text-[11px] text-slate-600 md:grid-cols-3">
                  <span>授权状态：{authorizationStatusText(selectedAccount?.authorization_status)}</span>
                  <span>绑定状态：{bindingStatusText(selectedAccount?.binding_status)}</span>
                  <span>智能体状态：{agentStatusText(selectedAccount?.bound_agent_status)}</span>
                  <span className="md:col-span-3">
                    当前绑定：
                    {selectedAccount?.bound_agent_id
                      ? `${selectedAccount.bound_agent_name || boundAgent?.agent_name || selectedAccount.bound_agent_id} / ${selectedAccount.bound_agent_id}`
                      : "未绑定智能体"}
                  </span>
                </div>
                {selectedAgent ? (
                  <div className="mt-2 grid gap-2 text-[11px] text-slate-600 md:grid-cols-3">
                    <span>分类：{selectedAgent.agent_category}</span>
                    <span>风格：{selectedAgent.reply_style}</span>
                    <span>{selectedAgent.agent_id === selectedAccount?.bound_agent_id ? "当前已绑定" : "待保存选择"}</span>
                    <span className="md:col-span-3">业务范围：{selectedAgent.business_scope}</span>
                  </div>
                ) : null}
                {!activeBindingReady ? (
                  <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-5 text-amber-800">
                    当前企业号未绑定已启用智能体，生成回复建议已禁用。请选择智能体并点击“保存绑定”。
                  </div>
                ) : null}
                {bindingNotice ? (
                  <div className="mt-2 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-[11px] leading-5 text-emerald-800">
                    {bindingNotice}
                  </div>
                ) : null}
                {agentNotice ? (
                  <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-5 text-amber-800">
                    {agentNotice}
                  </div>
                ) : null}
              </div>

              {reply ? (
                <ReplyDecisionPanel
                  reply={reply}
                  copied={copied}
                  onCopy={() => void copyReply()}
                  onManualSend={() => openSendDialog()}
                  manualSendDisabled={!selectedConversation || !selectedAccount}
                />
              ) : (
                <EmptyState text="选择会话后点击生成回复建议。页面不会自动发送私信。" />
              )}
            </div>
          </div>
        </section>

        <aside className="flex min-h-0 flex-col overflow-hidden rounded-r-lg border border-[#dfe5ee] bg-white">
          <div className="flex h-14 items-center gap-2 border-b border-[#edf1f6] px-4">
            <span className="grid h-8 w-8 place-items-center rounded-md bg-blue-50 text-blue-600">
              <UserRoundIcon size={16} />
            </span>
            <div>
              <div className="text-sm font-bold text-[#172033]">客户画像</div>
              <div className="text-[11px] text-slate-500">会话辅助信息</div>
            </div>
          </div>
          {selectedConversation ? (
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
                      <span className="text-right">{profileFieldText(profile?.lead?.status || selectedConversation.lead_status)}</span>
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
            <EmptyState text="暂无客户画像" />
          )}
        </aside>
      </div>

      {authModalOpen ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 px-4">
          <div className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-white shadow-[0_24px_80px_rgba(15,23,42,0.32)]">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div className="flex items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-blue-50 text-blue-600">
                  <QrCodeIcon size={18} />
                </span>
                <div>
                  <h2 className="text-sm font-bold text-[#172033]">添加抖音号</h2>
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
                  已检测到授权回调：{authCallback?.nick_name || "未返回昵称"} / {authCallback?.open_id}
                  {authAccountRefreshDone ? "。抖音号列表已刷新。" : "。正在刷新抖音号列表..."}
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
                      暂无可展示的授权页面，请检查 9000 授权配置。
                    </div>
                  )}
                </div>

                <aside className="rounded-md border border-slate-200 bg-white p-3 text-xs">
                  <div className="font-bold text-[#172033]">授权状态</div>
                  <div className="mt-3 space-y-2 text-slate-600">
                    <div className="flex items-center justify-between gap-3">
                      <span>状态轮询</span>
                      <span className="inline-flex items-center gap-1 font-semibold">
                        {authStatusLoading ? <LoaderIcon size={12} className="animate-spin" /> : null}
                        {authAuthorized ? "已授权" : "授权中"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>open_id</span>
                      <span className="max-w-[132px] truncate text-right font-mono">
                        {authCallback?.open_id || "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>昵称</span>
                      <span className="max-w-[132px] truncate text-right">
                        {authCallback?.nick_name || "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>接收时间</span>
                      <span className="max-w-[132px] text-right">
                        {formatTime(authCallback?.received_at)}
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

      {sendDialogOpen ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 px-4">
          <div className="w-full max-w-2xl overflow-hidden rounded-lg bg-white shadow-[0_24px_80px_rgba(15,23,42,0.32)]">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div>
                <h2 className="text-sm font-bold text-[#172033]">人工确认发送</h2>
                <p className="mt-1 text-xs text-slate-500">
                  仅在你确认后发送，后端会强制按人工确认链路处理。
                </p>
              </div>
              <button
                onClick={() => setSendDialogOpen(false)}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-slate-500 hover:bg-slate-100"
                aria-label="关闭发送确认弹窗"
              >
                <XIcon size={16} />
              </button>
            </div>

            <div className="space-y-4 p-5">
              <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                <div className="font-semibold text-slate-700">
                  {selectedConversation?.nickname || "-"} · {selectedConversation?.open_id || "-"}
                </div>
                <div className="mt-1">
                  conversation_short_id：{selectedConversation?.conversation_short_id ? String(selectedConversation.conversation_short_id) : "缺失"}
                </div>
              </div>

              <label className="block">
                <div className="mb-2 text-xs font-semibold text-slate-700">发送内容</div>
                <textarea
                  value={draftReplyText}
                  onChange={(event) => setDraftReplyText(event.target.value)}
                  rows={7}
                  className="w-full resize-none rounded-md border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-800 outline-none ring-0 placeholder:text-slate-400 focus:border-blue-300"
                  placeholder="请输入要发送的文本内容"
                />
              </label>

              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-5 text-amber-800">
                发送动作由人工触发，不会携带 auto_send 字段。
              </div>

              {sendError ? (
                <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
                  <AlertCircleIcon size={15} className="mt-0.5 shrink-0" />
                  <span>{sendError}</span>
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-2">
                <button
                  onClick={() => setSendDialogOpen(false)}
                  className="h-9 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                >
                  取消
                </button>
                <button
                  onClick={() => void confirmManualSend()}
                  disabled={sendingMessage}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {sendingMessage ? <LoaderIcon size={14} className="animate-spin" /> : null}
                  确认发送
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {uploadDialogOpen ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 px-4">
          <div className="w-full max-w-2xl overflow-hidden rounded-lg bg-white shadow-[0_24px_80px_rgba(15,23,42,0.32)]">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div className="flex items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-emerald-50 text-emerald-600">
                  <ImagePlusIcon size={18} />
                </span>
                <div>
                  <h2 className="text-sm font-bold text-[#172033]">上传图片</h2>
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
