export const DEFAULT_LOCAL_AGENT_BASE_URL = "http://127.0.0.1:19000";

export const LOCAL_AGENT_BASE_URL =
  localStorage.getItem("local_wechat_agent_url") || DEFAULT_LOCAL_AGENT_BASE_URL;

export interface LocalAgentHealth {
  success: boolean;
  service: string;
  host: string;
  port: number;
  wechat_agent: boolean;
  agent_machine: {
    hostname: string;
    platform: string;
    pid: number;
  };
}

export interface LocalWechatTestPayload {
  nickname: string;
  message: string;
  mode: "paste_only" | "single_send";
  engine: string;
  position: "left" | "right";
  confirm_before_send?: boolean;
}

export interface LocalWechatTestResult {
  success: boolean;
  agent_machine?: {
    hostname?: string;
    platform?: string;
    pid?: number;
  };
  request?: {
    nickname?: string;
    mode?: string;
  };
  open_chat?: {
    success?: boolean;
    nickname?: string | null;
    failure_stage?: string | null;
    chat_verified?: boolean;
    confidence?: number | null;
    evidence?: unknown;
    search_keyword?: string | null;
    opened_by?: string | null;
    search_action_completed?: boolean;
    search_keyword_pasted?: boolean;
    maybe_chat_opened?: boolean;
    search_focus?: LocalWechatSearchFocus | null;
    notes?: string[];
  };
  verify?: {
    verified?: boolean;
    strategy?: string | null;
    ocr_text?: string | null;
    confidence?: number | null;
    partial_match?: boolean;
    manual_review_required?: boolean;
  };
  action?: {
    pasted?: boolean;
    sent?: boolean;
  };
  evidence?: {
    before?: string | null;
    after?: string | null;
    verify_json?: string | null;
  };
  foreground_debug?: LocalWechatForegroundDebug | null;
  ocr?: LocalWechatOcrStatus | null;
  failure_stage?: string | null;
  message?: string;
}

export interface LocalWechatOcrStatus {
  success: boolean;
  failure_stage?: string | null;
  ocr_available?: boolean;
  ocr_initialized?: boolean;
  model_ready?: boolean;
  initializing?: boolean;
  last_error?: string | null;
  engine?: string;
  cache_dir?: string;
  model_source?: string;
  model_dir?: string;
  download_enabled?: boolean;
  model_files_count?: number;
  model_total_size_mb?: number;
  message?: string;
  notes?: string[];
}

export interface LocalWechatOcrWarmupResult extends LocalWechatOcrStatus {
  started?: boolean;
  message?: string;
}

export interface LocalWechatWindowInfo {
  hwnd: number;
  title: string;
  class_name: string;
  visible: boolean;
  iconic: boolean;
  rect?: {
    left: number;
    top: number;
    right: number;
    bottom: number;
  };
  process_id?: number;
  process_name?: string;
}

export interface LocalWechatWindowsDiagnostic {
  success: boolean;
  agent_machine?: {
    hostname?: string;
    platform?: string;
    pid?: number;
  };
  wechat_detected: boolean;
  wechat_candidates: LocalWechatWindowInfo[];
  all_windows_sample: LocalWechatWindowInfo[];
  notes: string[];
}

export interface ForegroundAttempt {
  method: string;
  success: boolean;
  foreground_after_hwnd?: number;
  foreground_after_title?: string;
  foreground_after_class?: string;
  foreground_after_process_name?: string;
  error?: string | null;
}

export interface LocalWechatForegroundDebug {
  stage?: string;
  wechat_hwnd?: number;
  wechat_title?: string;
  wechat_class?: string;
  wechat_pid?: number;
  wechat_process_name?: string;
  foreground_before_hwnd?: number;
  foreground_before_title?: string;
  foreground_before_class?: string;
  foreground_before_process_name?: string;
  foreground_after_hwnd?: number;
  foreground_after_title?: string;
  foreground_after_class?: string;
  foreground_after_process_name?: string;
  is_wechat_foreground?: boolean;
  reason?: string;
  attempts?: ForegroundAttempt[];
}

