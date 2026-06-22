import type { CapabilityNavCenter } from "./types";

export const capabilityNavCenters: CapabilityNavCenter[] = [
  {
    id: "douyin-cs",
    title: "抖音AI小高客服",
    shortLabel: "客服",
    path: "/douyin-cs/workbench",
    defaultNavId: "douyin-ai-cs",
    children: [
      { id: "douyin-ai-cs", label: "客服工作台", path: "/douyin-cs/workbench" },
      { id: "douyin-ai-cs-reply-records", label: "AI回复记录", path: "/douyin-cs/reply-records" },
      { id: "douyin-ai-cs-auto-reply-settings", label: "AI自动回复配置", path: "/douyin-cs/auto-reply-settings" },
      { id: "douyin-ai-cs-auto-reply-runs", label: "自动回复运行记录", path: "/douyin-cs/auto-reply-runs" },
      { id: "douyin-ai-cs-test", label: "抖音客服测试", path: "/douyin-cs/test" },
      { id: "douyin-accounts", label: "抖音企业号管理", path: "/douyin-cs/accounts" },
    ],
  },
  {
    id: "leads-center",
    title: "AI小高线索",
    shortLabel: "线索",
    path: "/leads/list",
    defaultNavId: "leads",
    children: [
      { id: "leads", label: "线索列表", path: "/leads/list" },
      { id: "lead-board", label: "线索看板", path: "/leads/board" },
      { id: "lead-detail", label: "线索详情", path: "/leads/detail" },
      { id: "lead-conversations", label: "对话跟进", path: "/leads/conversations" },
    ],
  },
  {
    id: "agents-center",
    title: "AI小高智能体",
    shortLabel: "智能体",
    path: "/agents",
    defaultNavId: "ai-agents",
    children: [
      { id: "ai-agents", label: "智能体列表", path: "/agents" },
      { id: "agent-create", label: "创建智能体", path: "/agents/new" },
      { id: "agent-edit", label: "编辑智能体", path: "/agents/edit" },
      { id: "agent-knowledge-categories", label: "智能体知识分类绑定", path: "/agents/knowledge-categories" },
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
    title: "统一知识库训练",
    shortLabel: "知识",
    path: "/knowledge/base",
    defaultNavId: "knowledge-base",
    children: [
      { id: "knowledge-base", label: "知识库", path: "/knowledge/base" },
      { id: "knowledge-categories", label: "知识分类", path: "/knowledge/categories" },
      { id: "knowledge-doc-training", label: "文档训练", path: "/knowledge/doc-training" },
      { id: "knowledge-rag-search", label: "RAG搜索测试", path: "/knowledge/rag-search" },
      { id: "knowledge-training-chat", label: "训练对话", path: "/knowledge/training-chat" },
    ],
  },
];

export const merchantNavItems = capabilityNavCenters.flatMap((center) => center.children);

export function findCapabilityByNavId(navId: string): CapabilityNavCenter {
  return capabilityNavCenters.find((center) => center.children.some((item) => item.id === navId)) || capabilityNavCenters[0];
}
