import type { CapabilityRoute } from "../types";

export const leadsRoutes: CapabilityRoute[] = [
  { path: "/leads/list", navId: "leads" },
  { path: "/leads/board", navId: "lead-board" },
  { path: "/leads/detail", navId: "lead-detail" },
  { path: "/leads/conversations", navId: "lead-conversations" },
];
