import { agentsRoutes } from "./agents/routes";
import { computeRoutes } from "./compute/routes";
import { douyinCsRoutes } from "./douyin-cs/routes";
import { knowledgeRoutes } from "./knowledge/routes";
import { leadsRoutes } from "./leads/routes";
import { wechatAssistantRoutes } from "./wechat-assistant/routes";
import type { CapabilityRoute, LegacyRouteRedirect } from "./types";

export const capabilityRoutes: CapabilityRoute[] = [
  ...douyinCsRoutes,
  ...leadsRoutes,
  ...agentsRoutes,
  ...wechatAssistantRoutes,
  ...computeRoutes,
  ...knowledgeRoutes,
];

export const legacyRouteRedirects: LegacyRouteRedirect[] = [
  { from: "/douyin-ai-cs", to: "/douyin-cs/workbench" },
  { from: "/douyin-ai-cs/reply-records", to: "/douyin-cs/reply-records" },
  { from: "/douyin-ai-cs/auto-reply-settings", to: "/douyin-cs/auto-reply-settings" },
  { from: "/douyin-ai-cs/auto-reply-runs", to: "/douyin-cs/auto-reply-runs" },
  { from: "/douyin-ai-cs-test", to: "/douyin-cs/workbench" },
  { from: "/ai-agent", to: "/wechat-assistant" },
  { from: "/compute", to: "/compute/center" },
  { from: "/knowledge-base", to: "/knowledge/base" },
  { from: "/knowledge-categories", to: "/knowledge/base" },
];
