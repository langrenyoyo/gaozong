import {
  BotIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CoinsIcon,
  CpuIcon,
  FilterIcon,
  LogOutIcon,
  MessageCircleMoreIcon,
  MessagesSquareIcon,
  ScissorsIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { AppUser } from "../App";
import {
  filterCapabilityNavCenters,
  findCapabilityByNavId,
  hasPermission,
  isAdminLike,
  isMockAuthUser,
  PERMISSIONS,
} from "../features/capabilities";

interface SideNavProps {
  activeNav?: string;
  onNavChange?: (id: string) => void;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  onLogout?: () => void;
  showSalesBadge?: boolean;
  user?: AppUser;
}

const centerIcons: Record<string, React.ReactNode> = {
  "douyin-cs": <MessageCircleMoreIcon size={18} />,
  "leads-center": <FilterIcon size={18} />,
  "agents-center": <BotIcon size={18} />,
  "wechat-assistant": <ShieldCheckIcon size={18} />,
  "compute-center": <CoinsIcon size={18} />,
  "ai-edit-center": <ScissorsIcon size={18} />,
};

const adminItems = [
  {
    id: "admin-autoreply-rollout",
    label: "发送",
    expandedLabel: "自动回复灰度",
    path: "/admin/autoreply-rollout",
    permission: PERMISSIONS.adminAutoreply,
  },
  {
    id: "admin-return-visits",
    label: "回访",
    expandedLabel: "回访配置",
    path: "/admin/return-visits",
    permission: PERMISSIONS.adminReturnVisitPrompts,
  },
  {
    id: "ai-reply-records",
    label: "回复",
    expandedLabel: "AI回复记录",
    path: "/admin/ai-reply-records",
    permission: PERMISSIONS.adminAiReplyRecords,
  },
];

const adminIcons: Record<string, React.ReactNode> = {
  "admin-autoreply-rollout": <ShieldAlertIcon size={18} />,
  "admin-return-visits": <MessagesSquareIcon size={18} />,
  "ai-reply-records": <MessageCircleMoreIcon size={18} />,
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
  const isAdminUser = isAdminLike(user);
  const isMockUser = isMockAuthUser(user);
  const visibleAdminItems = adminItems.filter((item) => canViewAdminItem(user, item.permission));
  const visibleCenters = filterCapabilityNavCenters(user);
  const activeCenter = findCapabilityByNavId(activeNav, user);
  const navigate = useNavigate();

  const navigateMerchantItem = (id: string, path: string) => {
    onNavChange(id);
    navigate(path);
  };

  const navigateAdminItem = (id: string, path: string) => {
    onNavChange(id);
    navigate(path);
  };

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
            className={`flex min-w-0 items-center rounded-xl text-left transition-smooth ${expanded ? "gap-3" : "hover:scale-105"}`}
            aria-label={expanded ? "收起导航" : "展开导航"}
          >
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#2563eb] text-white shadow-[0_12px_30px_rgba(37,99,235,0.34)]">
              <BotIcon size={19} />
            </div>
            {expanded ? (
              <div className="min-w-0">
                <div className="truncate text-sm font-bold text-white">小高AI系统</div>
                <div className="mt-0.5 truncate text-[10px] text-slate-500">能力中心</div>
              </div>
            ) : null}
          </button>
        </div>

        <nav className={`flex flex-1 flex-col gap-1.5 overflow-y-auto pt-4 ${expanded ? "px-3" : "items-center"}`}>
          {isAdminUser && !isMockUser
            ? visibleAdminItems.map((item) => {
                const isActive = activeNav === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => navigateAdminItem(item.id, item.path)}
                    className={`relative flex transition-smooth ${
                      expanded
                        ? "h-10 w-full flex-row items-center gap-3 rounded-xl px-3 text-xs font-semibold"
                        : "w-16 flex-col items-center gap-1 rounded-xl py-2.5 text-[10px]"
                    } ${
                      isActive
                        ? "bg-[#2563eb] text-white shadow-[0_12px_24px_rgba(37,99,235,0.28)]"
                        : "text-slate-400 hover:bg-white/8 hover:text-white"
                    }`}
                  >
                    <span className="shrink-0">{adminIcons[item.id]}</span>
                    <span className={expanded ? "truncate" : "leading-tight"}>{expanded ? item.expandedLabel : item.label}</span>
                  </button>
                );
              })
            : visibleCenters.map((center) => {
                const isCenterActive = activeCenter.id === center.id;
                const showChildren = expanded && isCenterActive && center.children.length > 1;
                return (
                  <div key={center.id} className={expanded ? "w-full" : ""}>
                    <button
                      onClick={() => navigateMerchantItem(center.defaultNavId, center.path)}
                      className={`relative flex transition-smooth ${
                        expanded
                          ? "h-10 w-full flex-row items-center gap-3 rounded-xl px-3 text-xs font-semibold"
                          : "w-16 flex-col items-center gap-1 rounded-xl py-2.5 text-[10px]"
                      } ${
                        isCenterActive
                          ? "bg-[#2563eb] text-white shadow-[0_12px_24px_rgba(37,99,235,0.28)]"
                          : "text-slate-400 hover:bg-white/8 hover:text-white"
                      }`}
                    >
                      <span className="shrink-0">{centerIcons[center.id]}</span>
                      <span className={expanded ? "truncate" : "leading-tight"}>{expanded ? center.title : center.shortLabel}</span>
                      {center.id === "douyin-cs" && showSalesBadge ? (
                        <span className={`grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[9px] font-bold text-white ${expanded ? "" : "absolute right-1.5 top-1.5"}`}>
                          6
                        </span>
                      ) : null}
                    </button>
                    {showChildren ? (
                      <div className="mt-1.5 space-y-1 pl-8">
                        {center.children.map((item) => {
                          const isChildActive = activeNav === item.id;
                          return (
                            <button
                              key={item.id}
                              onClick={() => navigateMerchantItem(item.id, item.path)}
                              className={`h-8 w-full rounded-lg px-3 text-left text-[11px] font-semibold transition-smooth ${
                                isChildActive
                                  ? "bg-white/12 text-white"
                                  : "text-slate-500 hover:bg-white/8 hover:text-slate-200"
                              }`}
                            >
                              <span className="block truncate">{item.label}</span>
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                );
              })}
          {isMockUser && visibleAdminItems.length > 0
            ? visibleAdminItems.map((item) => {
                const isActive = activeNav === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => navigateAdminItem(item.id, item.path)}
                    className={`relative flex transition-smooth ${
                      expanded
                        ? "h-10 w-full flex-row items-center gap-3 rounded-xl px-3 text-xs font-semibold"
                        : "w-16 flex-col items-center gap-1 rounded-xl py-2.5 text-[10px]"
                    } ${
                      isActive
                        ? "bg-[#2563eb] text-white shadow-[0_12px_24px_rgba(37,99,235,0.28)]"
                        : "text-slate-400 hover:bg-white/8 hover:text-white"
                    }`}
                  >
                    <span className="shrink-0">{adminIcons[item.id]}</span>
                    <span className={expanded ? "truncate" : "leading-tight"}>{expanded ? item.expandedLabel : item.label}</span>
                  </button>
                );
              })
            : null}
        </nav>

        <div className={`flex flex-col gap-2 pb-4 ${expanded ? "px-3" : "items-center"}`}>
          <button
            onClick={() => onExpandedChange(!expanded)}
            aria-label={expanded ? "收起导航" : "展开导航"}
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
                      <span className="truncate text-xs font-semibold text-slate-200">AI小高微信助手</span>
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
            aria-label="退出登录"
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

function canViewAdminItem(user: AppUser, permission: string): boolean {
  return hasPermission(user, permission);
}
