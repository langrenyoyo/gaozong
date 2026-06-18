import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircleIcon,
  BotIcon,
  CheckIcon,
  ClipboardIcon,
  DownloadIcon,
  LoaderIcon,
  MessageSquareTextIcon,
  PlusIcon,
  QrCodeIcon,
  RefreshCwIcon,
  SearchIcon,
  SparklesIcon,
  XIcon,
  UserRoundIcon,
} from "lucide-react";

import {
  fetchDouyinLiveCheckAccounts,
  fetchDouyinLiveCheckAuthUrl,
  fetchDouyinLiveCheckStatus,
} from "../api/douyinLiveCheck";
import type {
  DouyinLiveCheckAccount,
  DouyinLiveCheckAuthUrlData,
  DouyinLiveCheckStatusData,
} from "../api/types";
import {
  downloadDouyinResource,
  getDouyinAccountAgents,
  getDouyinAccountConversations,
  getDouyinConversationMessages,
  getTrustedReplySuggestion,
  sendDouyinManualMessage,
  type DouyinAccountItem,
  type DouyinAgentItem,
  type DouyinConversationItem,
  type DouyinMessageItem,
  type DouyinUserProfileResponse,
  type ReplySuggestionResponse,
} from "../api/douyinAiCsClient";

const TENANT_ID = "demo_tenant";
const MERCHANT_ID = "demo_bba";

type ConversationFilterKey = "all" | "manual_required" | "high_intent" | "has_contact" | "pending_follow_up";

const CONVERSATION_FILTERS: Array<{ key: ConversationFilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "manual_required", label: "需人工" },
  { key: "high_intent", label: "高意向" },
  { key: "has_contact", label: "已留资" },
  { key: "pending_follow_up", label: "待回访" },
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
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function statusText(value?: string | null) {
  if (value === "active") return "在线";
  if (value === "pending") return "待跟进";
  if (value === "captured") return "已留资";
  if (value === "new") return "新会话";
  return value || "未知";
}

function accountIdFromOpenId(openId: string): number {
  let hash = 0;
  for (let index = 0; index < openId.length; index += 1) {
    hash = (hash * 31 + openId.charCodeAt(index)) >>> 0;
  }
  return hash || 1;
}

function mapAuthorizedAccount(item: DouyinLiveCheckAccount): DouyinAccountItem | null {
  const openId = item.account_open_id || item.open_id;
  if (!openId) return null;
  const numericAccountId = typeof item.account_id === "number" ? item.account_id : null;
  const id = item.douyin_account_id || item.id || numericAccountId || accountIdFromOpenId(openId);
  return {
    id,
    tenant_id: TENANT_ID,
    account_name: item.account_name || item.nickname || `已授权抖音号 ${openId.slice(-4)}`,
    account_open_id: openId,
    status: item.status || (item.is_active === false ? "inactive" : "active"),
    avatar: item.avatar_url || item.avatar || null,
    unread_count: item.unread_count || 0,
    last_active_at: item.last_active_at || item.authorized_at || null,
    source: item.source || null,
    is_authorized: item.is_authorized,
    has_events: item.has_events,
  };
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="grid min-h-[180px] place-items-center px-6 text-center text-xs text-slate-500">
      {text}
    </div>
  );
}

function budgetText(profile: DouyinUserProfileResponse | null) {
  if (!profile) return "-";
  if (profile.budget_min && profile.budget_max) {
    return `${profile.budget_min.toLocaleString()} - ${profile.budget_max.toLocaleString()}`;
  }
  if (profile.budget_min) return `${profile.budget_min.toLocaleString()} 起`;
  if (profile.budget_max) return `${profile.budget_max.toLocaleString()} 内`;
  return "暂无预算";
}

