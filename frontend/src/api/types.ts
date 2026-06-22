// ========== Leads ==========

export interface Lead {
  id: number;
  source: string;
  lead_type: string;
  customer_name: string | null;
  customer_contact: string | null;
  phone?: string | null;
  wechat?: string | null;
  city?: string | null;
  car_model?: string | null;
  budget?: string | null;
  all_extracted_contacts?: string[];
  contact_extract_status?: string | null;
  original_message_text?: string | null;
  content: string | null;
  source_url: string | null;
  source_id: string | null;
  // 商户隔离 / 会话定位字段：后端 LeadOut 已返回，前端用于对话跟进跳转与会话归并
  merchant_id?: string | null;
  account_open_id?: string | null;
  conversation_short_id?: string | null;
  assigned_staff_id: number | null;
  assigned_at: string | null;
  status: string;
  display_status?: string | null;
  status_label?: string | null;
  status_reason?: string | null;
  lead_score?: {
    score?: number;
    level?: string;
    reasons?: string[];
  } | null;
  assigned_staff?: {
    id: number;
    name: string;
    wechat_id?: string | null;
    wechat_nickname?: string | null;
    phone?: string | null;
    status?: string | null;
  } | null;
  timeline?: Array<{
    id: number;
    record_type: string;
    action_label?: string | null;
    content: string | null;
    remark?: string | null;
    staff_id: number | null;
    staff_name?: string | null;
    created_at: string | null;
  }>;
  raw_data: string | null;
  created_at: string;
  updated_at: string;
}

