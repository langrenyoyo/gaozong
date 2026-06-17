import {
  BotIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CpuIcon,
  DatabaseIcon,
  FilterIcon,
  LogOutIcon,
  MessageCircleMoreIcon,
  MessageSquareIcon,
  MonitorSmartphoneIcon,
  ScissorsIcon,
  ShieldCheckIcon,
  UserCogIcon,
  WalletCardsIcon,
  WrenchIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
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
  { id: "chat", label: "客服", expandedLabel: "抖音AI小高客服", path: "/" },
  { id: "douyin-ai-cs-test", label: "测试", expandedLabel: "抖音AI客服测试", path: "/douyin-ai-cs-test" },
  { id: "leads", label: "线索", expandedLabel: "AI小高线索", path: "/leads" },
  { id: "ai-agent", label: "助手", expandedLabel: "小高AI微信助手", path: "/ai-agent" },
  { id: "ai-edit", label: "剪辑", expandedLabel: "AI小高剪辑", path: "/ai-edit" },
  { id: "assets", label: "素材", expandedLabel: "小高素材库", path: "/assets" },
  { id: "compute", label: "算力", expandedLabel: "小高算力", path: "/compute" },
];

const superNavItems: Array<NavItem & { expandedLabel: string }> = [
  { id: "merchant-agent", label: "智能体", expandedLabel: "商户智能体", path: "/merchant-agent" },
  { id: "merchant-management", label: "商户", expandedLabel: "商户管理", path: "/merchant-management" },
  { id: "forbidden-words", label: "词库", expandedLabel: "违禁词库", path: "/forbidden-words" },
  { id: "follow-up-prompts", label: "回访", expandedLabel: "回访提示词", path: "/follow-up-prompts" },
  { id: "ai-reply-records", label: "回复", expandedLabel: "AI回复记录", path: "/ai-reply-records" },
  { id: "compute-config", label: "算力", expandedLabel: "算力配置", path: "/compute-config" },
  { id: "admin-accounts", label: "账号", expandedLabel: "管理员账号", path: "/admin-accounts" },
];

const navIcons: Record<string, React.ReactNode> = {
  "douyin-ai-cs": <MessageCircleMoreIcon size={18} />,
  chat: <MessageSquareIcon size={18} />,
  "douyin-ai-cs-test": <WrenchIcon size={18} />,
  leads: <FilterIcon size={18} />,
  "ai-agent": <BotIcon size={18} />,
  "ai-edit": <ScissorsIcon size={18} />,
  assets: <DatabaseIcon size={18} />,
  compute: <CpuIcon size={18} />,
  "merchant-agent": <BotIcon size={18} />,
  "merchant-management": <DatabaseIcon size={18} />,
  "forbidden-words": <ShieldCheckIcon size={18} />,
  "follow-up-prompts": <MessageCircleMoreIcon size={18} />,
  "ai-reply-records": <MessageSquareIcon size={18} />,
  "compute-config": <CpuIcon size={18} />,
  "admin-accounts": <UserCogIcon size={18} />,
};

