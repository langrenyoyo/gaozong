import {
  BotIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CoinsIcon,
  CpuIcon,
  ExternalLinkIcon,
  FilterIcon,
  KeyRoundIcon,
  LoaderCircleIcon,
  LogOutIcon,
  MessageCircleMoreIcon,
  MessagesSquareIcon,
  ScissorsIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppUser } from "../App";
// 复用 NewCar 的 avatar.svg，保留其中 Avataaars 授权信息。
import avatarUrl from "../assets/avatar.svg";
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
  onSwitchToNewCar?: () => void;
  switchingToNewCar?: boolean;
  onChangePassword?: () => void;
  changingPassword?: boolean;
  onAdminLogout?: () => void;
  adminLoggingOut?: boolean;
  showSalesBadge?: boolean;
  localAgentOnline?: boolean;
  localAgentVersion?: string | null;
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
  {
    id: "admin-forbidden-words",
    label: "违禁词",
    expandedLabel: "违禁词配置",
    path: "/admin/forbidden-words",
    permission: PERMISSIONS.adminForbiddenWords,
  },
  {
    id: "admin-compute-config",
    label: "算力",
    expandedLabel: "算力配置",
    path: "/admin/compute-config",
    permission: PERMISSIONS.adminComputeConfig,
  },
];

const adminIcons: Record<string, React.ReactNode> = {
  "admin-return-visits": <MessagesSquareIcon size={18} />,
  "ai-reply-records": <MessageCircleMoreIcon size={18} />,
  "admin-forbidden-words": <ShieldCheckIcon size={18} />,
  "admin-compute-config": <CoinsIcon size={18} />,
};

