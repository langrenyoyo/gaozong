import type { AppUser } from "../App";
import type { CapabilityNavCenter } from "./types";

export const PERMISSIONS = {
  use: "auto_wechat:use",
  douyinAiCs: "auto_wechat:douyin_ai_cs",
  leads: "auto_wechat:leads",
  agent: "auto_wechat:agent",
  compute: "auto_wechat:compute",
  // AI剪辑与一键过审共用入口权限，不新增拆分权限码。
  aiEdit: "auto_wechat:ai_edit",
  adminAutoreply: "auto_wechat:admin:autoreply",
  adminAiReplyRecords: "auto_wechat:admin:ai_reply_records",
  adminComputeConfig: "auto_wechat:admin:compute_config",
  adminAccounts: "auto_wechat:admin:accounts",
  adminForbiddenWords: "auto_wechat:admin:forbidden_words",
  adminReturnVisitPrompts: "auto_wechat:admin:return_visit_prompts",
} as const;

const legacyPermissionAliases: Record<string, string[]> = {
  [PERMISSIONS.agent]: ["auto_wechat:wechat_assistant", "auto_wechat:wechat_agent"],
};

export const capabilityNavCenters: CapabilityNavCenter[] = [
  {
    id: "douyin-cs",
    title: "抖音AI小高客服",
    shortLabel: "客服",
    path: "/douyin-cs/workbench",
    defaultNavId: "douyin-ai-cs",
    permissionCodes: [PERMISSIONS.douyinAiCs],
    children: [
      { id: "douyin-ai-cs", label: "客服工作台", path: "/douyin-cs/workbench" },
      { id: "douyin-auto-reply-diagnostics", label: "自动回复诊断", path: "/douyin-cs/auto-reply-runs" },
    ],
  },
  {
    id: "leads-center",
    title: "AI小高线索",
    shortLabel: "线索",
    path: "/leads",
    defaultNavId: "leads",
    permissionCodes: [PERMISSIONS.leads],
    children: [
      { id: "leads", label: "AI小高线索", path: "/leads" },
    ],
  },
  {
    id: "agents-center",
    title: "AI小高智能体",
    shortLabel: "智能体",
    path: "/agents",
    defaultNavId: "ai-agents",
    permissionCodes: [PERMISSIONS.douyinAiCs],
    children: [
      { id: "ai-agents", label: "智能体管理", path: "/agents" },
    ],
  },
  {
    id: "wechat-assistant",
    title: "AI小高微信助手",
    shortLabel: "微信",
    path: "/wechat-assistant",
    defaultNavId: "ai-agent",
    permissionCodes: [PERMISSIONS.agent],
    children: [
      { id: "ai-agent", label: "AI小高助手状态", path: "/wechat-assistant" },
      { id: "wechat-config", label: "微信配置", path: "/wechat-assistant/config" },
      { id: "wechat-tasks", label: "任务记录", path: "/wechat-assistant/tasks" },
      { id: "wechat-download-test", label: "下载/测试", path: "/wechat-assistant/download-test" },
      { id: "wechat-daily-reports", label: "每日报表", path: "/wechat-assistant/daily-reports" },
    ],
  },
  {
    id: "ai-edit-center",
    title: "AI小高剪辑",
    shortLabel: "剪辑",
    path: "/ai-edit/materials",
    defaultNavId: "ai-edit-materials",
    permissionCodes: [PERMISSIONS.aiEdit],
    children: [
      { id: "ai-edit-materials", label: "素材库", path: "/ai-edit/materials" },
      { id: "ai-edit-editor", label: "剪辑工作台", path: "/ai-edit/editor" },
    ],
  },
  {
    id: "compute-center",
    title: "AI小高算力",
    shortLabel: "算力",
    path: "/compute/center",
    defaultNavId: "compute",
    permissionCodes: [PERMISSIONS.compute],
    children: [
      { id: "compute", label: "算力中心", path: "/compute/center" },
      { id: "compute-token-transactions", label: "Token流水", path: "/compute/token-transactions" },
      { id: "compute-recharge-orders", label: "充值订单", path: "/compute/recharge-orders" },
      { id: "compute-packages", label: "套餐配置", path: "/compute/packages", permissionCodes: [PERMISSIONS.adminComputeConfig] },
      { id: "compute-markup-ratios", label: "上浮比例", path: "/compute/markup-ratios", permissionCodes: [PERMISSIONS.adminComputeConfig] },
    ],
  },
];

export const merchantNavItems = capabilityNavCenters.flatMap((center) => center.children);

export function isSuperAdmin(user: Pick<AppUser, "role"> | null | undefined): boolean {
  return user?.role === "super_admin";
}

export function isMockAuthUser(
  user: Pick<AppUser, "permissions" | "authMode" | "sourceSystem"> | null | undefined,
): boolean {
  if (!user) return false;
  const permissions = user.permissions || [];
  return user.authMode === "mock" || user.sourceSystem === "mock" || permissions.includes("*");
}

export function hasPermission(
  user: Pick<AppUser, "permissions" | "role" | "authMode" | "sourceSystem"> | null | undefined,
  code: string,
): boolean {
  if (!user) return false;
  if (isMockAuthUser(user)) return true;
  if (isSuperAdmin(user)) return true;
  const permissions = user.permissions || [];
  return permissions.includes(code) || (legacyPermissionAliases[code] || []).some((alias) => permissions.includes(alias));
}

export function hasAnyPermission(
  user: Pick<AppUser, "permissions" | "role" | "authMode" | "sourceSystem"> | null | undefined,
  codes: string[],
): boolean {
  return codes.some((code) => hasPermission(user, code));
}

export function hasAdminPermission(
  user: Pick<AppUser, "permissions" | "role" | "authMode" | "sourceSystem"> | null | undefined,
): boolean {
  if (!user) return false;
  if (isMockAuthUser(user)) return true;
  if (isSuperAdmin(user)) return true;
  return (user.permissions || []).some((code) => code.startsWith("auto_wechat:admin:"));
}

export const isAdminLike = hasAdminPermission;

export function filterCapabilityNavCenters(user: AppUser): CapabilityNavCenter[] {
  return capabilityNavCenters
    .map((center) => ({
      ...center,
      children: center.children.filter((item) => hasAnyPermission(user, item.permissionCodes || center.permissionCodes)),
    }))
    .filter((center) => center.children.length > 0);
}

export function findCapabilityByNavId(navId: string, user?: AppUser | null): CapabilityNavCenter {
  const centers = user ? filterCapabilityNavCenters(user) : capabilityNavCenters;
  return centers.find((center) => center.children.some((item) => item.id === navId)) || centers[0] || capabilityNavCenters[0];
}