export interface LocalWechatForegroundDebugResult {
  success: boolean;
  agent_machine?: {
    hostname?: string;
    platform?: string;
    pid?: number;
  };
  wechat_detected?: boolean;
  foreground_success?: boolean;
  foreground_debug?: LocalWechatForegroundDebug | null;
  failure_stage?: string | null;
  message?: string;
}

export interface LocalWechatSearchDebugPayload {
  nickname: string;
  position: "left" | "right";
}

export interface LocalWechatSearchFocus {
  located?: boolean;
  focused?: boolean;
  search_text_verified?: boolean;
  text_pasted_into_search_box?: boolean;
  text_leaked_to_chat_input?: boolean;
  verified?: boolean;
  success?: boolean;
  failure_stage?: string | null;
  manual?: boolean;
  manual_review_required?: boolean;
  reason?: string | null;
  strategy?: string | null;
  confidence?: number | null;
  ocr_text?: string | null;
  click_point?: LocalWechatSearchDebugResult["click_point"] | null;
  screenshots?: {
    after_paste?: string | null;
  };
  focus_control?: {
    name?: string | null;
    class_name?: string | null;
    control_type?: string | null;
    rect?: {
      left?: number;
      top?: number;
      right?: number;
      bottom?: number;
    } | null;
  } | null;
  search_text_debug?: {
    expected?: string | null;
    verified?: boolean;
    method?: string | null;
    search_box_crop_path?: string | null;
    search_box_overlay_path?: string | null;
    ocr_text?: string | null;
    ocr_items?: Array<{
      text?: string;
      confidence?: number;
      bbox?: number[][][];
    }>;
    normalized_expected?: string | null;
    normalized_ocr_text?: string | null;
    crop_rect?: {
      left?: number;
      top?: number;
      right?: number;
      bottom?: number;
    } | null;
    reason?: string | null;
    result_area_ocr_text?: string | null;
    result_area_contains_expected?: boolean | null;
    result_area_crop_path?: string | null;
    result_area_overlay_path?: string | null;
    click_point_inside_search_box?: boolean;
    text_leaked_to_chat_input?: boolean;
  } | null;
}

export interface LocalWechatSearchDebugResult {
  success: boolean;
  nickname?: string;
  position?: string;
  clicked?: boolean;
  focused?: boolean;
  text_pasted_into_search_box?: boolean;
  text_leaked_to_chat_input?: boolean;
  verified?: boolean;
  manual?: boolean;
  click_point?: {
    success?: boolean;
    x?: number | null;
    y?: number | null;
    strategy?: string;
    confidence?: number;
    reason?: string | null;
    search_box_rect?: {
      left?: number;
      top?: number;
      right?: number;
      bottom?: number;
    };
  } | null;
  screenshots?: {
    before?: string | null;
    overlay?: string | null;
    after_click?: string | null;
    after_paste?: string | null;
  };
  search_focus?: LocalWechatSearchFocus;
  notes?: string[];
  failure_stage?: string | null;
  message?: string;
}

export interface LocalWechatSearchCalibrationResult {
  success: boolean;
  relative_x?: number;
  relative_y?: number;
  absolute_x?: number;
  absolute_y?: number;
  config_path?: string;
  failure_stage?: string | null;
  message?: string;
}

export interface LocalWechatSearchResultDebugResult {
  success: boolean;
  nickname?: string;
  position?: string;
  search_text_verified?: boolean;
  search_result_detected?: boolean;
  search_result?: {
    nickname?: string;
    method?: string | null;
    rect?: {
      left: number;
      top: number;
      right: number;
      bottom: number;
    } | null;
    click_point?: {
      x: number;
      y: number;
    } | null;
    confidence?: number | null;
  } | null;
  screenshots?: {
    after_search_text?: string | null;
    result_area?: string | null;
    overlay?: string | null;
  };
  failure_stage?: string | null;
  message?: string;
  notes?: string[];
  search_text_debug?: LocalWechatSearchFocus["search_text_debug"];
}

