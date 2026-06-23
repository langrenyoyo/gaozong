import { agentsRoutes } from "./agents/routes";
import { computeRoutes } from "./compute/routes";
import { douyinCsRoutes } from "./douyin-cs/routes";
import { leadsRoutes } from "./leads/routes";
import { wechatAssistantRoutes } from "./wechat-assistant/routes";
import type { CapabilityRoute, LegacyRouteRedirect } from "./types";

export const capabilityRoutes: CapabilityRoute[] = [
  ...douyinCsRoutes,
  ...leadsRoutes,
  ...agentsRoutes,
  ...wechatAssistantRoutes,
  ...computeRoutes,
];

export const legacyRouteRedirects: LegacyRouteRedirect[] = [
  { from: "/douyin-ai-cs", to: "/douyin-cs/workbench" },
  { from: "/douyin-ai-cs/reply-records", to: "/douyin-cs/workbench" },
  { from: "/douyin-ai-cs/auto-reply-settings", to: "/douyin-cs/auto-reply-settings" },
  { from: "/douyin-ai-cs/auto-reply-runs", to: "/douyin-cs/workbench" },
  { from: "/douyin-cs/reply-records", to: "/douyin-cs/workbench" },
  { from: "/douyin-cs/auto-reply-runs", to: "/douyin-cs/workbench" },
  { from: "/douyin-ai-cs-test", to: "/douyin-cs/workbench" },
  { from: "/leads/list", to: "/leads" },
  { from: "/leads/board", to: "/leads" },
  { from: "/leads/detail", to: "/leads" },
  { from: "/leads/conversations", to: "/leads" },
  { from: "/ai-agent", to: "/wechat-assistant" },
  { from: "/agents/new", to: "/agents" },
  { from: "/agents/edit", to: "/agents" },
  { from: "/agents/knowledge-categories", to: "/agents" },
  { from: "/compute", to: "/compute/center" },
  { from: "/knowledge-base", to: "/douyin-cs/workbench" },
  { from: "/knowledge-categories", to: "/douyin-cs/workbench" },
  { from: "/knowledge/base", to: "/douyin-cs/workbench" },
  { from: "/knowledge/categories", to: "/douyin-cs/workbench" },
];
