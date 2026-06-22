import type { CapabilityRoute } from "../types";

export const wechatAssistantRoutes: CapabilityRoute[] = [
  { path: "/wechat-assistant", navId: "ai-agent" },
  { path: "/wechat-assistant/config", navId: "wechat-config" },
  { path: "/wechat-assistant/tasks", navId: "wechat-tasks" },
  { path: "/wechat-assistant/download-test", navId: "wechat-download-test" },
];