async function requestLocalAgent<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${LOCAL_AGENT_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(`本机微信 Agent 请求失败：HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function checkLocalAgentHealth(): Promise<LocalAgentHealth> {
  return requestLocalAgent<LocalAgentHealth>("/health", { method: "GET" });
}

export async function startLocalWechatTest(
  payload: LocalWechatTestPayload,
  signal?: AbortSignal,
): Promise<LocalWechatTestResult> {
  return requestLocalAgent<LocalWechatTestResult>("/agent/wechat/test", {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  });
}

export async function checkLocalWechatOcrStatus(): Promise<LocalWechatOcrStatus> {
  return requestLocalAgent<LocalWechatOcrStatus>("/agent/ocr/status", { method: "GET" });
}

export async function warmupLocalWechatOcr(): Promise<LocalWechatOcrWarmupResult> {
  return requestLocalAgent<LocalWechatOcrWarmupResult>("/agent/ocr/warmup", { method: "POST" });
}

export async function diagnoseLocalWechatWindows(): Promise<LocalWechatWindowsDiagnostic> {
  return requestLocalAgent<LocalWechatWindowsDiagnostic>("/agent/wechat/windows", {
    method: "GET",
  });
}

export async function diagnoseLocalWechatForeground(
  payload: { position: "left" | "right" } = { position: "right" },
): Promise<LocalWechatForegroundDebugResult> {
  return requestLocalAgent<LocalWechatForegroundDebugResult>("/agent/wechat/foreground-debug", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function diagnoseLocalWechatSearch(
  payload: LocalWechatSearchDebugPayload = { nickname: "Aw3", position: "right" },
): Promise<LocalWechatSearchDebugResult> {
  return requestLocalAgent<LocalWechatSearchDebugResult>("/agent/wechat/search-debug", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function startLocalWechatSearchCalibration(): Promise<LocalWechatSearchCalibrationResult> {
  return requestLocalAgent<LocalWechatSearchCalibrationResult>("/agent/wechat/search-calibration/start", {
    method: "POST",
  });
}

export async function diagnoseLocalWechatSearchResult(
  payload: LocalWechatSearchDebugPayload = { nickname: "Aw3", position: "right" },
): Promise<LocalWechatSearchResultDebugResult> {
  return requestLocalAgent<LocalWechatSearchResultDebugResult>("/agent/wechat/search-result-debug", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface LocalAgentVersion {
  app_name: string;
  build_version: string;
  build_time: string;
  git_commit: string;
  exe_mode: boolean;
  python_executable: string;
  cwd: string;
  agent_file: string;
  hostname: string;
  routes: string[];
}

export async function fetchLocalAgentVersion(): Promise<LocalAgentVersion> {
  return requestLocalAgent<LocalAgentVersion>("/agent/version", { method: "GET" });
}

/** 获取 Local Agent 配置的主系统地址（P0-FE-MAIN-1） */
export async function getAgentServerUrl(): Promise<import("./types").AgentServerUrlResponse> {
  return requestLocalAgent<import("./types").AgentServerUrlResponse>("/agent/tasks/server-url", { method: "GET" });
}

/** 触发 Local Agent 拉取并执行一条 pending 任务（P0-FE-MAIN-1 / P1-AUTO-1D-FIX2） */
export async function pollAndExecuteWechatTask(
  taskId?: number | null,
  signal?: AbortSignal,
): Promise<import("./types").PollAndExecuteResponse> {
  const body = taskId ? { task_id: taskId } : {};
  return requestLocalAgent<import("./types").PollAndExecuteResponse>("/agent/tasks/poll-and-execute", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}

/** P0-REPLY-2：触发 Local Agent 读取微信消息并检测销售回复 */
export async function detectReply(payload: {
  lead_id: number;
  staff_id: number;
  task_id?: number | null;
  target_nickname?: string;
}): Promise<import("./types").AgentReplyDetectResponse> {
  return requestLocalAgent<import("./types").AgentReplyDetectResponse>("/agent/replies/detect", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** P1-AUTO-1D / FIX3：触发 Local Agent 拉取并执行一次 detect_reply 任务（只读，不粘贴不发送）
 *  FIX3：支持传入 taskId 指定要检测的任务，避免被旧 pending 队列阻塞。
 */
export async function pollAndDetectReply(
  maxMessages: number = 20,
  signal?: AbortSignal,
  taskId?: number | null,
): Promise<import("./types").PollAndDetectResponse> {
  const body: Record<string, unknown> = { max_messages: maxMessages };
  if (taskId) body.task_id = taskId;
  return requestLocalAgent<import("./types").PollAndDetectResponse>("/agent/tasks/poll-and-detect", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}
