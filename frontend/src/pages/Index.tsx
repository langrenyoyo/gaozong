import { useCallback, useEffect, useMemo, useState } from "react";
import { Toaster } from "sonner";
import {
  CheckCircle2Icon,
  ExternalLinkIcon,
  QrCodeIcon,
  RefreshCwIcon,
  XIcon,
} from "lucide-react";
import ChatPanel from "../components/ChatPanel";
import ContactInfo from "../components/ContactInfo";
import ContactList from "../components/ContactList";
import SideNav from "../components/SideNav";
import { API_BASE_URL } from "../api/client";
import { fetchLeads } from "../api/leads";
import { fetchWebhookEvents } from "../api/webhookEvents";
import type { Lead, WebhookEvent } from "../api/types";
import { apiDateTimeMs, formatDateTimeLocal } from "../lib/datetime";
import type { ChatMessage, Contact, TagType } from "../types";
import ComputeCenter from "./ComputeCenter";
import LeadsModulePage from "./LeadsModulePage";
import WechatAgent from "./WechatAgent";
import DouyinAiCsWorkbenchPage from "./DouyinAiCsWorkbenchPage";
import DouyinAiCsTestPage from "./DouyinAiCsTestPage";
import { AppUser } from "../App";
import SuperMerchantAgent from "./SuperMerchantAgent";
import SuperAiReplyRecords from "./SuperAiReplyRecords";
import SuperAdminAccounts from "./SuperAdminAccounts";
import SuperComputeConfig from "./SuperComputeConfig";

interface DouyinAccount {
  name: string;
  openid: string;
  key: string;
}

interface DouyinProfile {
  nickName?: string | null;
  avatar?: string | null;
}

function shortId(value?: string | null): string {
  if (!value) return "";
  return value.length > 12 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}

function nonEmptyText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function objectValue(source: unknown, key: string): unknown {
  if (!source) return undefined;
  if (typeof source === "string") {
    try {
      const parsed = JSON.parse(source) as unknown;
      return objectValue(parsed, key);
    } catch {
      return undefined;
    }
  }
  if (typeof source !== "object") return undefined;
  return (source as Record<string, unknown>)[key];
}

function eventTextValue(event: WebhookEvent, key: string): string | null {
  return nonEmptyText((event as unknown as Record<string, unknown>)[key]);
}

function nestedTextValue(event: WebhookEvent, sourceKey: "raw_body" | "content", key: string): string | null {
  return nonEmptyText(objectValue((event as unknown as Record<string, unknown>)[sourceKey], key));
}

function nestedRecordText(source: unknown, key: string): string | null {
  return nonEmptyText(objectValue(source, key));
}

function eventAnyTextValue(event: WebhookEvent, key: string): string | null {
  return nonEmptyText((event as unknown as Record<string, unknown>)[key]);
}

function eventProfileName(event: WebhookEvent): string | null {
  return (
    eventAnyTextValue(event, "nick_name") ||
    eventAnyTextValue(event, "nickname") ||
    eventAnyTextValue(event, "douyin_nick_name") ||
    eventAnyTextValue(event, "display_name") ||
    eventAnyTextValue(event, "customer_name") ||
    nestedTextValue(event, "raw_body", "nick_name") ||
    nestedTextValue(event, "raw_body", "nickname") ||
    nestedTextValue(event, "content", "nick_name") ||
    nestedTextValue(event, "content", "nickname")
  );
}

function eventProfileAvatar(event: WebhookEvent): string | null {
  return (
    eventAnyTextValue(event, "avatar") ||
    eventAnyTextValue(event, "avatar_url") ||
    nestedTextValue(event, "raw_body", "avatar") ||
    nestedTextValue(event, "raw_body", "avatar_url") ||
    nestedTextValue(event, "content", "avatar") ||
    nestedTextValue(event, "content", "avatar_url")
  );
}

function eventExplicitOpenIds(event: WebhookEvent): string[] {
  const rawBody = (event as unknown as Record<string, unknown>).raw_body;
  const content = (event as unknown as Record<string, unknown>).content;
  const ids = [
    eventAnyTextValue(event, "open_id"),
    eventAnyTextValue(event, "account_open_id"),
    event.body_open_id,
    event.body_account_open_id,
    event.content_open_id,
    event.content_account_open_id,
    nestedRecordText(rawBody, "open_id"),
    nestedRecordText(rawBody, "account_open_id"),
    nestedRecordText(content, "open_id"),
    nestedRecordText(content, "account_open_id"),
  ];
  return ids.filter((value, index): value is string => Boolean(value) && ids.indexOf(value) === index);
}

