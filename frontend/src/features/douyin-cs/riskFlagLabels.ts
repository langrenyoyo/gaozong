// 自动回复风险标记与阻断原因的中文映射。
// 9100 返回的 risk_flags（如 contact_request）与 9000 gate 的 block_reason（如 risk_flags）
// 均为纯英文技术词，前端统一映射为中文，避免甲方面对裸英文字段。
// 来源：apps/xg_douyin_ai_cs/services/reply_decision_service.py（risk_flags 全集）
//       app/services/douyin_autoreply_gate_service.py（block_reason 全集）

// risk_flags 中文标签（9100 安全审查风险全集）
export const RISK_FLAG_LABELS: Record<string, string> = {
  // 9100 reply_decision_service risk_flags
  prompt_injection: "提示词注入风险",
  inventory_or_model_specific: "回复含具体车型库存",
  price_or_inventory_sensitive: "回复含价格库存敏感信息",
  inventory_claim: "回复含库存承诺",
  price_or_discount: "回复含价格优惠",
  finance_or_loan: "回复含金融贷款",
  vehicle_condition_specific: "回复含具体车况",
  legal_or_transfer: "回复含手续过户",
  contact_request: "回复含联系方式请求",
  after_sales_or_complaint: "回复含售后投诉",
  appointment_or_visit_specific: "回复含到店预约",
  no_rag_risky_question: "回复含高风险问题（未用知识库）",
  // 9100 其他诊断标记
  price_commitment: "价格承诺风险",
  no_rag_source: "知识库无命中",
  llm_json_parse_failed: "结构化解析失败",
  llm_requested_auto_send: "模型请求自动发送",
  proxy_forced_auto_send_false: "代理已强制关闭自动发送",
  // 意图类 risk_flag 补充（9100 LLM 可能直接输出）
  inquiry_inventory: "询问库存",
  consult_specific_model: "咨询具体车型",
  consult_inventory: "咨询库存",
};

// tags（9100 LLM 自由输出标签）常见值中文映射；未命中回退原值。
export const TAG_LABELS: Record<string, string> = {
  high_intent: "高意向",
  medium_intent: "中意向",
  low_intent: "低意向",
  contact_provided: "已留资",
  no_contact: "未留资",
  price_inquiry: "询价",
  inventory_inquiry: "问库存",
  test_drive_request: "试驾",
  complaint: "投诉",
  greeting: "打招呼",
  general_inquiry: "一般咨询",
};

// 单个 tag → 中文（未命中回退原值）
export function tagLabel(tag: string): string {
  return TAG_LABELS[tag] || tag;
}

// block_reason / skip_reason 中文标签（9000 gate 阻断/跳过原因全集）
export const BLOCK_REASON_LABELS: Record<string, string> = {
  // post_llm gate
  risk_flags: "回复内容触发风险审查，转人工确认",
  risk_flags_manual: "回复内容触发风险审查，转人工确认",
  manual_required: "回复内容需人工确认",
  empty_reply_text: "回复内容为空",
  fallback_reason: "回复降级，转人工确认",
  intent_not_allowed: "回复意图不在允许范围",
  rag_not_used: "未使用知识库，不允许自动发送",
  rag_required_but_unavailable: "要求可信知识库，但当前知识库不可用",
  rag_sources_empty: "未检索到可用知识来源",
  // binding / context
  conversation_context_unavailable: "缺少可回复上下文",
  account_send_disabled: "账号未开启发送",
  auto_send_disabled_by_decision: "决策未授权自动发送",
  // real_send gate
  real_send_gate_blocked: "真实发送门禁未通过",
  manual_takeover_blocked: "人工接管中，已阻断",
  // latest_message gate（发送前校验最新消息状态）
  latest_message_changed: "客户已发新消息，旧回复不再发送",
  latest_message_not_customer: "最新消息不是客户消息",
  outbound_after_trigger: "触发后已有人工客服回复",
  send_context_unavailable: "发送上下文不可用",
  // format
  format_invalid: "回复内容格式无效",
};

// 单个 risk_flag → 中文（未命中回退原值）
export function riskFlagLabel(flag: string): string {
  return RISK_FLAG_LABELS[flag] || flag;
}

// block_reason / skip_reason → 中文（未命中回退原值）
export function blockReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "-";
  return BLOCK_REASON_LABELS[reason] || reason;
}

// 列表项中需要展示真实阻断原因的 run 字段子集（后端 AiAutoReplyRunListItem 已返回）
export interface RunBlockReasonContext {
  block_reason?: string | null;
  skip_reason?: string | null;
  manual_required?: boolean | null;
  manual_required_reason?: string | null;
  risk_flags?: string[] | null;
  rag_used?: boolean | null;
}

// 把 risk_flags 翻译为去重后的中文短语列表
function riskFlagsToChinese(flags: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const flag of flags) {
    const text = flag ? riskFlagLabel(flag) : "";
    if (text && !seen.has(text)) {
      seen.add(text);
      result.push(text);
    }
  }
  return result;
}

// 当 block_reason 为 auto_send_disabled_by_decision 时，补充 9100 的真实判定原因，
// 让甲方在列表直接看到"为什么没授权发送"，而不只是统一的"决策未授权自动发送"。
// 返回主标签 + 括号补充；无补充信息时退回主标签。
export function blockReasonDetailText(ctx: RunBlockReasonContext): string {
  const reason = ctx.block_reason || ctx.skip_reason;
  const base = blockReasonLabel(reason);
  if (reason !== "auto_send_disabled_by_decision") {
    return base;
  }
  const extras: string[] = [];
  // 优先用 9100 给出的人工确认原因（如"具体车型库存需人工确认"）
  const mr = (ctx.manual_required_reason || "").trim();
  if (mr) {
    extras.push(mr);
  }
  // 补充风险标记中文（库存/价格/车况/联系方式等）
  const flags = Array.isArray(ctx.risk_flags) ? ctx.risk_flags : [];
  const flagTexts = riskFlagsToChinese(flags).filter(
    (t) => !mr || !t.includes(mr.slice(0, 4)), // 去掉与 manual_required_reason 重复项
  );
  if (flagTexts.length) {
    extras.push(flagTexts.join("、"));
  }
  // rag_used=true 但被阻断 → 知识不可信（Milvus 降级）的提示
  if (ctx.rag_used === true && (mr || flags.length)) {
    extras.push("知识库检索降级");
  }
  if (!extras.length) {
    return base;
  }
  return `${base}（${extras.join("；")}）`;
}