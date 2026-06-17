// ========== Leads ==========

export interface Lead {
  id: number;
  source: string;
  lead_type: string;
  customer_name: string | null;
  customer_contact: string | null;
  phone?: string | null;
  wechat?: string | null;
  all_extracted_contacts?: string[];
  contact_extract_status?: string | null;
  original_message_text?: string | null;
  content: string | null;
  source_url: string | null;
  source_id: string | null;
  assigned_staff_id: number | null;
  assigned_at: string | null;
  status: string;
  raw_data: string | null;
  created_at: string;
  updated_at: string;
}

// ========== Raw webhook events ==========

export type WebhookLeadAction =
  | "duplicate_event"
  | "valid_lead"
  | "non_lead_event"
  | "invalid_content"
  | "non_text_message"
  | "invalid_contact"
  | "unknown";

export interface WebhookEvent {
  id: number;
  event: string | null;
  nick_name?: string | null;
  nickname?: string | null;
  douyin_nick_name?: string | null;
  display_name?: string | null;
  customer_name?: string | null;
  avatar?: string | null;
  avatar_url?: string | null;
  from_user_nick_name?: string | null;
  from_user_avatar?: string | null;
  to_user_nick_name?: string | null;
  to_user_avatar?: string | null;
  from_user_id: string | null;
  to_user_id: string | null;
  body_open_id: string | null;
  body_account_open_id: string | null;
  content_open_id: string | null;
  content_account_open_id: string | null;
  event_key: string | null;
  is_duplicate: boolean;
  lead_id: number | null;
  lead_action: WebhookLeadAction | string;
  created_at: string | null;
  server_message_id: string | null;
  conversation_short_id: string | null;
  message_text: string | null;
  contact_extract_status: string | null;
  customer_contact: string | null;
  failure_reason: string | null;
  raw_body?: Record<string, unknown> | null;
  content?: Record<string, unknown> | string | null;
}

export interface WebhookEventDetail extends WebhookEvent {
  raw_body: Record<string, unknown> | null;
}

export interface WebhookEventListResponse {
  success: boolean;
  data: {
    page: number;
    page_size: number;
    total: number;
    items: WebhookEvent[];
  };
  message: string;
}

export interface WebhookEventDetailResponse {
  success: boolean;
  data: WebhookEventDetail;
  message: string;
}

export interface WebhookEventQuery {
  page?: number;
  page_size?: number;
  event?: string;
  lead_action?: string;
  is_duplicate?: boolean;
  start_time?: string;
  end_time?: string;
  keyword?: string;
  open_id?: string;
  conversation_short_id?: string;
  lead_id?: number;
}

// ========== Agent status ==========

export interface AgentStatusData {
  agent_online: boolean;
  agent_status: string;
  wechat_available: string;
  wechat_status: string;
  automation_enabled: boolean;
  emergency_stopped: boolean;
  action_in_progress: boolean;
  current_task_id: number | null;
  current_task_type: string | null;
  last_heartbeat_at: string | null;
  last_checked_at: string | null;
  can_run_wechat_action: boolean;
  disabled_reason: string;
  status_source: string;
}

export interface AgentStatusResponse {
  success: boolean;
  data: AgentStatusData;
  message: string;
}

// ========== Douyin live-check ==========

export interface DouyinLiveCheckOAuthCallback {
  received_at: string;
  has_code: boolean;
  code_preview: string | null;
  state: string | null;
  open_id: string | null;
  nick_name?: string | null;
  avatar?: string | null;
  error: string | null;
  error_description: string | null;
  query_keys: string[];
}

export interface DouyinLiveCheckWebhookObserve {
  received_at: string;
  has_authorization: boolean;
  has_x_auth_timestamp: boolean;
  content_type: string | null;
  user_agent: string | null;
  body_has_event: boolean;
  body_has_content: boolean;
  body_has_open_id: boolean;
  body_has_account_open_id: boolean;
  body_has_conversation_short_id: boolean;
  body_has_server_message_id: boolean;
  from_user_id: string | null;
  to_user_id: string | null;
  body_open_id: string | null;
  body_account_open_id: string | null;
  content_open_id: string | null;
  content_account_open_id: string | null;
  content_parse_success: boolean;
  content_parse_error: string | null;
  content_has_conversation_short_id: boolean;
  content_has_server_message_id: boolean;
  content_has_message_type: boolean;
  content_message_type: string | null;
  event: string | null;
  body_keys: string[];
  content_keys: string[];
}

