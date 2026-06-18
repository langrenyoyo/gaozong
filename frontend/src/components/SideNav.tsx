import {
  BotIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CpuIcon,
  FilterIcon,
  LogOutIcon,
  MessageCircleMoreIcon,
  MessageSquareIcon,
  ShieldCheckIcon,
  UserCogIcon,
  WrenchIcon,
} from "lucide-react";
import { AppUser } from "../App";
import { NavItem } from "../types";

interface SideNavProps {
  activeNav?: string;
  onNavChange?: (id: string) => void;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  onLogout?: () => void;
  showSalesBadge?: boolean;
  user?: AppUser;
}

const navItems: Array<NavItem & { expandedLabel: string }> = [
  { id: "douyin-ai-cs", label: "客服", expandedLabel: "抖音AI小高客服", path: "/douyin-ai-cs" },
  { id: "douyin-ai-cs-test", label: "测试", expandedLabel: "抖音AI客服测试", path: "/douyin-ai-cs-test" },
  { id: "leads", label: "线索", expandedLabel: "AI小高线索", path: "/leads" },
  { id: "ai-agents", label: "智能体", expandedLabel: "AI小高智能体", path: "/ai-agents" },
  { id: "ai-agent", label: "助手", expandedLabel: "小高AI微信助手", path: "/ai-agent" },
];

const superNavItems: Array<NavItem & { expandedLabel: string }> = [
  { id: "merchant-agent", label: "智能体", expandedLabel: "AI小高智能体", path: "/merchant-agent" },
  { id: "ai-reply-records", label: "回复", expandedLabel: "AI回复记录", path: "/ai-reply-records" },
  { id: "admin-accounts", label: "账号", expandedLabel: "管理员账号", path: "/admin-accounts" },
];

const navIcons: Record<string, React.ReactNode> = {
  "douyin-ai-cs": <MessageCircleMoreIcon size={18} />,
  "douyin-ai-cs-test": <WrenchIcon size={18} />,
  leads: <FilterIcon size={18} />,
  "ai-agents": <BotIcon size={18} />,
  "ai-agent": <ShieldCheckIcon size={18} />,
  "merchant-agent": <BotIcon size={18} />,
  "ai-reply-records": <MessageSquareIcon size={18} />,
  "admin-accounts": <UserCogIcon size={18} />,
};

export default function SideNav({
  activeNav = "douyin-ai-cs",
  onNavChange = () => {},
  expanded = false,
  onExpandedChange = () => {},
  onLogout = () => {},
  showSalesBadge = false,
  user = { account: "18578790007", role: "merchant", roleLabel: "商户账号" },
}: SideNavProps) {
  const isAdminUser = user.role !== "merchant";
  const visibleNavItems = isAdminUser ? superNavItems : navItems;

  return (
    <aside className="relative h-full">
      <div
        className={`flex h-full flex-col bg-[#101729] text-slate-300 shadow-[inset_-1px_0_0_rgba(255,255,255,0.08)] transition-[width] duration-200 ${
          expanded ? "w-[220px] items-stretch" : "w-[88px] items-center"
        }`}
      >
        <div className={`flex w-full items-center border-b border-white/10 py-5 ${expanded ? "justify-between px-4" : "justify-center"}`}>
          <button
            onClick={() => onExpandedChange(!expanded)}
            className={`flex min-w-0 items-center rounded-2xl text-left transition-smooth ${expanded ? "gap-3" : "hover:scale-105"}`}
            aria-label={expanded ? "收起导航" : "展开导航"}
          >
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-[#2563eb] text-white shadow-[0_12px_30px_rgba(37,99,235,0.34)]">
              <BotIcon size={19} />
            </div>
            {expanded ? (
              <div className="min-w-0">
                <div className="truncate text-sm font-bold text-white">小高AI系统</div>
                <div className="mt-0.5 truncate text-[10px] text-slate-500">AI工作台</div>
              </div>
            ) : null}
          </button>
        </div>

        <nav className={`flex flex-1 flex-col gap-1.5 pt-4 ${expanded ? "px-3" : "items-center"}`}>
          {visibleNavItems.map((item) => {
            const isActive = activeNav === item.id;
            const badge = item.id === "douyin-ai-cs" && showSalesBadge ? 6 : item.badge;
            return (
              <button
                key={item.id}
                onClick={() => onNavChange(item.id)}
                className={`relative flex transition-smooth ${
                  expanded
                    ? "h-10 w-full flex-row items-center gap-3 rounded-xl px-3 text-xs font-semibold"
                    : "w-16 flex-col items-center gap-1 rounded-2xl py-2.5 text-[10px]"
                } ${
                  isActive
                    ? "bg-[#2563eb] text-white shadow-[0_12px_24px_rgba(37,99,235,0.28)]"
                    : "text-slate-400 hover:bg-white/8 hover:text-white"
                }`}
              >
                <span className="shrink-0">{navIcons[item.id]}</span>
                <span className={expanded ? "truncate" : "leading-tight"}>{expanded ? item.expandedLabel : item.label}</span>
                {badge ? (
                  <span
                    className={`grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[9px] font-bold text-white ${
                      expanded ? "ml-auto" : "absolute right-1.5 top-1.5"
                    }`}
                  >
                    {badge}
                  </span>
                ) : null}
              </button>
            );
          })}
        </nav>

        <div className={`flex flex-col gap-2 pb-4 ${expanded ? "px-3" : "items-center"}`}>
          <button
            onClick={() => onExpandedChange(!expanded)}
            className={`grid h-10 place-items-center rounded-xl text-slate-400 transition-smooth hover:bg-white/8 hover:text-white ${
              expanded ? "w-full grid-cols-[18px_1fr] px-3 text-left text-xs" : "w-12"
            }`}
          >
            {expanded ? <ChevronLeftIcon size={16} /> : <ChevronRightIcon size={16} />}
            {expanded ? <span>收起导航</span> : null}
          </button>

          {user.role === "merchant" ? (
            <div
              className={`border border-white/10 bg-[#182238] shadow-[0_14px_30px_rgba(7,13,28,0.22)] ${
                expanded ? "w-full rounded-xl px-3 py-3" : "grid h-12 w-12 place-items-center rounded-xl"
              }`}
            >
              {expanded ? (
                <div className="flex items-center gap-3">
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[#22304b] text-[#8fb4ff]">
                    <CpuIcon size={17} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs font-semibold text-slate-200">小高AI微信助手</span>
                      <span className="text-[11px] font-bold text-[#8fb4ff]">v3.8</span>
                    </div>
                    <div className="mt-1 flex items-center justify-between gap-2 text-[11px]">
                      <span className="text-slate-500">状态</span>
                      <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-400">
                        <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_0_4px_rgba(52,211,153,0.12)]" />
                        在线
                      </span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="relative grid h-8 w-8 place-items-center rounded-xl bg-[#22304b] text-[#8fb4ff]">
                  <CpuIcon size={16} />
                  <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-[#182238] bg-emerald-400" />
                </div>
              )}
            </div>
          ) : null}

          <button
            onClick={onLogout}
            className={`mt-1 flex items-center text-left text-slate-400 transition-smooth hover:bg-white/8 hover:text-white ${
              expanded ? "gap-3 rounded-xl px-3 py-2 text-xs" : "justify-center rounded-xl p-2"
            }`}
          >
            <LogOutIcon size={16} />
            {expanded ? <span className="truncate">{user.account} 退出</span> : null}
          </button>
        </div>
      </div>
    </aside>
  );
}
