export type TagType = "需人工" | "高意向" | "已留资" | "待回访";

export interface Contact {
  id: string;
  name: string;
  avatarSeed: string;
  avatarUrl?: string | null;
  lastMessage: string;
  time: string;
  tag: TagType;
  source: string;
  carModel: string;
  year: string;
  priceRange: string;
  isOnline: boolean;
  unread: number;
  conversationShortId?: string | null;
  isFallbackConversation?: boolean;
  leadId?: number | null;
  customerContact?: string | null;
  contactExtractStatus?: string | null;
  eventsCount?: number;
  customerOpenId?: string | null;
  fromUserId?: string | null;
  toUserId?: string | null;
  phone?: string | null;
  wechat?: string | null;
  leadStatus?: string | null;
  leadContent?: string | null;
  originalMessageText?: string | null;
}

export type MessageSender = "user" | "ai" | "human" | "system";

export interface ChatMessage {
  id: string;
  sender: MessageSender;
  content: string;
  time: string;
  senderLabel?: string;
  event?: string | null;
  fromUserId?: string | null;
  toUserId?: string | null;
  serverMessageId?: string | null;
  leadAction?: string | null;
  customerContact?: string | null;
}

export interface ChatSession {
  contactId: string;
  isAiManaged: boolean;
  messages: ChatMessage[];
}

export type NavItem = {
  id: string;
  label: string;
  path: string;
  badge?: number;
  permissionCodes?: string[];
};
