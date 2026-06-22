export interface CapabilityRoute {
  path: string;
  navId: string;
}

export interface LegacyRouteRedirect {
  from: string;
  to: string;
}

export const capabilityRoutes: CapabilityRoute[] = [
  { path: "/douyin-cs/workbench", navId: "douyin-ai-cs" },
  { path: "/douyin-cs/reply-records", navId: "douyin-ai-cs-reply-records" },
  { path: "/douyin-cs/auto-reply-settings", navId: "douyin-ai-cs-auto-reply-settings" },
  { path: "/douyin-cs/auto-reply-runs", navId: "douyin-ai-cs-auto-reply-runs" },
  { path: "/douyin-cs/test", navId: "douyin-ai-cs-test" },
  { path: "/douyin-cs/accounts", navId: "douyin-accounts" },
  { path: "/leads/list", navId: "leads" },
  { path: "/leads/board", navId: "lead-board" },
  { path: "/leads/detail", navId: "lead-detail" },
  { path: "/leads/conversations", navId: "lead-conversations" },
  { path: "/agents", navId: "ai-agents" },
  { path: "/agents/new", navId: "agent-create" },
  { path: "/agents/edit", navId: "agent-edit" },
  { path: "/agents/knowledge-categories", navId: "agent-knowledge-categories" },
  { path: "/wechat-assistant", navId: "ai-agent" },
  { path: "/wechat-assistant/config", navId: "wechat-config" },
  { path: "/wechat-assistant/tasks", navId: "wechat-tasks" },
  { path: "/wechat-assistant/download-test", navId: "wechat-download-test" },
  { path: "/compute/center", navId: "compute" },
  { path: "/compute/token-transactions", navId: "compute-token-transactions" },
  { path: "/compute/recharge-orders", navId: "compute-recharge-orders" },
  { path: "/compute/packages", navId: "compute-packages" },
  { path: "/knowledge/base", navId: "knowledge-base" },
  { path: "/knowledge/categories", navId: "knowledge-categories" },
  { path: "/knowledge/doc-training", navId: "knowledge-doc-training" },
  { path: "/knowledge/rag-search", navId: "knowledge-rag-search" },
  { path: "/knowledge/training-chat", navId: "knowledge-training-chat" },
];

export const legacyRouteRedirects: LegacyRouteRedirect[] = [
  { from: "/douyin-ai-cs", to: "/douyin-cs/workbench" },
  { from: "/douyin-ai-cs/reply-records", to: "/douyin-cs/reply-records" },
  { from: "/douyin-ai-cs/auto-reply-settings", to: "/douyin-cs/auto-reply-settings" },
  { from: "/douyin-ai-cs/auto-reply-runs", to: "/douyin-cs/auto-reply-runs" },
  { from: "/douyin-ai-cs-test", to: "/douyin-cs/test" },
  { from: "/ai-agent", to: "/wechat-assistant" },
  { from: "/compute", to: "/compute/center" },
  { from: "/knowledge-base", to: "/knowledge/base" },
  { from: "/knowledge-categories", to: "/knowledge/categories" },
];
