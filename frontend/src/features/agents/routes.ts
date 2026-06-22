import type { CapabilityRoute } from "../types";

export const agentsRoutes: CapabilityRoute[] = [
  { path: "/agents", navId: "ai-agents" },
  { path: "/agents/new", navId: "agent-create" },
  { path: "/agents/edit", navId: "agent-edit" },
  { path: "/agents/knowledge-categories", navId: "agent-knowledge-categories" },
];