export default function SideNav({
  activeNav = "douyin-ai-cs",
  onNavChange = () => {},
  expanded = false,
  onExpandedChange = () => {},
  onLogout = () => {},
  onSwitchToNewCar = () => {},
  switchingToNewCar = false,
  onChangePassword = () => {},
  changingPassword = false,
  onAdminLogout = () => {},
  adminLoggingOut = false,
  showSalesBadge = false,
  localAgentOnline = false,
  localAgentVersion = null,
  user = { account: "18578790007", role: "merchant", roleLabel: "商户账号" },
}: SideNavProps) {
  const isAdminUser = isAdminLike(user);
  const isMockUser = isMockAuthUser(user);
  const visibleAdminItems = adminItems.filter((item) => canViewAdminItem(user, item.permission));
  const visibleCenters = filterCapabilityNavCenters(user);
  const activeCenter = findCapabilityByNavId(activeNav, user);
  const navigate = useNavigate();
  // 账号卡片下拉菜单的展开状态，对齐 NewCar account-menu：点击卡片切换、点击动作关闭、收起导航时关闭。
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const toggleExpanded = () => {
    setAccountMenuOpen(false);
    onExpandedChange(!expanded);
  };

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
            onClick={toggleExpanded}
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
                return (
                  <button
                    key={center.id}
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
                      <span className="truncate text-xs font-semibold text-slate-200">小高AI系统测试版</span>
                      <span className="text-[11px] font-bold text-[#8fb4ff]">{localAgentVersion || "-"}</span>
                    </div>
                    <div className="mt-1 flex items-center justify-between gap-2 text-[11px]">
                      <span className="text-slate-500">状态</span>
                      <span className={localAgentOnline ? "inline-flex items-center gap-1.5 font-semibold text-emerald-400" : "inline-flex items-center gap-1.5 font-semibold text-rose-400"}>
                        <span className={localAgentOnline ? "h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_0_4px_rgba(52,211,153,0.12)]" : "h-2 w-2 rounded-full bg-rose-400 shadow-[0_0_0_4px_rgba(251,113,133,0.12)]"} />
                        {localAgentOnline ? "在线" : "离线"}
                      </span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="relative grid h-8 w-8 place-items-center rounded-xl bg-[#22304b] text-[#8fb4ff]">
                  <CpuIcon size={16} />
                  <span className={localAgentOnline ? "absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-[#182238] bg-emerald-400" : "absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-[#182238] bg-rose-400"} />
                </div>
              )}
            </div>
          ) : null}

          {isAdminUser ? (
            <button
              type="button"
              onClick={onSwitchToNewCar}
              disabled={switchingToNewCar}
              aria-label={switchingToNewCar ? "正在切换到内部管理系统" : "切换到内部管理系统"}
              title={switchingToNewCar ? "正在切换到内部管理系统" : "切换到内部管理系统"}
              className={`flex items-center rounded-xl border border-[#f59e0b] bg-[#fff7ed] text-[#7c2d12] shadow-[0_10px_24px_rgba(245,158,11,0.22)] transition-smooth hover:bg-[#ffedd5] disabled:cursor-wait disabled:opacity-70 ${
                expanded ? "w-full gap-2.5 px-3 py-2.5" : "h-12 w-12 justify-center"
              }`}
            >
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-[#f59e0b] text-[#111827]">
                {switchingToNewCar ? <LoaderCircleIcon size={18} className="animate-spin" /> : <ExternalLinkIcon size={18} />}
              </span>
              {expanded ? (
                <span className="grid min-w-0 gap-0.5">
                  <span className="truncate text-xs font-bold">{switchingToNewCar ? "正在切换" : "切换到内部系统"}</span>
                  <span className="truncate text-[11px] text-[#9a3412]">内部系统管理入口</span>
                </span>
              ) : null}
            </button>
          ) : null}

          <button
            onClick={toggleExpanded}
            aria-label={expanded ? "收起导航" : "展开导航"}
            title={expanded ? "收起导航" : "展开导航"}
            className={`flex h-10 items-center rounded-xl border border-white/10 bg-[#22304b] text-white transition-smooth hover:bg-[#2a3a5c] ${
              expanded ? "w-full gap-2 px-3 text-left text-xs" : "w-12 justify-center"
            }`}
          >
            {expanded ? <ChevronLeftIcon size={16} /> : <ChevronRightIcon size={16} />}
            {expanded ? <span>收起导航</span> : null}
          </button>

          <div className={`relative ${expanded ? "w-full" : "w-12"}`}>
            {accountMenuOpen ? (
              <div
                className={`absolute z-20 grid gap-1 overflow-hidden rounded-2xl border border-slate-200 bg-white p-2.5 text-slate-700 shadow-[0_18px_44px_rgba(15,23,42,0.28)] ${
                  expanded ? "inset-x-0 bottom-[56px]" : "bottom-[56px] left-0 w-[220px]"
                }`}
              >
                <strong className="truncate text-xs font-semibold text-[#1a1f2e]">{user.account}</strong>
                <span className="mb-1.5 truncate text-[10px] text-slate-500">{user.roleLabel}</span>
                {isAdminUser ? (
                  <button
                    type="button"
                    onClick={() => {
                      setAccountMenuOpen(false);
                      onAdminLogout();
                    }}
                    disabled={adminLoggingOut}
                    className="flex h-[34px] items-center gap-2 rounded-lg px-2 text-xs font-bold text-[#dc2626] hover:bg-red-50 disabled:cursor-wait disabled:opacity-60"
                  >
                    {adminLoggingOut ? <LoaderCircleIcon size={14} className="animate-spin" /> : <LogOutIcon size={14} />}
                    退出登录
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => {
                        setAccountMenuOpen(false);
                        onChangePassword();
                      }}
                      disabled={changingPassword}
                      className="flex h-[34px] items-center gap-2 rounded-lg px-2 text-xs font-bold text-[#2563eb] hover:bg-blue-50 disabled:cursor-wait disabled:opacity-60"
                    >
                      {changingPassword ? <LoaderCircleIcon size={14} className="animate-spin" /> : <KeyRoundIcon size={14} />}
                      修改密码
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setAccountMenuOpen(false);
                        onLogout();
                      }}
                      className="flex h-[34px] items-center gap-2 rounded-lg px-2 text-xs font-bold text-[#dc2626] hover:bg-red-50"
                    >
                      <LogOutIcon size={14} />
                      退出登录
                    </button>
                  </>
                )}
              </div>
            ) : null}
            <button
              type="button"
              onClick={() => setAccountMenuOpen((value) => !value)}
              aria-label={`${user.account} · ${user.roleLabel}`}
              title={`${user.account} · ${user.roleLabel}`}
              className={`flex items-center rounded-xl bg-[#22304b] text-white transition-smooth hover:bg-[#2a3a5c] ${
                expanded ? "w-full gap-2.5 px-2.5 py-2" : "h-12 w-12 justify-center"
              }`}
            >
              <img src={avatarUrl} alt={user.account} className="h-8 w-8 shrink-0 rounded-full" />
              {expanded ? (
                <span className="grid min-w-0">
                  <span className="truncate text-xs font-semibold">{user.account}</span>
                  <span className="mt-0.5 truncate text-[10px] text-slate-400">{user.roleLabel}</span>
                </span>
              ) : null}
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
}

function canViewAdminItem(user: AppUser, permission: string): boolean {
  return hasPermission(user, permission);
}