export interface DouyinLiveCheckStatusData {
  enabled: boolean;
  auth_url_configured: boolean;
  missing_config: string[];
  auth_redirect_url: string | null;
  webhook_observe_url: string | null;
  last_oauth_callback: DouyinLiveCheckOAuthCallback | null;
  last_webhook_observe: DouyinLiveCheckWebhookObserve | null;
}

export interface DouyinLiveCheckAuthUrlData {
  configured: boolean;
  missing: string[];
  auth_url: string | null;
  auth_redirect_url: string | null;
  callback_url: string | null;
}

export interface DouyinLiveCheckAccount {
  id?: number;
  account_id?: number | string;
  douyin_account_id?: number;
  account_open_id?: string | null;
  open_id?: string | null;
  account_name?: string | null;
  nickname?: string | null;
  avatar?: string | null;
  avatar_url?: string | null;
  status?: string | null;
  is_active?: boolean;
  last_active_at?: string | null;
  authorized_at?: string | null;
  unread_count?: number;
  source?: string | null;
  is_authorized?: boolean;
  has_events?: boolean;
}

export interface DouyinLiveCheckAccountsData {
  items: DouyinLiveCheckAccount[];
  total: number;
  source?: string;
}

export interface DouyinLiveCheckStatusResponse {
  success: boolean;
  data: DouyinLiveCheckStatusData;
  message: string;
}

export interface DouyinLiveCheckAuthUrlResponse {
  success: boolean;
  data: DouyinLiveCheckAuthUrlData;
  message: string;
}

export interface DouyinLiveCheckAccountsResponse {
  success: boolean;
  data: DouyinLiveCheckAccountsData;
  message: string;
}

// ========== Staff ==========