export default function SideNav({
  activeNav = "chat",
  onNavChange = () => {},
  expanded = false,
  onExpandedChange = () => {},
  onLogout = () => {},
  showSalesBadge = false,
  user = { account: "18578790007", role: "merchant", roleLabel: "商户账号" },
}: SideNavProps) {
  const [panel, setPanel] = useState<"profile" | null>(null);
  const [panelView, setPanelView] = useState<"home" | "personal">("home");
  const profileButtonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const isAdminUser = user.role !== "merchant";
  const visibleNavItems = isAdminUser ? superNavItems : navItems;

  const openPanel = () => {
    if (panel === "profile") {
      setPanel(null);
      setPanelView("home");
      return;
    }
    setPanel("profile");
    setPanelView("home");
  };

  useEffect(() => {
    if (!panel) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || profileButtonRef.current?.contains(target)) {
        return;
      }
      setPanel(null);
      setPanelView("home");
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [panel]);

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
          className={`flex min-w-0 items-center rounded-2xl text-left transition-smooth ${
            expanded ? "gap-3" : "hover:scale-105"
          }`}
          aria-label={expanded ? "收起导航" : "展开导航"}
        >
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-[#2563eb] text-white shadow-[0_12px_30px_rgba(37,99,235,0.34)]">
            <BotIcon size={19} />
          </div>
          {expanded ? (
            <div className="min-w-0">
              <div className="truncate text-sm font-bold text-white">小高AI系统</div>
              <div className="mt-0.5 truncate text-[10px] text-slate-500">AI 工作台</div>
            </div>
          ) : null}
        </button>
      </div>

      <nav className={`flex flex-1 flex-col gap-1.5 pt-4 ${expanded ? "px-3" : "items-center"}`}>
        {visibleNavItems.map((item) => {
          const isActive = activeNav === item.id;
          const badge = item.id === "chat" && showSalesBadge ? 6 : item.badge;
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
              <span className={`${expanded ? "truncate" : "leading-tight"}`}>
                {expanded ? item.expandedLabel : item.label}
              </span>
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
              expanded
                ? "w-full rounded-xl px-3 py-3"
                : "grid h-12 w-12 place-items-center rounded-xl"
            }`}
          >
            {expanded ? (
              <div className="flex items-center gap-3">
                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[#22304b] text-[#8fb4ff]">
                  <ShieldCheckIcon size={17} />
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
                <ShieldCheckIcon size={16} />
                <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-[#182238] bg-emerald-400" />
              </div>
            )}
          </div>
        ) : null}

        <button
          ref={profileButtonRef}
          onClick={openPanel}
          className={`mt-1 flex items-center text-left transition-smooth hover:bg-white/8 ${
            panel === "profile" ? "bg-white/10" : ""
          } ${expanded ? "gap-3 rounded-xl px-3 py-2" : "justify-center rounded-xl p-1"}`}
        >
          <img
            src="https://api.dicebear.com/7.x/avataaars/svg?seed=admin&backgroundColor=b6e3f4"
            alt="管理员"
            className="h-8 w-8 rounded-full bg-[#2d3a54]"
          />
          {expanded ? (
            <div className="min-w-0">
              <div className="truncate text-xs font-semibold text-slate-200">{user.account}</div>
              <div className="mt-0.5 text-[10px] text-slate-500">{user.roleLabel}</div>
            </div>
          ) : null}
        </button>
      </div>
      </div>

      {panel ? (
        <div
          ref={panelRef}
          className={`absolute bottom-[74px] z-20 rounded-2xl border border-white/10 bg-[#182238] p-4 text-white shadow-[0_24px_70px_rgba(7,13,28,0.42)] ${
            expanded ? "left-3 w-[220px]" : "left-2 w-[236px]"
          }`}
        >
          {panelView === "home" ? (
            <>
              <div className="flex items-center gap-3">
                <img
                  src="https://api.dicebear.com/7.x/avataaars/svg?seed=admin&backgroundColor=b6e3f4"
                  alt="鐢ㄦ埛澶村儚"
                  className="h-12 w-12 rounded-xl bg-white/12"
                />
                <div className="min-w-0">
                  <div className="truncate text-base font-bold">{user.account}</div>
                  <div className="mt-1 text-xs text-white/58">{user.roleLabel}</div>
                </div>
              </div>

              <div className="my-4 h-px bg-white/12" />

              <div className="grid gap-2 text-xs">
                <div className="flex h-9 items-center justify-between rounded-lg bg-[#22304b] px-3">
                  <span className="inline-flex items-center gap-2 text-white/60">
                    <CpuIcon size={14} />
                    绠楀姏
                  </span>
                  <b className="text-[#8fb4ff]">38752676</b>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                {[
                  { label: "个人设置", icon: <UserCogIcon size={15} />, action: () => setPanelView("personal") },
                  { label: "充值", icon: <WalletCardsIcon size={15} /> },
                ].map((item) => (
                  <button
                    key={item.label}
                    onClick={item.action}
                    className="grid h-[58px] place-items-center rounded-lg bg-[#22304b] text-white/72 transition-smooth hover:bg-[#2563eb] hover:text-white"
                  >
                    <span>{item.icon}</span>
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>

              <div className="my-4 h-px bg-white/12" />

              <button
                onClick={() => {
                  setPanel(null);
                  onLogout();
                }}
                className="flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-[#26344f] text-xs font-semibold text-[#fca5a5] transition-smooth hover:bg-[#33445f]"
              >
                <LogOutIcon size={15} />
                退出登录
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPanelView("home")}
                  className="grid h-8 w-8 place-items-center rounded-lg bg-[#22304b] text-white/70 hover:bg-[#2563eb] hover:text-white"
                >
                  <ChevronLeftIcon size={15} />
                </button>
                <div>
                  <div className="text-sm font-bold">个人设置</div>
                  <div className="mt-0.5 text-[11px] text-white/50">账号安全与个人资料</div>
                </div>
              </div>

              <div className="my-4 h-px bg-white/12" />

              <div className="grid gap-2 text-xs">
                {[
                  { label: "账号资料", desc: "头像、手机号与账号信息", icon: <UserCogIcon size={15} /> },
                  { label: "修改密码", desc: "更新当前登录密码", icon: <ShieldCheckIcon size={15} /> },
                  { label: "登录设备", desc: "查看最近登录设备", icon: <MonitorSmartphoneIcon size={15} /> },
                ].map((item) => (
                  <button
                    key={item.label}
                    className="flex items-center gap-3 rounded-xl bg-[#22304b] px-3 py-3 text-left transition-smooth hover:bg-[#2563eb]"
                  >
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/10 text-white/78">
                      {item.icon}
                    </span>
                    <span className="min-w-0">
                      <span className="block font-semibold text-white">{item.label}</span>
                      <span className="mt-0.5 block truncate text-[11px] text-white/52">{item.desc}</span>
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}

          <span
            className={`absolute -bottom-2 h-4 w-4 rotate-45 border-b border-r border-white/10 bg-[#182238] ${
              expanded ? "left-7" : "left-8"
            }`}
          />
        </div>
      ) : null}
    </aside>
  );
}
