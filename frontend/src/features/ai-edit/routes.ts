import type { CapabilityRoute } from "../types";

// Phase 12 Task 9 AI 剪辑路由：素材库 + 轻量剪辑工作台。
// 一键过审已 CANCELLED_BY_CUSTOMER，不新增过审入口。
export const aiEditRoutes: CapabilityRoute[] = [
  { path: "/ai-edit/materials", navId: "ai-edit-materials" },
  { path: "/ai-edit/editor", navId: "ai-edit-editor" },
];