export interface Staff {
  id: number;
  name: string;
  wechat_id: string | null;
  wechat_nickname: string | null;
  phone: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

// ========== Reports ==========

export interface ReportSummary {
  total_leads: number;
  assigned_leads: number;
  replied_leads: number;
  timeout_leads: number;
  pending_leads: number;
  assigned_count?: number;
  replied_count?: number;
  timeout_count?: number;
}

// ========== Reply checks ==========

export interface CheckRecord {
  id: number;
  lead_id: number;
  staff_id: number;
  reply_deadline: string | null;
  actual_reply_at: string | null;
  reply_content: string | null;
  is_effective: number;
  effectiveness_reason: string | null;
  check_status: string;
  checked_at: string | null;
  created_at: string;
}

// ========== WeChat auto detection ==========

/** WeChat reply detection response. */
export interface WechatDetectResponse {
  success: boolean;
  message?: string;
  detection_mode?: string;
  check_id?: number;
  lead_id?: number;
  staff_id?: number;
  is_effective?: number;
  effectiveness_reason?: string;
  reply_content?: string;
  reply_time?: string;
  check_status?: string;
  confirmed_required?: boolean;
  warning?: string;
  risk_level?: string;
  error?: string;
  matched_content?: string;
}

export interface WechatAutoDetectStatus {
  success?: boolean;
  message?: string;
  active_check_id: number | null;
  lead_id: number | null;
  customer_name: string | null;
  staff_id: number | null;
  staff_name: string | null;
  check_status: string | null;
  interval_seconds: number;
  last_detect_at: string | null;
  last_result: string | null;
  warning: string | null;
}

// ========== Automation control ==========

export interface AutomationStatus {
  emergency_stopped: boolean;
  stop_reason: string | null;
  stopped_at: string | null;
}

// ========== douyinAPI sync ==========

export interface DouyinSyncItem {
  source_id: string;
  customer_name: string;
  content: string;
  action: "create" | "update" | "skip";
  reason: string;
}

export interface DouyinSyncResponse {
  success: boolean;
  fetched: number;
  mapped: number;
  created: number;
  updated: number;
  skipped: number;
  assigned: number;
  notified: number;
  dry_run: boolean;
  items: DouyinSyncItem[];
  wechat_tasks?: WechatTaskSyncStats | null;
}

// ========== P0-5A: WeChat task queue ==========

/** WechatTask creation stats during sync. */
export interface WechatTaskSyncStats {
  auto_create_enabled: boolean;
  created_count: number;
  skipped_count: number;
  details?: Array<{ lead_id: number; task_id: number }>;
  skipped: Array<{ lead_id: number; reason: string }>;
}

/** WeChat task response. */
export interface WechatTask {
  id: number;
  task_type: string;
  lead_id: number | null;
  staff_id: number | null;
  reply_check_id: number | null;
  target_nickname: string | null;
  message: string | null;
  mode: string;
  status: string;
  failure_stage: string | null;
  raw_result: string | null;
  agent_hostname: string | null;
  agent_pid: number | null;
  pasted_at: string | null;
  sent_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** WeChat task create request. */
export interface WechatTaskCreateRequest {
  lead_id?: number;
  staff_id?: number;
  reply_check_id?: number;
  task_type?: string;
  target_nickname: string;
  message?: string;
  mode?: string;
}

/** Local Agent server-url response. */
export interface AgentServerUrlResponse {
  server_url: string | null;
  configured: boolean;
}

/** Local Agent poll-and-execute response. */
export interface PollAndExecuteResponse {
  success: boolean;
  agent_machine?: {
    hostname?: string;
    platform?: string;
    pid?: number;
  };
  server_url?: string | null;
  task?: {
    id?: number;
    target_nickname?: string;
    mode?: string;
    message?: string;
  } | null;
  action?: {
    pasted?: boolean;
    sent?: boolean;
  };
  write_back?: {
    ok?: boolean;
    status_code?: number;
  };
  failure_stage?: string | null;
  message?: string;
  raw_result?: Record<string, unknown>;
}

// ========== Lead notifications ==========

export interface SendToStaffResponse {
  success: boolean;
  message: string;
  lead_id: number;
  staff_id: number;
  notification_id?: number;
  send_status?: string;
  chat_title?: string;
  failure_stage?: string;
}

/** Notification record response. */
export interface NotificationRecord {
  id: number;
  lead_id: number;
  staff_id: number;
  check_id: number | null;
  notification_text: string | null;
  send_status: string;
  send_mode: string | null;
  chat_title: string | null;
  error_message: string | null;
  sent_at: string | null;
  created_at: string | null;
  customer_name: string | null;
  staff_name: string | null;
}

export interface NotificationRecordsResponse {
  records: NotificationRecord[];
  total: number;
}

// ========== P0-REPLY-2: Local Agent reply detection ==========

/** Local Agent reply detection response. */
export interface AgentReplyDetectResponse {
  success: boolean;
  detected_status: "replied" | "pending" | "manual_review" | "failed" | "blocked";
  matched_reply: string | null;
  messages_read: number;
  messages: Array<{ sender: string; content: string | null }>;
  failure_stage: string | null;
  write_back: { ok?: boolean; status_code?: number; error?: string | null } | null;
  message: string;
  raw_result: Record<string, unknown> | null;
  agent_machine?: { hostname?: string; platform?: string; pid?: number };
}

// ========== P1-AUTO-1D: Automatic reply detection ==========

/** Local Agent poll-and-detect response. */
export interface PollAndDetectResponse {
  success: boolean;
  message: string;
  task: {
    id: number;
    task_type: string;
    target_nickname: string | null;
    mode: string;
    lead_id: number | null;
    staff_id: number | null;
    reply_check_id: number | null;
  } | null;
  detect_result?: {
    detected_status: string | null;
    matched_reply: string | null;
    messages_read: number;
    failure_stage: string | null;
    verify: { verified?: boolean; strategy?: string | null; confidence?: number | null } | null;
    write_back: { ok?: boolean; status_code?: number } | null;
    raw_result: Record<string, unknown> | null;
  } | null;
  action?: {
    pasted?: boolean;
    sent?: boolean;
  };
  failure_stage?: string | null;
}
