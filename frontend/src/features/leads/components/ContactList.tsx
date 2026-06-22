import { LoaderIcon, RefreshCwIcon, SearchIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Contact, TagType } from "../../../types";

interface ContactListProps {
  selectedId?: string;
  onSelect?: (id: string) => void;
  douyinAccountName?: string;
  contacts?: Contact[];
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void;
}

const tagConfig: Record<TagType, { label: string; color: string; bg: string }> = {
  "需人工": { label: "需人工", color: "#b45309", bg: "#fef3c7" },
  "高意向": { label: "高意向", color: "#047857", bg: "#d1fae5" },
  "已留资": { label: "已留资", color: "#6d28d9", bg: "#ede9fe" },
  "待回访": { label: "待回访", color: "#dc2626", bg: "#fee2e2" },
};

const filters: Array<TagType | "全部"> = ["全部", "需人工", "高意向", "已留资", "待回访"];

export default function ContactList({
  selectedId = "",
  onSelect = () => {},
  douyinAccountName,
  contacts = [],
  loading = false,
  error = null,
  onRefresh,
}: ContactListProps) {
  const [search, setSearch] = useState("");
  const [activeTag, setActiveTag] = useState<TagType | "全部">("全部");

  const filtered = useMemo(
    () =>
      contacts.filter((contact) => {
        const keyword = search.trim();
        const matchSearch =
          !keyword ||
          contact.name.includes(keyword) ||
          contact.lastMessage.includes(keyword) ||
          contact.carModel.includes(keyword) ||
          contact.priceRange.includes(keyword) ||
          (contact.conversationShortId || "").includes(keyword) ||
          (contact.customerOpenId || "").includes(keyword) ||
          (contact.fromUserId || "").includes(keyword) ||
          (contact.toUserId || "").includes(keyword) ||
          (contact.customerContact || "").includes(keyword);
        const matchTag = activeTag === "全部" || contact.tag === activeTag;
        return matchSearch && matchTag;
      }),
    [activeTag, contacts, search],
  );

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden border-r border-[#e4e8f0] bg-white">
      <div className="shrink-0 border-b border-[#e4e8f0] px-4 pb-3 pt-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[#1a1f2e]">抖音AI小高客服</h2>
            <p className="mt-1 truncate text-[11px] text-[#8b95a6]">
              {douyinAccountName ? `抖音企业号：${douyinAccountName}` : "真实 webhook 私信会话"}
            </p>
          </div>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="inline-flex h-7 shrink-0 items-center gap-1 rounded-lg bg-[#eff6ff] px-2 text-xs font-semibold text-[#2563eb] disabled:opacity-60"
          >
            {loading ? <LoaderIcon size={12} className="animate-spin" /> : <RefreshCwIcon size={12} />}
            {contacts.length}
          </button>
        </div>

        <label className="relative block">
          <SearchIcon size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
          <input
            type="search"
            placeholder="搜索客户、联系方式或消息"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="h-9 w-full rounded-xl border border-[#e4e8f0] bg-[#f4f6f8] pl-7 pr-3 text-xs outline-none transition-smooth focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          />
        </label>
      </div>

      <div className="shrink-0 border-b border-[#e4e8f0] px-3 py-2">
        <div className="grid grid-cols-5 rounded-xl bg-[#eef2f7] p-1">
          {filters.map((tag) => {
            const isActive = activeTag === tag;
            return (
              <button
                key={tag}
                onClick={() => setActiveTag(tag)}
                className={`h-7 rounded-lg text-[11px] font-medium transition-smooth ${
                  isActive
                    ? "bg-white text-[#1a1f2e] shadow-[0_1px_2px_rgba(15,23,42,0.08)]"
                    : "text-[#8b95a6] hover:text-[#1a1f2e]"
                }`}
              >
                {tag}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        {loading ? (
          <div className="grid h-full place-items-center px-5 text-center text-xs text-[#8b95a6]">
            <span className="inline-flex items-center gap-2">
              <LoaderIcon size={14} className="animate-spin" />
              加载真实抖音私信会话
            </span>
          </div>
        ) : error ? (
          <div className="px-5 py-6 text-xs leading-6 text-amber-700">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="px-5 py-8 text-center text-xs leading-6 text-[#8b95a6]">
            暂无真实抖音私信会话，请完成授权并让客户发送私信。
          </div>
        ) : (
          filtered.map((contact) => {
            const isSelected = selectedId === contact.id;
            const tag = tagConfig[contact.tag];

            return (
              <button
                key={contact.id}
                onClick={() => onSelect(contact.id)}
                className={`mx-2 mb-1.5 grid w-[calc(100%-16px)] grid-cols-[36px_1fr_auto] gap-2.5 rounded-xl px-2.5 py-2.5 text-left transition-smooth ${
                  isSelected
                    ? "bg-[#eff6ff] shadow-[0_8px_18px_rgba(37,99,235,0.10)] ring-1 ring-[#bfdbfe]"
                    : "hover:bg-[#f8fafc]"
                }`}
              >
                <div className="relative">
                  <img
                    src={contact.avatarUrl || `https://api.dicebear.com/7.x/avataaars/svg?seed=${contact.avatarSeed}&backgroundColor=b6e3f4,c0aede,d1d4f9`}
                    alt={contact.name}
                    className="h-9 w-9 rounded-full bg-[#e0edff]"
                  />
                  <span
                    className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white"
                    style={{ background: contact.isOnline ? "#10b981" : "#d1d5db" }}
                  />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-[13px] font-bold text-[#1a1f2e]">{contact.name}</span>
                    {contact.unread > 0 ? (
                      <span className="grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[9px] font-bold text-white">
                        {contact.unread}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 truncate text-[11px] text-[#8b95a6]">{contact.lastMessage}</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    <span
                      className="inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold"
                      style={{ background: tag.bg, color: tag.color }}
                    >
                      {tag.label}
                    </span>
                  </div>
                </div>
                <span className="pt-0.5 text-[10px] text-[#8b95a6]">{contact.time}</span>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}
