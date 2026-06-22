import type { CapabilityNavCenter } from "./types";

export const capabilityNavCenters: CapabilityNavCenter[] = [
  {
    id: "douyin-cs",
    title: "抖音AI小高客服",
    shortLabel: "客服",
    path: "/douyin-cs/workbench",
    defaultNavId: "douyin-ai-cs",
    children: [
      { id: "douyin-ai-cs", label: "抖音AI小高客服", path: "/douyin-cs/workbench" },
    ],
  },
  {
    id: "leads-center",
    title: "AI小高线索",
    shortLabel: "线索",
    path: "/leads",
    defaultNavId: "leads",
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
    children: [
      { id: "ai-agent", label: "Local Agent状态", path: "/wechat-assistant" },
      { id: "wechat-config", label: "微信配置", path: "/wechat-assistant/config" },
      { id: "wechat-tasks", label: "任务记录", path: "/wechat-assistant/tasks" },
      { id: "wechat-download-test", label: "下载/测试", path: "/wechat-assistant/download-test" },
    ],
  },
  {
    id: "compute-center",
    title: "小高算力",
    shortLabel: "算力",
    path: "/compute/center",
    defaultNavId: "compute",
    children: [
      { id: "compute", label: "算力中心", path: "/compute/center" },
      { id: "compute-token-transactions", label: "Token流水", path: "/compute/token-transactions" },
      { id: "compute-recharge-orders", label: "充值订单", path: "/compute/recharge-orders" },
      { id: "compute-packages", label: "套餐配置", path: "/compute/packages" },
    ],
  },
  {
    id: "knowledge-center",
    title: "小高知识库",
    shortLabel: "知识",
    path: "/knowledge/base",
    defaultNavId: "knowledge-base",
    children: [
      { id: "knowledge-base", label: "小高知识库", path: "/knowledge/base" },
    ],
  },
];

export const merchantNavItems = capabilityNavCenters.flatMap((center) => center.children);

export function findCapabilityByNavId(navId: string): CapabilityNavCenter {
  return capabilityNavCenters.find((center) => center.children.some((item) => item.id === navId)) || capabilityNavCenters[0];
}