function conversationMatchesFilter(conversation: DouyinConversationItem, filter: ConversationFilterKey) {
  const status = String(conversation.lead_status || "").toLowerCase();
  if (filter === "all") return true;
  if (filter === "manual_required") return status.includes("manual") || status.includes("人工");
  if (filter === "high_intent") return status.includes("high") || status.includes("高意向");
  if (filter === "has_contact") return status.includes("captured") || status.includes("已留资");
  if (filter === "pending_follow_up") return status.includes("pending") || status.includes("待回访") || status.includes("待跟进");
  return true;
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

export default function DouyinAiCsWorkbenchPage() {
  const [accounts, setAccounts] = useState<DouyinAccountItem[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<DouyinConversationItem[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | number | null>(null);
  const [messages, setMessages] = useState<DouyinMessageItem[]>([]);
  const [profile, setProfile] = useState<DouyinUserProfileResponse | null>(null);
  const [reply, setReply] = useState<ReplySuggestionResponse | null>(null);
  const [agents, setAgents] = useState<DouyinAgentItem[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [draftReplyText, setDraftReplyText] = useState("");
  const [sendDialogOpen, setSendDialogOpen] = useState(false);
  const [sendingMessage, setSendingMessage] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [mediaDownloads, setMediaDownloads] = useState<Record<string, MediaDownloadState>>({});
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(false);
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

  const selectedAccount = accounts.find((item) => item.id === selectedAccountId) || null;
  const selectedConversation =
    conversations.find((item) => item.id === selectedConversationId) || null;
  const selectedAgent = agents.find((item) => item.agent_id === selectedAgentId) || null;
  const authCallback = authStatus?.last_oauth_callback || null;
  const authAuthorized = Boolean(authCallback?.open_id);
  const latestMessage = useMemo(() => {
    const inbound = [...messages].reverse().find((item) => item.direction === "inbound");
    return inbound?.content || selectedConversation?.last_message || "";
  }, [messages, selectedConversation]);
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

  const loadAccounts = useCallback(async (preferredOpenId?: string | null) => {
    setLoadingAccounts(true);
    setError(null);
    try {
      const data = await fetchDouyinLiveCheckAccounts();
      const mapped = data.data.items
        .map(mapAuthorizedAccount)
        .filter((item): item is DouyinAccountItem => Boolean(item));
      setAccounts(mapped);
      setAccountListSource(data.data.source || "live_check");
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
      setAccounts([]);
      setSelectedAccountId(null);
      setAccountListSource(null);
      setError(liveCheckErrorMessage(err));
      return [];
    } finally {
      setLoadingAccounts(false);
    }
  }, []);

  const loadConversations = useCallback(async (account: DouyinAccountItem) => {
    setLoadingConversations(true);
    setError(null);
    try {
      const data = await getDouyinAccountConversations(account.id, {
        account_open_id: account.account_open_id,
      });
      setConversations(data.items);
      setSelectedConversationId(data.items[0]?.id || null);
    } catch (err) {
      setConversations([]);
      setSelectedConversationId(null);
      setError(err instanceof Error ? err.message : "会话列表加载失败");
    } finally {
      setLoadingConversations(false);
    }
  }, []);

  const loadAccountAgents = useCallback(async (accountId: number) => {
    setLoadingAgents(true);
    setAgentNotice(null);
    setReply(null);
    try {
      const data = await getDouyinAccountAgents(accountId, {
        tenant_id: TENANT_ID,
        merchant_id: MERCHANT_ID,
      });
      setAgents(data.items);
      if (!data.items.length) {
        setSelectedAgentId(null);
        setAgentNotice("当前抖音号未配置 AI客服 Agent，请先配置后再生成回复建议。");
        return;
      }
      const defaultAgent = data.default_agent_id
        ? data.items.find((item) => item.agent_id === data.default_agent_id)
        : null;
      const nextAgent = defaultAgent || data.items[0];
      setSelectedAgentId(nextAgent.agent_id);
      setAgentNotice(defaultAgent ? null : "未配置默认 Agent，已临时使用第一个可用 Agent。");
    } catch (err) {
      setAgents([]);
      setSelectedAgentId(null);
      setAgentNotice(err instanceof Error ? err.message : "AI客服 Agent 加载失败");
    } finally {
      setLoadingAgents(false);
    }
  }, []);

  const loadConversationDetail = useCallback(async (conversationId: string | number) => {
    setLoadingMessages(true);
    setError(null);
    setReply(null);
    try {
      const messageData = await getDouyinConversationMessages(conversationId, {
        account_open_id: selectedAccount?.account_open_id,
      });
      setMessages(messageData.items);
      setProfile(null);
    } catch (err) {
      setMessages([]);
      setProfile(null);
      setError(err instanceof Error ? err.message : "聊天详情加载失败");
    } finally {
      setLoadingMessages(false);
    }
  }, [selectedAccount?.account_open_id]);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    if (selectedAccount) {
      void loadConversations(selectedAccount);
      void loadAccountAgents(selectedAccount.id);
    } else {
      setConversations([]);
      setSelectedConversationId(null);
      setAgents([]);
      setSelectedAgentId(null);
      setAgentNotice(null);
    }
  }, [loadAccountAgents, loadConversations, selectedAccount, selectedAccountId]);

  useEffect(() => {
    if (selectedConversationId) {
      void loadConversationDetail(selectedConversationId);
    } else {
      setMessages([]);
      setProfile(null);
      setReply(null);
    }
  }, [loadConversationDetail, selectedConversationId]);

  useEffect(() => {
    if (!filteredConversations.length) {
      setSelectedConversationId(null);
      return;
    }
    if (!selectedConversationId || !filteredConversations.some((item) => item.id === selectedConversationId)) {
      setSelectedConversationId(filteredConversations[0].id);
    }
  }, [filteredConversations, selectedConversationId]);

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

  useEffect(() => {
    setReply(null);
  }, [selectedAgentId]);

  useEffect(() => {
    setDraftReplyText(reply?.reply_text || "");
    setSendError(null);
    setSendDialogOpen(false);
    setMediaDownloads({});
  }, [reply?.reply_text, selectedConversationId]);

  async function generateReply() {
    if (!selectedAccount || !selectedConversation || !selectedAgent || !latestMessage) return;
    setGenerating(true);
    setError(null);
    try {
      const data = await getTrustedReplySuggestion(selectedAccount.id, {
        tenant_id: TENANT_ID,
        account_id: selectedAccount.id,
        douyin_account_id: selectedAccount.id,
        agent_id: selectedAgent.agent_id,
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

  function openSendDialog() {
    if (!selectedConversation || !selectedAccount) return;
    setSendError(null);
    setDraftReplyText((current) => current || reply?.reply_text || "");
    setSendDialogOpen(true);
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

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div>
          <h1 className="text-base font-bold text-[#172033]">抖音AI小高客服</h1>
          <p className="mt-1 text-xs text-[#7b8798]">
            多抖音号会话工作台，当前只生成 AI 回复建议，不自动发送私信。
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
          <CheckIcon size={14} />
          auto_send=false
        </div>
      </header>

      <ErrorBanner message={error} />

      <div className="grid min-h-0 flex-1 grid-cols-[260px_320px_minmax(460px,1fr)_260px] overflow-hidden p-4 pt-3">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-l-lg border border-r-0 border-[#dfe5ee] bg-white">
          <div className="flex h-14 items-center justify-between border-b border-[#edf1f6] px-4">
            <div>
              <div className="text-sm font-bold text-[#172033]">抖音号</div>
              <div className="text-[11px] text-slate-500">
                {accountListSource ? "真实授权账号" : `${TENANT_ID} / ${MERCHANT_ID}`}
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
              const isEventSource = account.source === "webhook_events";
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
                    {isEventSource ? (
                      <span className="mt-1 inline-flex max-w-full rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-semibold text-amber-700">
                        事件来源
                      </span>
                    ) : null}
                    <span className="mt-1 block truncate text-[11px] text-slate-500">
                      {isEventSource ? "来自历史私信事件" : `真实授权 · ${statusText(account.status)}`} · {formatTime(account.last_active_at)}
                    </span>
                  </span>
                  {account.unread_count ? (
                    <span className="grid h-5 min-w-5 place-items-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                      {account.unread_count}
                    </span>
                  ) : null}
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
            {loadingConversations ? <EmptyState text="正在加载会话..." /> : null}
            {!loadingConversations && conversations.length === 0 ? <EmptyState text="该抖音号暂无私信会话。" /> : null}
            {!loadingConversations && conversations.length > 0 && filteredConversations.length === 0 ? (
              <EmptyState text="没有符合条件的会话。" />
            ) : null}
            {filteredConversations.map((conversation) => {
              const active = conversation.id === selectedConversationId;
              return (
                <button
                  key={conversation.id}
                  onClick={() => setSelectedConversationId(conversation.id)}
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
          <div className="flex h-14 items-center justify-between border-b border-[#edf1f6] px-5">
            <div className="min-w-0">
              <div className="truncate text-sm font-bold text-[#172033]">
                {selectedConversation?.nickname || "请选择会话"}
              </div>
              <div className="mt-0.5 truncate text-[11px] text-slate-500">
                {profile
                  ? `${profile.brand_preference || "未知品牌"} / ${profile.vehicle_preference || "未知车型"} / ${profile.purchase_intent_level}`
                  : "用户画像加载中"}
              </div>
            </div>
            <span className="rounded-md bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">
              只读建议模式
            </span>
          </div>

          <div className="grid min-h-0 flex-1 grid-rows-[minmax(220px,1fr)_minmax(270px,42%)]">
            <div className="min-h-0 overflow-auto bg-[#f8fafc] px-5 py-4">
              {loadingMessages ? <EmptyState text="正在加载聊天消息..." /> : null}
              {!loadingMessages && messages.length === 0 ? <EmptyState text="暂无消息。" /> : null}
              <div className="space-y-3">
                {messages.map((message) => {
                  const isCustomer = message.direction === "inbound";
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
                      className={`flex ${isCustomer ? "justify-start" : "justify-end"}`}
                    >
                      <div
                        className={`max-w-[72%] rounded-lg px-3 py-2 text-sm leading-6 shadow-sm ${
                          isCustomer ? "bg-white text-slate-800" : "bg-blue-600 text-white"
                        }`}
                      >
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
                        <div className={`mt-1 text-[10px] ${isCustomer ? "text-slate-400" : "text-blue-100"}`}>
                          {isCustomer ? "客户" : "客服"} · {formatTime(message.created_at)}
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
                <div className="flex shrink-0 items-center gap-2">
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
                    disabled={!selectedConversation || !selectedAgent || generating}
                    className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {generating ? <LoaderIcon size={14} className="animate-spin" /> : <SparklesIcon size={14} />}
                    生成回复建议
                  </button>
                </div>
              </div>

              <div className="mb-3 rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-bold text-[#172033]">当前 AI客服</span>
                  {loadingAgents ? (
                    <span className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                      <LoaderIcon size={12} className="animate-spin" />
                      加载中
                    </span>
                  ) : null}
                  <select
                    value={selectedAgentId || ""}
                    onChange={(event) => setSelectedAgentId(event.target.value || null)}
                    disabled={!agents.length || loadingAgents}
                    className="h-8 min-w-[220px] rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-700 outline-none disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
                  >
                    {!agents.length ? <option value="">未配置 Agent</option> : null}
                    {agents.map((agent) => (
                      <option key={agent.agent_id} value={agent.agent_id}>
                        {agent.agent_name} · {agent.agent_category}
                      </option>
                    ))}
                  </select>
                </div>
                {selectedAgent ? (
                  <div className="mt-2 grid gap-2 text-[11px] text-slate-600 md:grid-cols-3">
                    <span>分类：{selectedAgent.agent_category}</span>
                    <span>风格：{selectedAgent.reply_style}</span>
                    <span>{selectedAgent.is_default ? "默认 Agent" : "手动选择 Agent"}</span>
                    <span className="md:col-span-3">业务范围：{selectedAgent.business_scope}</span>
                  </div>
                ) : null}
                {agentNotice ? (
                  <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-5 text-amber-800">
                    {agentNotice}
                  </div>
                ) : null}
              </div>

              {reply ? (
                <div className="space-y-3">
                  {reply.agent_id ? (
                    <div className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-800">
                      Agent：{reply.agent_name || reply.agent_id}
                      {reply.agent_category ? ` · 分类：${reply.agent_category}` : ""}
                    </div>
                  ) : null}
                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-800">
                    {reply.reply_text || "暂无建议内容"}
                  </div>
                  <div className="grid gap-2 text-xs text-slate-600 sm:grid-cols-5">
                    <span>manual_required: {String(reply.manual_required)}</span>
                    <span>llm_used: {String(reply.llm_used)}</span>
                    <span>rag_used: {String(reply.rag_used)}</span>
                    <span className="font-bold text-amber-700">auto_send: {String(reply.auto_send)}</span>
                    <span>chunks: {reply.source_chunks?.length || 0}</span>
                  </div>
                  {reply.warnings?.length ? (
                    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      {reply.warnings.join("，")}
                    </div>
                  ) : null}
                  {reply.source_chunks?.length ? (
                    <div className="rounded-md border border-slate-200">
                      <div className="border-b border-slate-200 px-3 py-2 text-xs font-bold text-slate-600">
                        来源知识
                      </div>
                      <div className="divide-y divide-slate-100">
                        {reply.source_chunks.map((chunk, index) => (
                          <div key={`${chunk.document_id}-${chunk.chunk_id}-${index}`} className="px-3 py-2 text-xs text-slate-600">
                            #{chunk.chunk_id} · {chunk.title} · score {chunk.score}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-xs text-slate-500">
                      <MessageSquareTextIcon size={14} />
                      暂无 RAG 来源 chunk。
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => void copyReply()}
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      <ClipboardIcon size={14} />
                      {copied ? "已复制" : "复制回复"}
                    </button>
                  </div>
                </div>
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
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-sm font-bold text-[#172033]">{selectedConversation.nickname}</div>
                <div className="mt-1 text-[11px] text-slate-500">{selectedConversation.open_id}</div>
              </div>

              <div className="mt-4 space-y-3 text-xs">
                <div>
                  <div className="font-semibold text-slate-500">意向等级</div>
                  <div className="mt-1 rounded-md bg-white px-3 py-2 text-slate-800 ring-1 ring-slate-200">
                    {profile?.purchase_intent_level || "暂无客户画像"}
                  </div>
                </div>
                <div>
                  <div className="font-semibold text-slate-500">品牌 / 车型</div>
                  <div className="mt-1 rounded-md bg-white px-3 py-2 text-slate-800 ring-1 ring-slate-200">
                    {profile ? `${profile.brand_preference || "未知品牌"} / ${profile.vehicle_preference || "未知车型"}` : "暂无客户画像"}
                  </div>
                </div>
                <div>
                  <div className="font-semibold text-slate-500">预算</div>
                  <div className="mt-1 rounded-md bg-white px-3 py-2 text-slate-800 ring-1 ring-slate-200">
                    {budgetText(profile)}
                  </div>
                </div>
                <div>
                  <div className="font-semibold text-slate-500">联系方式/留资状态</div>
                  <div className="mt-1 rounded-md bg-white px-3 py-2 text-slate-800 ring-1 ring-slate-200">
                    {profile?.lead_capture_suggested || selectedConversation.lead_status === "captured"
                      ? "建议引导留资或已留资"
                      : "暂无联系方式"}
                  </div>
                </div>
                <div>
                  <div className="font-semibold text-slate-500">最近跟进建议</div>
                  <div className="mt-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 leading-5 text-amber-800">
                    {profile?.lead_capture_suggested
                      ? "客户意向较明确，建议复制 AI 回复后由人工确认，引导留下联系方式。"
                      : "先确认客户预算、品牌和车型偏好，再决定是否引导留资。"}
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
    </section>
  );
}