export interface LeadListResponse {
  success: boolean;
  data: {
    page: number;
    page_size: number;
    total: number;
    items: Lead[];
  };
  message: string;
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
  retained_contact_count?: number;
  high_intent_count?: number;
  lead_growth_rate?: number | null;
  sales_response_rate?: number | null;
  retained_contact_rate?: number | null;
  // 转化口径语义别名：与 retained_contact_count / retained_contact_rate 等价，后端 ReportSummary 已返回
  converted_leads?: number;
  conversion_rate?: number | null;
  high_intent_hint?: string | null;
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

// ========== Compute（小高算力，P1-COMPUTE-FE-1）==========

/** 算力余额与消耗统计（GET /compute/summary data）。 */
export interface ComputeSummary {
  merchant_id: string;
  /** 当前算力余额（Token） */
  balance_tokens: number;
  /** 今日消耗（Token） */
  today_consume: number;
  /** 昨日消耗（Token） */
  yesterday_consume: number;
  /** 累计消耗（Token） */
  total_consume: number;
}

/** 算力 Token 流水（GET /compute/transactions items）。 */
export interface ComputeTransaction {
  id: number;
  merchant_id: string;
  /** 流水类型: recharge(充值) / grant_package(发放套餐) / consume(消耗) */
  transaction_type: string;
  /** Token 变动（正为增加，负为消耗） */
  delta_tokens: number;
  /** 变动后余额 */
  balance_after_tokens: number;
  /** 来源: manual_recharge / package_grant / llm / embedding / other */
  source: string;
  remark?: string | null;
  model?: string | null;
  agent_id?: string | null;
  conversation_id?: number | null;
  created_at?: string | null;
}

/** Token 明细分页数据。 */
export interface ComputeTransactionListData {
  page: number;
  page_size: number;
  total: number;
  items: ComputeTransaction[];
}

/** 算力套餐（GET /compute/packages items）。 */
export interface ComputePackage {
  id: number;
  name: string;
  /** 价格（整数元） */
  price_yuan: number;
  /** Token 数量 */
  token_amount: number;
  enabled: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

/** 商户发起充值订单请求（POST /compute/recharge-orders）。 */
export interface ComputeRechargeOrderRequest {
  /** 套餐充值时传入套餐 ID（与 custom_tokens 二选一） */
  package_id?: number;
  /** 自定义金额充值 Token 数量（与 package_id 二选一） */
  custom_tokens?: number;
  /** 支付方式: wechat / alipay */
  pay_method: string;
}

/** 充值订单输出（一期 mock，不接真实支付）。 */
export interface ComputeRechargeOrder {
  /** mock 订单号 */
  order_no: string;
  pay_method: string;
  tokens: number;
  /** 价格（元），套餐充值时有值 */
  price_yuan?: number | null;
  /** mock 付款码占位 */
  pay_qr_code?: string | null;
  /** 订单状态: mock_pending（一期不接真实支付） */
  status: string;
}

/** 算力余额/统计响应（GET /compute/summary）。 */
export interface ComputeSummaryResponse {
  success: boolean;
  data: ComputeSummary;
  message: string;
}

/** Token 明细列表响应（GET /compute/transactions）。 */
export interface ComputeTransactionListResponse {
  success: boolean;
  data: ComputeTransactionListData;
  message: string;
}

/** 套餐列表响应（GET /compute/packages）。 */
export interface ComputePackageListResponse {
  success: boolean;
  data: ComputePackage[];
  message: string;
}

/** 充值订单响应（POST /compute/recharge-orders）。 */
export interface ComputeRechargeOrderResponse {
  success: boolean;
  data: ComputeRechargeOrder;
  message: string;
}

/** Token 明细查询参数。 */
export interface ComputeTransactionQuery {
  transaction_type?: string;
  page?: number;
  page_size?: number;
}

// ========== Douyin auto reply settings ==========

export interface DouyinAutoReplySettingItem {
  account_open_id: string;
  account_name?: string | null;
  nickname?: string | null;
  bind_status?: number | string | null;
  bound_agent_id?: string | null;
  bound_agent_name?: string | null;
  bound_agent_status?: string | null;
  enabled: boolean;
  dry_run_enabled: boolean;
  send_enabled: boolean;
  min_confidence: number;
  require_rag: boolean;
  require_rag_sources: boolean;
  allowed_intents: string[];
  blocked_risk_flags: string[];
  customer_whitelist_open_ids: string[];
  conversation_whitelist_ids: string[];
  min_interval_seconds: number;
  max_auto_replies_per_conversation_per_day: number;
  max_replies_per_conversation_per_hour: number;
  max_replies_per_account_per_hour: number;
  updated_at?: string | null;
}

export interface DouyinAutoReplySettingUpdateRequest {
  enabled: boolean;
  dry_run_enabled: boolean;
  send_enabled: boolean;
  min_confidence: number;
  require_rag: boolean;
  require_rag_sources: boolean;
  allowed_intents: string[];
  blocked_risk_flags: string[];
  customer_whitelist_open_ids: string[];
  conversation_whitelist_ids: string[];
  min_interval_seconds: number;
  max_auto_replies_per_conversation_per_day: number;
  max_replies_per_conversation_per_hour: number;
  max_replies_per_account_per_hour: number;
}

export interface DouyinAutoReplySettingsListResponse {
  success?: boolean;
  data: {
    items: DouyinAutoReplySettingItem[];
    total?: number;
  };
  message?: string;
}

export interface DouyinAutoReplySettingResponse {
  success?: boolean;
  data: DouyinAutoReplySettingItem;
  message?: string;
}

export interface AllowedIntentOption {
  value: string;
  label: string;
  description?: string;
}

export interface BlockedRiskFlagOption {
  value: string;
  label: string;
  description?: string;
}

// ========== Douyin auto reply runs ==========

export type AiAutoReplyRunStatus =
  | "skipped"
  | "blocked"
  | "decided"
  | "failed"
  | "sent"
  | "send_failed"
  | "send_skipped";

export interface AiAutoReplyRunSendRecord {
  id: number;
  send_status?: string | null;
  send_source?: string | null;
  auto_send?: boolean | number | null;
  manual_confirmed?: boolean | number | null;
  upstream_msg_id?: string | null;
  error_message?: string | null;
  sent_at?: string | null;
}

export interface AiAutoReplyRunListItem {
  id: number;
  account_open_id?: string | null;
  conversation_short_id?: string | null;
  customer_open_id?: string | null;
  trigger_event_id?: number | null;
  trigger_event_key?: string | null;
  trigger_server_message_id?: string | null;
  latest_message_summary?: string | null;
  agent_id?: string | number | null;
  mode?: string | null;
  status: AiAutoReplyRunStatus | string;
  skip_reason?: string | null;
  block_reason?: string | null;
  decision_log_id?: number | null;
  would_send_content_summary?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AiAutoReplyRunDetail extends AiAutoReplyRunListItem {
  latest_message?: string | null;
  would_send_content?: string | null;
  gate_results?: Record<string, unknown> | unknown[] | null;
  send_record?: AiAutoReplyRunSendRecord | null;
}

export interface AiAutoReplyRunListData {
  page: number;
  page_size: number;
  total: number;
  items: AiAutoReplyRunListItem[];
}

export interface AiAutoReplyRunQueryParams {
  page?: number;
  page_size?: number;
  account_open_id?: string;
  conversation_short_id?: string;
  customer_open_id?: string;
  agent_id?: string | number;
  status?: string;
  created_from?: string;
  created_to?: string;
  keyword?: string;
}

export interface AiAutoReplyRunListResponse {
  success?: boolean;
  data: AiAutoReplyRunListData;
  message?: string;
}

export interface AiAutoReplyRunDetailResponse {
  success?: boolean;
  data: AiAutoReplyRunDetail;
  message?: string;
}