function eventCustomerOpenId(event: WebhookEvent): string | null {
  if (event.event === "im_receive_msg" && event.from_user_id) return event.from_user_id;
  if (event.event === "im_send_msg" && event.to_user_id) return event.to_user_id;
  return event.body_open_id || event.content_open_id || eventAnyTextValue(event, "open_id") || null;
}

function mergeDouyinProfile(
  profiles: Map<string, DouyinProfile>,
  openId: string | null | undefined,
  profile: DouyinProfile,
) {
  if (!openId || (!profile.nickName && !profile.avatar)) return;
  const current = profiles.get(openId) || {};
  profiles.set(openId, {
    nickName: current.nickName || profile.nickName || null,
    avatar: current.avatar || profile.avatar || null,
  });
}

function walkRecords(source: unknown, visitor: (record: Record<string, unknown>) => void, depth = 0) {
  if (!source || depth > 8) return;
  if (typeof source === "string") {
    const parsed = parseRecord(source);
    if (parsed) walkRecords(parsed, visitor, depth + 1);
    return;
  }
  if (Array.isArray(source)) {
    source.forEach((item) => walkRecords(item, visitor, depth + 1));
    return;
  }
  if (typeof source !== "object") return;

  const record = source as Record<string, unknown>;
  visitor(record);
  Object.values(record).forEach((value) => walkRecords(value, visitor, depth + 1));
}

function addLeadProfiles(profiles: Map<string, DouyinProfile>, lead: Lead) {
  const rawData = parseRecord(lead.raw_data);
  walkRecords(rawData, (record) => {
    const openId = nonEmptyText(record.open_id) || nonEmptyText(record.account_open_id);
    mergeDouyinProfile(profiles, openId, {
      nickName: nonEmptyText(record.nick_name) || nonEmptyText(record.nickname),
      avatar: nonEmptyText(record.avatar) || nonEmptyText(record.avatar_url),
    });
  });

  mergeDouyinProfile(profiles, lead.source_id, {
    nickName: leadDisplayName(lead),
    avatar: lead.source_id ? profiles.get(lead.source_id)?.avatar || null : null,
  });
}

function buildProfileByOpenId(events: WebhookEvent[], leads: Lead[] = []): Map<string, DouyinProfile> {
  const profiles = new Map<string, DouyinProfile>();

  for (const event of events) {
    const profile = { nickName: eventProfileName(event), avatar: eventProfileAvatar(event) };
    mergeDouyinProfile(profiles, event.from_user_id, {
      nickName: eventAnyTextValue(event, "from_user_nick_name"),
      avatar: eventAnyTextValue(event, "from_user_avatar"),
    });
    mergeDouyinProfile(profiles, event.to_user_id, {
      nickName: eventAnyTextValue(event, "to_user_nick_name"),
      avatar: eventAnyTextValue(event, "to_user_avatar"),
    });
    mergeDouyinProfile(profiles, eventCustomerOpenId(event), profile);
    const explicitIds = eventExplicitOpenIds(event);
    explicitIds.forEach((openId) => mergeDouyinProfile(profiles, openId, profile));
    if (explicitIds.length === 0) {
      mergeDouyinProfile(profiles, eventCustomerOpenId(event), profile);
    }
  }

  leads.forEach((lead) => addLeadProfiles(profiles, lead));

  return profiles;
}

