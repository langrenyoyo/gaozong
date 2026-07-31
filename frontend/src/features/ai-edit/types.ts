// Phase 12 Task 9 AI 剪辑前端类型定义。
// 冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §10/§11。
// 与 9000 公共 Out 模型对齐（设计 §10：外部 API 不返回 storage_key/merchant_id/执行令牌/绝对路径）。

/** 任务状态冻结枚举（与 9000 AiEditJob.status 对齐）。 */
export type AiEditJobStatus =
  | "queued"
  | "running"
  | "review_required"
  | "cancel_requested"
  | "cancelled"
  | "failed"
  | "succeeded";

/** 任务阶段。 */
export type AiEditJobStage =
  | "preflight"
  | "analyze"
  | "stabilize_optional"
  | "plan_input"
  | "render_preview_720p"
  | "review_required"
  | "render_final_1080p"
  | "verify"
  | "completed";

/** 素材范围。 */
export type AiEditMaterialScope = "merchant" | "platform";

/** 9000 公共素材（不含 storage_key / merchant_id / 绝对路径）。 */
export interface AiEditMaterial {
  material_id: string;
  scope: AiEditMaterialScope;
  media_type: string;
  storage_mode: string;
  source_sha256: string;
  analysis_status: string;
  stabilization_status: string;
  deleted_at: string | null;
  purge_after: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** 9000 公共任务（不含 storage_key / merchant_id / 执行令牌 / 绝对路径）。 */
export interface AiEditJob {
  id: number;
  job_id: string;
  status: AiEditJobStatus;
  source_type: string;
  error_message: string | null;
  completed_at: string | null;
  stage: string | null;
  progress: number;
  attempt_count: number;
  cancel_requested_at: string | null;
  heartbeat_at: string | null;
  engine_version: string | null;
  template_version: string | null;
  model_version: string | null;
  failure_code: string | null;
  error_summary: string | null;
}

/** 9000 模板。 */
export interface AiEditTemplate {
  template_key: string;
  name: string;
  rules_json: unknown;
  prompt_version: string;
  enabled: boolean;
}

/** 9000 列表响应包装。 */
export interface AiEditListResponse<T> {
  total: number;
  items: T[];
}

/** 任务创建请求素材项。 */
export interface AiEditJobMaterialItem {
  material_id: string;
  role: "main" | "broll" | "pip_replacement";
  position?: number;
  pinned_sha256?: string;
  source_start?: number;
  source_end?: number;
}

/** 任务创建请求。 */
export interface AiEditJobCreateRequest {
  job_id: string;
  template_key: string;
  materials: AiEditJobMaterialItem[];
}

/** Local Agent 状态响应（按商户过滤）。 */
export interface LocalAiEditStatus {
  total_enqueued: number;
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  running_count: number;
  queued_count: number;
}

// ===== LAS speech_auto 云端混剪（2026-07-31 重做）=====

/** LAS 混剪任务提交请求。 */
export interface LasJobCreateRequest {
  video_urls: string[];
  script: string;
  template?: string;
  output_tos_path?: string | null;
  idempotent_id?: string | null;
}

/** LAS 产物项。 */
export interface LasArtifact {
  artifact_type: string;
  url: string | null;
  file_name: string | null;
}

/** LAS 任务状态响应。 */
export interface LasJobStatus {
  job_id: number;
  status: string;
  stage: string | null;
  progress: number | null;
  las_task_id: string | null;
  error_message: string | null;
  failure_code: string | null;
  created_at: string | null;
  completed_at: string | null;
  artifacts: LasArtifact[];
}
