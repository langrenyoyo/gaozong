import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircleIcon,
  BotIcon,
  CheckIcon,
  ClipboardIcon,
  LoaderIcon,
  MessageSquareTextIcon,
  RefreshCwIcon,
  SearchIcon,
  SparklesIcon,
  UserRoundIcon,
} from "lucide-react";

import {
  getDouyinAccountConversations,
  getDouyinAccounts,
  getDouyinConversationMessages,
  getDouyinConversationProfile,
  getReplySuggestion,
  type DouyinAccountItem,
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

export default function DouyinAiCsWorkbenchPage() {
  const [accounts, setAccounts] = useState<DouyinAccountItem[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<DouyinConversationItem[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<DouyinMessageItem[]>([]);
  const [profile, setProfile] = useState<DouyinUserProfileResponse | null>(null);
  const [reply, setReply] = useState<ReplySuggestionResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conversationSearch, setConversationSearch] = useState("");
  const [conversationFilter, setConversationFilter] = useState<ConversationFilterKey>("all");

  const selectedAccount = accounts.find((item) => item.id === selectedAccountId) || null;
  const selectedConversation =
    conversations.find((item) => item.id === selectedConversationId) || null;
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

  const loadAccounts = useCallback(async () => {
    setLoadingAccounts(true);
    setError(null);
    try {
      const data = await getDouyinAccounts();
      setAccounts(data.items);
      setSelectedAccountId((current) => current || data.items[0]?.id || null);
    } catch (err) {
      setAccounts([]);
      setSelectedAccountId(null);
      setError(err instanceof Error ? err.message : "抖音号列表加载失败");
    } finally {
      setLoadingAccounts(false);
    }
  }, []);

  const loadConversations = useCallback(async (accountId: number) => {
    setLoadingConversations(true);
    setError(null);
    try {
      const data = await getDouyinAccountConversations(accountId);
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

  const loadConversationDetail = useCallback(async (conversationId: number) => {
    setLoadingMessages(true);
    setError(null);
    setReply(null);
    try {
      const [messageData, profileData] = await Promise.all([
        getDouyinConversationMessages(conversationId),
        getDouyinConversationProfile(conversationId),
      ]);
      setMessages(messageData.items);
      setProfile(profileData);
    } catch (err) {
      setMessages([]);
      setProfile(null);
      setError(err instanceof Error ? err.message : "聊天详情加载失败");
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    if (selectedAccountId) {
      void loadConversations(selectedAccountId);
    } else {
      setConversations([]);
      setSelectedConversationId(null);
    }
  }, [loadConversations, selectedAccountId]);

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

  async function generateReply() {
    if (!selectedAccount || !selectedConversation || !latestMessage) return;
    setGenerating(true);
    setError(null);
    try {
      const data = await getReplySuggestion(selectedConversation.id, {
        tenant_id: TENANT_ID,
        merchant_id: MERCHANT_ID,
        account_id: selectedAccount.id,
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
              <div className="text-[11px] text-slate-500">{TENANT_ID} / {MERCHANT_ID}</div>
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
            {!loadingAccounts && accounts.length === 0 ? <EmptyState text="暂无抖音号，请确认 9100 已启动。" /> : null}
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
                    <span className="mt-1 block truncate text-[11px] text-slate-500">
                      {statusText(account.status)} · {formatTime(account.last_active_at)}
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
            {!loadingConversations && conversations.length === 0 ? <EmptyState text="暂无会话。" /> : null}
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
                <button
                  onClick={() => void generateReply()}
                  disabled={!selectedConversation || generating}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {generating ? <LoaderIcon size={14} className="animate-spin" /> : <SparklesIcon size={14} />}
                  生成回复建议
                </button>
              </div>

              {reply ? (
                <div className="space-y-3">
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
                    <button
                      disabled
                      className="h-9 rounded-md border border-slate-200 bg-slate-100 px-3 text-xs font-semibold text-slate-400"
                    >
                      人工确认发送暂未接入
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
    </section>
  );
}