function firstText(events: WebhookEvent[], getter: (event: WebhookEvent) => string | null): string | null {
  for (const event of events) {
    const value = getter(event);
    if (value) return value;
  }
  return null;
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

function leadNestedText(lead: Lead | null | undefined, path: string[]): string | null {
  let current: unknown = parseRecord(lead?.raw_data);
  for (const key of path) {
    current = objectValue(current, key);
    if (current === undefined || current === null) return null;
  }
  return nonEmptyText(current);
}

function leadConversationId(lead: Lead): string | null {
  return (
    leadNestedText(lead, ["parsed_content", "conversation_short_id"]) ||
    leadNestedText(lead, ["webhook_payload", "content", "conversation_short_id"]) ||
    leadNestedText(lead, ["content", "conversation_short_id"]) ||
    leadNestedText(lead, ["conversation_short_id"])
  );
}

function leadDisplayName(lead?: Lead | null): string | null {
  if (!lead) return null;
  const leadRecord = lead as unknown as Record<string, unknown>;
  return (
    nonEmptyText(leadRecord.douyin_display_name) ||
    nonEmptyText(lead.customer_name) ||
    nonEmptyText(leadRecord.display_name) ||
    leadNestedText(lead, ["user_infos", "nick_name"]) ||
    leadNestedText(lead, ["user_infos", "nickname"]) ||
    leadNestedText(lead, ["webhook_payload", "nick_name"]) ||
    leadNestedText(lead, ["webhook_payload", "nickname"])
  );
}

function firstLeadContact(lead?: Lead | null): string | null {
  if (!lead) return null;
  return (
    nonEmptyText(lead.phone) ||
    nonEmptyText(lead.wechat) ||
    nonEmptyText(lead.customer_contact) ||
    lead.all_extracted_contacts?.find((item) => nonEmptyText(item)) ||
    null
  );
}

function leadByConversation(events: WebhookEvent[], leads: Lead[]): Lead | null {
  const leadById = new Map(leads.map((lead) => [lead.id, lead]));
  const leadByConversationId = new Map<string, Lead>();
  const leadBySourceId = new Map<string, Lead>();
  const leadByContact = new Map<string, Lead>();

  for (const lead of leads) {
    const conversationId = leadConversationId(lead);
    if (conversationId) leadByConversationId.set(conversationId, lead);
    if (lead.source_id) leadBySourceId.set(lead.source_id, lead);
    for (const value of [lead.customer_contact, lead.phone, lead.wechat, ...(lead.all_extracted_contacts || [])]) {
      const contact = nonEmptyText(value);
      if (contact) leadByContact.set(contact, lead);
    }
  }

  for (const event of events) {
    if (event.lead_id && leadById.has(event.lead_id)) return leadById.get(event.lead_id) || null;
    if (event.conversation_short_id && leadByConversationId.has(event.conversation_short_id)) {
      return leadByConversationId.get(event.conversation_short_id) || null;
    }
    for (const openId of [event.from_user_id, event.to_user_id, event.body_open_id, event.content_open_id]) {
      if (openId && leadBySourceId.has(openId)) return leadBySourceId.get(openId) || null;
    }
    if (event.customer_contact && leadByContact.has(event.customer_contact)) return leadByContact.get(event.customer_contact) || null;
  }

  return null;
}

function contactFromMessageText(events: WebhookEvent[]): string | null {
  const text = firstText(events, (event) => event.message_text);
  if (!text) return null;
  const phone = text.match(/1[3-9]\d{9}/)?.[0];
  if (phone) return phone;
  return text.match(/(?:微信|wx|WX|v|V)[:：\s]*([a-zA-Z][-_a-zA-Z0-9]{5,19})/)?.[1] || null;
}

function getDouyinDisplayName(
  events: WebhookEvent[],
  openId: string | null,
  customerContact: string | null,
  matchedLead: Lead | null,
  profile: DouyinProfile | null,
): string {
  if (profile?.nickName) return profile.nickName;
  const leadName = leadDisplayName(matchedLead);
  if (leadName) return leadName;
  const leadContact = firstLeadContact(matchedLead);
  if (leadContact) return `客户 ${leadContact}`;
  if (customerContact) return `客户 ${customerContact}`;
  const name =
    firstText(events, (event) => eventTextValue(event, "nick_name")) ||
    firstText(events, (event) => eventTextValue(event, "nickname")) ||
    firstText(events, (event) => eventTextValue(event, "douyin_nick_name")) ||
    firstText(events, (event) => nestedTextValue(event, "raw_body", "nick_name")) ||
    firstText(events, (event) => nestedTextValue(event, "raw_body", "nickname")) ||
    firstText(events, (event) => nestedTextValue(event, "content", "nick_name")) ||
    firstText(events, (event) => nestedTextValue(event, "content", "nickname")) ||
    firstText(events, (event) => eventTextValue(event, "display_name")) ||
    firstText(events, (event) => eventTextValue(event, "customer_name"));
  if (name) return name;
  const messageContact = contactFromMessageText(events);
  if (messageContact) return `客户 ${messageContact}`;
  if (openId) return `客户 ${shortId(openId)}`;
  return "未知客户";
}

function formatEventTime(value: string | null): string {
  return formatDateTimeLocal(value);
}

function eventDescription(event?: string | null): string {
  if (event === "im_enter_direct_msg") return "进入私信会话";
  if (event === "im_send_msg") return "发送了一条消息";
  if (event === "im_receive_msg") return "客户发送了一条消息";
  return event || "系统事件";
}

function conversationKey(event: WebhookEvent): { id: string; isFallback: boolean } {
  if (event.conversation_short_id) {
    return { id: event.conversation_short_id, isFallback: false };
  }
  return {
    id: `${event.from_user_id || "unknown"}_${event.to_user_id || "unknown"}`,
    isFallback: true,
  };
}

function customerOpenId(events: WebhookEvent[]): string | null {
  const receive = events.find((event) => event.event === "im_receive_msg" && event.from_user_id);
  if (receive?.from_user_id) return receive.from_user_id;
  const send = events.find((event) => event.event === "im_send_msg" && event.to_user_id);
  if (send?.to_user_id) return send.to_user_id;
  const explicit = events.find((event) => event.body_open_id || event.content_open_id || eventAnyTextValue(event, "open_id"));
  if (explicit) return explicit.body_open_id || explicit.content_open_id || eventAnyTextValue(explicit, "open_id");

  const businessIds = new Set(
    events
      .flatMap((event) => [
        event.event === "im_receive_msg" ? event.to_user_id : null,
        event.event === "im_send_msg" ? event.from_user_id : null,
        event.body_account_open_id,
        event.content_account_open_id,
      ])
      .filter(Boolean),
  );
  const any = events.find((event) => {
    const candidate = event.from_user_id || event.to_user_id;
    return candidate && !businessIds.has(candidate);
  });
  return any?.from_user_id || any?.to_user_id || null;
}

function intentTag(events: WebhookEvent[]): TagType {
  if (events.some((event) => event.customer_contact || event.contact_extract_status === "matched")) return "高意向";
  if (events.some((event) => event.lead_id)) return "已留资";
  if (events.some((event) => event.event === "im_receive_msg")) return "待回访";
  return "需人工";
}

function toMessage(event: WebhookEvent): ChatMessage {
  const sender =
    event.event === "im_receive_msg"
      ? "user"
      : event.event === "im_send_msg"
        ? "human"
        : "system";
  return {
    id: String(event.id),
    sender,
    content: event.message_text || eventDescription(event.event),
    time: formatEventTime(event.created_at),
    senderLabel: sender === "human" ? "抖音企业号" : undefined,
    event: event.event,
    fromUserId: event.from_user_id,
    toUserId: event.to_user_id,
    serverMessageId: event.server_message_id,
    leadAction: event.lead_action,
    customerContact: event.customer_contact,
  };
}

function buildConversations(events: WebhookEvent[], leads: Lead[] = []): {
  contacts: Contact[];
  messages: Record<string, ChatMessage[]>;
} {
  const profileByOpenId = buildProfileByOpenId(events, leads);
  const groups = new Map<string, { fallback: boolean; events: WebhookEvent[] }>();
  for (const event of events) {
    const key = conversationKey(event);
    const group = groups.get(key.id) || { fallback: key.isFallback, events: [] };
    group.fallback = group.fallback || key.isFallback;
    group.events.push(event);
    groups.set(key.id, group);
  }

  const contacts: Contact[] = [];
  const messages: Record<string, ChatMessage[]> = {};

  for (const [id, group] of groups) {
    const sorted = [...group.events].sort((a, b) => {
      const left = apiDateTimeMs(a.created_at);
      const right = apiDateTimeMs(b.created_at);
      if (left !== right) return left - right;
      return a.id - b.id;
    });
    const latest = sorted[sorted.length - 1];
    const latestText = [...sorted].reverse().find((event) => event.message_text)?.message_text || eventDescription(latest?.event);
    const openId = customerOpenId(sorted);
    const contactValue = sorted.find((event) => event.customer_contact)?.customer_contact || null;
    const matchedLead = leadByConversation(sorted, leads);
    const leadId = matchedLead?.id || sorted.find((event) => event.lead_id)?.lead_id || null;
    const contactExtractStatus =
      matchedLead?.contact_extract_status || sorted.find((event) => event.contact_extract_status)?.contact_extract_status || null;
    const profile =
      (openId ? profileByOpenId.get(openId) : null) ||
      (matchedLead?.source_id ? profileByOpenId.get(matchedLead.source_id) : null) ||
      null;
    const displayName = getDouyinDisplayName(sorted, openId, contactValue, matchedLead, profile);
    const leadContact = firstLeadContact(matchedLead);

    contacts.push({
      id,
      name: displayName,
      avatarSeed: openId || id,
      avatarUrl: profile?.avatar || null,
      lastMessage: latestText || "无文本内容",
      time: formatEventTime(latest?.created_at || null),
      tag: intentTag(sorted),
      source: "抖音私信",
      carModel: "未知",
      year: "未知",
      priceRange: "未知",
      isOnline: false,
      unread: 0,
      conversationShortId: group.fallback ? null : id,
      isFallbackConversation: group.fallback,
      leadId,
      customerContact: leadContact || contactValue,
      contactExtractStatus,
      eventsCount: sorted.length,
      customerOpenId: openId,
      fromUserId: sorted.find((event) => event.from_user_id)?.from_user_id || null,
      toUserId: sorted.find((event) => event.to_user_id)?.to_user_id || null,
      phone: matchedLead?.phone || null,
      wechat: matchedLead?.wechat || null,
      leadStatus: matchedLead?.status || (leadId ? "created" : null),
      leadContent: matchedLead?.content || null,
      originalMessageText: matchedLead?.original_message_text || null,
    });
    messages[id] = sorted.map(toMessage);
  }

  contacts.sort((a, b) => {
    const aLatest = groupLatestTime(groups.get(a.id)?.events || []);
    const bLatest = groupLatestTime(groups.get(b.id)?.events || []);
    return bLatest - aLatest;
  });

  return { contacts, messages };
}

function groupLatestTime(events: WebhookEvent[]): number {
  return Math.max(...events.map((event) => apiDateTimeMs(event.created_at)), 0);
}

function DouyinAuthModal({
  onClose,
  onAuthorized,
}: {
  onClose: () => void;
  onAuthorized: (account: DouyinAccount) => void;
}) {
  const [linkCreated, setLinkCreated] = useState(false);
  const [authorizing, setAuthorizing] = useState(false);

  const completeAuth = () => {
    setAuthorizing(true);
    window.setTimeout(() => {
      onAuthorized({
        name: "老高二手车企业号",
        openid: "dy_openid_8f29c16",
        key: "dy_key_7A9K2M",
      });
      setAuthorizing(false);
    }, 800);
  };

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[520px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">接入抖音企业号</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">获取授权链接后扫码授权，系统将同步账号信息</p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="px-5 py-5">
          {linkCreated ? (
            <div className="grid place-items-center rounded-2xl border border-[#e4e8f0] bg-[#f8fafc] px-5 py-7 text-center">
              <div className="grid h-36 w-36 place-items-center rounded-2xl border border-[#dbe3ef] bg-white text-[#2563eb] shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
                <QrCodeIcon size={80} />
              </div>
              <p className="mt-4 text-sm font-bold text-[#1a1f2e]">扫码授权抖音企业号</p>
              <p className="mt-1 text-xs leading-relaxed text-[#8b95a6]">
                授权成功后将启用客户会话同步。
              </p>
              <div className="mt-4 w-full rounded-xl bg-white px-3 py-2 text-left text-xs text-[#64748b] ring-1 ring-[#e4e8f0]">
                https://open.douyin.com/oauth/authorize?client_key=laogao_demo
              </div>
            </div>
          ) : (
            <div className="rounded-2xl border border-[#e4e8f0] bg-[#f8fafc] px-5 py-6">
              <div className="grid h-12 w-12 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
                <ExternalLinkIcon size={22} />
              </div>
              <h3 className="mt-4 text-sm font-bold text-[#1a1f2e]">生成授权链接</h3>
              <p className="mt-2 text-xs leading-relaxed text-[#8b95a6]">
                点击后获取抖音开放平台授权链接，并在弹窗内打开扫码授权页面。
              </p>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          {linkCreated ? (
            <button
              onClick={completeAuth}
              disabled={authorizing}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:opacity-60"
            >
              {authorizing ? <RefreshCwIcon size={14} className="animate-spin" /> : <CheckCircle2Icon size={14} />}
              {authorizing ? "授权中" : "模拟授权完成"}
            </button>
          ) : (
            <button
              onClick={() => setLinkCreated(true)}
              className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
            >
              获取授权链接
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function DouyinConnectEmpty({ onConnect }: { onConnect: () => void }) {
  return (
    <>
      <section className="flex h-full flex-col border-r border-[#e4e8f0] bg-white">
        <div className="border-b border-[#e4e8f0] px-4 pb-3 pt-5">
          <h2 className="text-[15px] font-bold text-[#1a1f2e]">抖音AI小高客服</h2>
          <p className="mt-1 text-[11px] text-[#8b95a6]">接入抖音企业号后同步客户会话</p>
        </div>
        <div className="grid flex-1 place-items-center px-5 text-center">
          <div>
            <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[#eff6ff] text-[#2563eb]">
              <QrCodeIcon size={24} />
            </div>
            <p className="mt-3 text-sm font-bold text-[#1a1f2e]">暂未接入抖音企业号</p>
            <p className="mt-2 text-xs leading-relaxed text-[#8b95a6]">完成授权后，客户会话会同步到这里。</p>
          </div>
        </div>
      </section>

      <section className="flex h-full flex-col bg-[#f3f6fa]">
        <header className="border-b border-[#e4e8f0] bg-white px-6 py-4">
          <h1 className="text-[15px] font-bold text-[#1a1f2e]">抖音AI小高客服</h1>
          <p className="mt-1 text-xs text-[#8b95a6]">授权后即可启用抖音AI小高客服、AI托管和线索转化流程</p>
        </header>
        <div className="grid flex-1 place-items-center p-8">
          <div className="w-full max-w-[520px] rounded-2xl border border-[#e4e8f0] bg-white p-7 text-center shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-[#eff6ff] text-[#2563eb]">
              <ExternalLinkIcon size={30} />
            </div>
            <h2 className="mt-5 text-base font-bold text-[#1a1f2e]">接入抖音企业号</h2>
            <p className="mx-auto mt-2 max-w-[360px] text-xs leading-6 text-[#8b95a6]">
              点击按钮获取授权链接，在弹窗中扫码完成授权。授权成功后即可同步客户会话。
            </p>
            <button
              onClick={onConnect}
              className="mt-5 h-10 rounded-xl bg-[#2563eb] px-5 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
            >
              接入抖音企业号
            </button>
          </div>
        </div>
      </section>
    </>
  );
}

export default function Index({
  user,
  onLogout = () => {},
  initialActiveNav = "chat",
}: {
  user: AppUser;
  onLogout?: () => void;
  initialActiveNav?: string;
}) {
  const [activeNav, setActiveNav] = useState(initialActiveNav);
  const [superActiveNav, setSuperActiveNav] = useState("merchant-agent");
  const [isNavExpanded, setIsNavExpanded] = useState(true);
  const [selectedContactId, setSelectedContactId] = useState("");
  const [douyinAccount, setDouyinAccount] = useState<DouyinAccount | null>(null);
  const [showDouyinAuth, setShowDouyinAuth] = useState(false);
  const [chatEvents, setChatEvents] = useState<WebhookEvent[]>([]);
  const [chatLeads, setChatLeads] = useState<Lead[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const conversations = useMemo(() => buildConversations(chatEvents, chatLeads), [chatEvents, chatLeads]);
  const selectedContact =
    conversations.contacts.find((contact) => contact.id === selectedContactId) ||
    conversations.contacts[0] ||
    null;
  const selectedMessages = selectedContact ? conversations.messages[selectedContact.id] || [] : [];
  const navColumn = isNavExpanded ? "220px" : "88px";
  const isAdminUser = user.role !== "merchant";

  const loadChatEvents = useCallback(async () => {
    setChatLoading(true);
    setChatError(null);
    try {
      const [result, leads] = await Promise.all([
        fetchWebhookEvents({ page: 1, page_size: 100 }),
        fetchLeads().catch(() => [] as Lead[]),
      ]);
      const items = result.data.items || [];
      setChatEvents(items);
      setChatLeads(leads);
      setSelectedContactId((current) => {
        if (current && items.some((event) => conversationKey(event).id === current)) return current;
        const first = buildConversations(items, leads).contacts[0];
        return first?.id || "";
      });
    } catch (err) {
      setChatEvents([]);
      setChatLeads([]);
      setSelectedContactId("");
      setChatError(err instanceof Error ? err.message : "真实抖音私信会话加载失败");
    } finally {
      setChatLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadChatEvents();
  }, [loadChatEvents]);

  return (
    <main className="h-screen overflow-hidden bg-[#f3f6fa] text-[#1a1f2e]">
      <Toaster position="top-right" richColors />
      <div
        className={`grid h-full min-h-0 overflow-hidden ${
          isAdminUser
            ? "grid-cols-[var(--nav-width)_minmax(900px,1fr)]"
            : activeNav === "chat"
            ? "grid-cols-[var(--nav-width)_minmax(270px,320px)_minmax(520px,1fr)_240px] max-[1180px]:grid-cols-[var(--nav-width)_minmax(260px,300px)_minmax(460px,1fr)]"
            : "grid-cols-[var(--nav-width)_minmax(900px,1fr)]"
        }`}
        style={{ "--nav-width": navColumn } as React.CSSProperties}
      >
        <SideNav
          activeNav={isAdminUser ? superActiveNav : activeNav}
          onNavChange={isAdminUser ? setSuperActiveNav : setActiveNav}
          expanded={isNavExpanded}
          onExpandedChange={setIsNavExpanded}
          onLogout={onLogout}
          showSalesBadge={Boolean(douyinAccount)}
          user={user}
        />
        {isAdminUser ? (
          superActiveNav === "ai-reply-records" ? (
            <SuperAiReplyRecords />
          ) : superActiveNav === "admin-compute" ? (
            <SuperComputeConfig />
          ) : superActiveNav === "admin-accounts" ? (
            <SuperAdminAccounts />
          ) : (
            <SuperMerchantAgent />
          )
        ) : activeNav === "chat" ? (
          <>
            <ContactList
              selectedId={selectedContact?.id || ""}
              onSelect={setSelectedContactId}
              douyinAccountName={douyinAccount?.name || API_BASE_URL || "未配置后端"}
              contacts={conversations.contacts}
              loading={chatLoading}
              error={chatError}
              onRefresh={loadChatEvents}
            />
            <ChatPanel contact={selectedContact} messages={selectedMessages} loading={chatLoading} />
            <div className="min-h-0 overflow-hidden max-[1180px]:hidden">
              <ContactInfo contact={selectedContact} />
            </div>
          </>
        ) : activeNav === "douyin-ai-cs" ? (
          <DouyinAiCsWorkbenchPage />
        ) : activeNav === "leads" ? (
          <LeadsModulePage />
        ) : activeNav === "douyin-ai-cs-test" ? (
          <DouyinAiCsTestPage />
        ) : activeNav === "ai-agents" ? (
          <SuperMerchantAgent />
        ) : activeNav === "ai-agent" ? (
          <WechatAgent />
        ) : activeNav === "compute" ? (
          <ComputeCenter />
        ) : (
          <div className="grid h-full place-items-center bg-[#f3f6fa] p-8">
            <div className="rounded-2xl border border-[#e4e8f0] bg-white px-8 py-6 text-center shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <p className="text-sm font-bold text-[#1a1f2e]">模块建设中</p>
              <p className="mt-2 text-xs text-[#8b95a6]">当前先完成抖音AI小高客服和AI小高线索两个核心页面。</p>
            </div>
          </div>
        )}
      </div>
      {showDouyinAuth ? (
        <DouyinAuthModal
          onClose={() => setShowDouyinAuth(false)}
          onAuthorized={(account) => {
            setDouyinAccount(account);
            setShowDouyinAuth(false);
          }}
        />
      ) : null}
    </main>
  );
}
