import {
  AlertTriangleIcon,
  CheckCircleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  InboxIcon,
  LoaderIcon,
  MoreHorizontalIcon,
  MessageCircleIcon,
  RefreshCwIcon,
  SearchIcon,
  UserCheckIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { assignLead, fetchLead, fetchLeadsPage } from "../api";
import { fetchStaffList } from "../api";
import { fetchSummary } from "../api";
import { syncDouyinLeads } from "../api";
import { detectWechatReply } from "../api";
import { fetchChecks } from "../api";
import { setWechatAutoDetectTarget, fetchWechatAutoDetectStatus, clearWechatAutoDetectTarget } from "../api";
import { sendLeadToStaff } from "../api";
import { fetchNotificationRecords } from "../../../api/notifications";
import { fetchAgentStatus } from "../api";
import { fetchWebhookEvents } from "../api";
import type { AgentStatusData, DouyinSyncResponse, Lead, ReportSummary, Staff, WechatDetectResponse, CheckRecord, WechatAutoDetectStatus, WebhookEvent } from "../types";
import type { NotificationRecord } from "../../../api/types";
import { apiDateTimeMs, formatDateTimeLocal } from "../../../lib/datetime";

// ========== 状态配置（对齐 auto_wechat） ==========

const STATUS_OPTIONS = ["pending", "assigned", "replied", "timeout", "closed"] as const;
type LeadStatus = (typeof STATUS_OPTIONS)[number];
const SOURCE_OPTIONS = ["douyin", "douyin_live"] as const;

const STATUS_LABELS: Record<string, string> = {
  pending: "新线索",
  assigned: "跟进中",
  replied: "已回复",
  timeout: "已失效",
  closed: "已成交",
};

const STATUS_TONES: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  assigned: "bg-blue-100 text-blue-700",
  replied: "bg-emerald-100 text-emerald-700",
  timeout: "bg-red-100 text-red-700",
  closed: "bg-slate-100 text-slate-700",
};

function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status;
}

function leadStatusLabel(lead: Lead): string {
  return lead.status_label || statusLabel(lead.status);
}

function statusClass(status: string): string {
  return STATUS_TONES[status] || "bg-slate-100 text-slate-700";
}

const CONTACT_STATUS_LABELS: Record<string, string> = {
  matched: "已提取",
  not_matched: "未提取",
  no_contact: "未提取",
  empty_text: "空文本",
  parse_failed: "提取失败",
  failed: "提取失败",
  unknown: "未知",
};

function contactStatusLabel(status?: string | null): string {
  return status ? CONTACT_STATUS_LABELS[status] || status : "未知";
}

function getLeadContactValues(lead: Lead): string[] {
  const values = [lead.phone, lead.wechat, ...(lead.all_extracted_contacts || []), lead.customer_contact];
  return values.filter((value, index): value is string => Boolean(value) && values.indexOf(value) === index);
}

type OperationalTagKey = "manual_required" | "follow_up" | "retained_contact" | "high_intent";

interface OperationalTag {
  key: OperationalTagKey;
  label: string;
  tone: string;
  reasons: string[];
  cautious?: boolean;
}

const HIGH_INTENT_KEYWORDS = ["现车", "价格", "检测报告", "车况", "底价", "预算", "看车", "到店", "多少钱", "报价"];

const OPERATIONAL_TAG_META: Record<OperationalTagKey, { label: string; tone: string }> = {
  manual_required: { label: "需人工", tone: "bg-rose-50 text-rose-700 ring-rose-200" },
  follow_up: { label: "待回访", tone: "bg-sky-50 text-sky-700 ring-sky-200" },
  retained_contact: { label: "已留资", tone: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  high_intent: { label: "高意向", tone: "bg-amber-50 text-amber-700 ring-amber-200" },
};

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  values.forEach((item) => {
    const value = String(item || "").trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    result.push(value);
  });
  return result;
}

function hasRetainedContact(lead: Lead): boolean {
  return getLeadContactValues(lead).length > 0;
}

function isHighIntentLead(lead: Lead): boolean {
  const level = String(lead.lead_score?.level || "").trim();
  if (level === "高意向") return true;
  if ((lead.lead_score?.reasons || []).some((reason) => reason.includes("高意向"))) return true;
  const text = uniqueStrings([
    lead.content,
    lead.original_message_text,
    leadDerivedValue(lead, "car_model"),
    leadDerivedValue(lead, "budget"),
    leadDerivedValue(lead, "city"),
  ]).join(" ");
  return HIGH_INTENT_KEYWORDS.some((keyword) => text.includes(keyword));
}

function hasProblematicContactExtract(lead: Lead): boolean {
  return ["parse_failed", "failed"].includes(String(lead.contact_extract_status || ""));
}

function notificationNeedsManual(record: NotificationRecord): boolean {
  const status = String(record.send_status || "").toLowerCase();
  return ["failed", "blocked", "skipped"].includes(status) || Boolean(record.error_message);
}

function notificationSentToStaff(record: NotificationRecord): boolean {
  const status = String(record.send_status || "").toLowerCase();
  return ["pasted", "sent", "replied"].includes(status) || Boolean(record.sent_at);
}

function deriveOperationalTags(
  lead: Lead,
  checks: CheckRecord[] = [],
  notificationRecords: NotificationRecord[] = [],
): OperationalTag[] {
  const relatedChecks = checks.filter((item) => item.lead_id === lead.id);
  const relatedNotifications = notificationRecords.filter((item) => item.lead_id === lead.id);
  const reasons: Record<OperationalTagKey, string[]> = {
    manual_required: [],
    follow_up: [],
    retained_contact: [],
    high_intent: [],
  };

  if (hasProblematicContactExtract(lead) && !hasRetainedContact(lead)) {
    reasons.manual_required.push("联系方式提取失败，需要人工复核");
  }
  if (relatedChecks.some((item) => ["manual_review", "failed", "blocked", "invalid"].includes(item.check_status))) {
    reasons.manual_required.push("回复检测需要人工复核");
  }
  if (relatedNotifications.some(notificationNeedsManual)) {
    reasons.manual_required.push("微信通知销售失败或被阻断");
  }

  if (lead.status === "timeout" || relatedChecks.some((item) => item.check_status === "timeout")) {
    reasons.follow_up.push("销售跟进检测已超时，建议抖音私信二次提醒");
  }
  // 联系方式错误 → 待回访（销售反馈号码无效，需抖音私信向客户核实）
  // 注：「已分配+已通知+暂无反馈」属于销售跟进状态 no_feedback（未反馈），不再归为待回访
  if (lead.sales_followup_status === "contact_invalid") {
    reasons.follow_up.push("销售反馈联系方式错误，建议抖音私信向客户核实");
  }

  if (hasRetainedContact(lead)) {
    reasons.retained_contact.push("已提取手机号、微信号或其他联系方式");
  }
  if (isHighIntentLead(lead)) {
    reasons.high_intent.push("命中车型、预算、价格或看车等意向信号");
  }

  return (["manual_required", "follow_up", "retained_contact", "high_intent"] as OperationalTagKey[])
    .filter((key) => reasons[key].length > 0)
    .map((key) => ({
      key,
      label: OPERATIONAL_TAG_META[key].label,
      tone: OPERATIONAL_TAG_META[key].tone,
      reasons: reasons[key],
      cautious: key === "follow_up" && !relatedNotifications.length,
    }));
}

function buildDouyinConversationUrl(lead: Lead): string | null {
  if (!lead.account_open_id || !lead.conversation_short_id || !lead.source_id) return null;
  const params = new URLSearchParams({
    account_open_id: lead.account_open_id,
    conversation_short_id: lead.conversation_short_id,
    open_id: lead.source_id,
  });
  return `/douyin-ai-cs?${params.toString()}`;
}

function parseLeadRawData(lead: Lead): Record<string, unknown> {
  if (!lead.raw_data) return {};
  try {
    const parsed = JSON.parse(lead.raw_data);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function rawString(data: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = data[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function leadDerivedValue(lead: Lead, field: "city" | "car_model" | "budget"): string | null {
  const directValue = lead[field];
  if (typeof directValue === "string" && directValue.trim()) return directValue.trim();
  const raw = parseLeadRawData(lead);
  if (field === "city") return rawString(raw, ["city", "location", "customer_city"]);
  if (field === "car_model") return rawString(raw, ["car_model", "vehicle_model", "intent_car_model"]);
  return rawString(raw, ["budget", "intent_budget"]);
}

function leadTraceItems(lead: Lead): Array<{ label: string; value: string; title?: string }> {
  const items: Array<{ label: string; value: string; title?: string }> = [];
  const raw = parseLeadRawData(lead);
  if (lead.source_id) items.push({ label: "来源ID", value: shortId(lead.source_id), title: lead.source_id });
  if (lead.source_url) items.push({ label: "来源链接", value: shortId(lead.source_url, 12, 10), title: lead.source_url });
  if (lead.source) items.push({ label: "来源", value: lead.source });
  for (const [label, key] of [
    ["会话短ID", "conversation_short_id"],
    ["消息ID", "server_message_id"],
    ["事件键", "event_key"],
  ] as const) {
    const value = rawString(raw, [key]);
    if (value) items.push({ label, value: shortId(value, 12, 8), title: value });
  }
  return items;
}

function formatPercent(value?: number | null): string | null {
  return typeof value === "number" ? `${value.toFixed(1)}%` : null;
}

function leadGrowthHint(summary: ReportSummary): string {
  const percent = formatPercent(summary.lead_growth_rate);
  return percent ? `较昨日增长 ${percent}` : "暂无昨日基线";
}

function leadScorePercent(lead: Lead): number | null {
  const score = lead.lead_score?.score;
  if (typeof score !== "number") return null;
  return Math.max(0, Math.min(100, score));
}

function leadScoreLevelLabel(level?: string | null): string {
  if (level === "待跟进") return "低意向";
  return level || "低意向";
}

const DOUYIN_EVENT_DIRECTION: Record<string, { label: string; tone: string; align: string }> = {
  im_receive_msg: {
    label: "客户消息",
    tone: "border-emerald-200 bg-emerald-50 text-emerald-700",
    align: "mr-8",
  },
  im_send_msg: {
    label: "我方消息",
    tone: "border-blue-200 bg-blue-50 text-blue-700",
    align: "ml-8",
  },
  im_enter_direct_msg: {
    label: "进入私信/系统事件",
    tone: "border-slate-200 bg-slate-50 text-slate-600",
    align: "",
  },
};

function douyinDirection(event?: string | null) {
  return DOUYIN_EVENT_DIRECTION[event || ""] || {
    label: "其他事件",
    tone: "border-zinc-200 bg-zinc-50 text-zinc-600",
    align: "",
  };
}

function sortEventsAsc(items: WebhookEvent[]): WebhookEvent[] {
  return [...items].sort((a, b) => {
    const left = apiDateTimeMs(a.created_at);
    const right = apiDateTimeMs(b.created_at);
    if (left !== right) return left - right;
    return a.id - b.id;
  });
}

// ========== 工具函数 ==========

const AGENT_STATUS_FALLBACK: AgentStatusData = {
  agent_online: false,
  agent_status: "offline",
  wechat_available: "unknown",
  wechat_status: "unknown",
  automation_enabled: false,
  emergency_stopped: false,
  action_in_progress: false,
  current_task_id: null,
  current_task_type: null,
  last_heartbeat_at: null,
  last_checked_at: null,
  can_run_wechat_action: false,
  disabled_reason: "无法获取本地微信助手状态，请稍后重试",
  status_source: "frontend_fallback",
};

const AGENT_STATUS_LABELS: Record<string, string> = {
  online: "在线",
  offline: "离线",
  unknown: "状态未确认",
};

const WECHAT_STATUS_LABELS: Record<string, string> = {
  available: "可用",
  unavailable: "不可用",
  unknown: "未知",
};

function agentStatusLabel(status?: string | null): string {
  return status ? AGENT_STATUS_LABELS[status] || status : "状态未确认";
}

function wechatStatusLabel(status?: string | null): string {
  return status ? WECHAT_STATUS_LABELS[status] || status : "未知";
}

function agentDisabledReason(agentStatus: AgentStatusData): string {
  return agentStatus.disabled_reason || "本地微信助手状态未确认，暂不可执行微信自动化";
}

function formatTime(value: string | null): string {
  return formatDateTimeLocal(value);
}

function shortId(value?: string | null, head = 10, tail = 8): string {
  if (!value) return "-";
  return value.length > head + tail + 3 ? `${value.slice(0, head)}...${value.slice(-tail)}` : value;
}

function detailValue(label: string, value: string): { text: string; title?: string } {
  if (label === "来源ID" || label === "来源链接") {
    return { text: shortId(value), title: value === "-" ? undefined : value };
  }
  return { text: value };
}

const TIMELINE_TYPE_LABELS: Record<string, string> = {
  assign: "首次分配",
  reassign: "重新分配",
  reply_check: "回复检测",
  notification: "微信通知",
  feedback: "反馈记录",
  manual_note: "人工备注",
};

function timelineTypeLabel(type: string): string {
  return TIMELINE_TYPE_LABELS[type] || type;
}

function leadPrimaryContact(lead: Lead): string {
  if (lead.phone) return `手机号：${lead.phone}`;
  if (lead.wechat) return `微信：${lead.wechat}`;
  const fallback = getLeadContactValues(lead)[0];
  return fallback ? `联系方式：${fallback}` : "未留联系方式";
}

// ========== 同步弹窗 ==========

type SyncPhase = "preview" | "syncing" | "result" | "error";

interface SyncModalProps {
  phase: SyncPhase;
  preview: DouyinSyncResponse | null;
  result: DouyinSyncResponse | null;
  syncError: string | null;
  onConfirm: () => void;
  onClose: () => void;
}

function SyncModal({ phase, preview, result, syncError, onConfirm, onClose }: SyncModalProps) {
  const data = phase === "preview" ? preview : result;
  const items = (data?.items || []).slice(0, 5);

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[560px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        {/* 标题栏 */}
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">
              同步 douyinAPI 测试环境线索
            </h2>
            <p className="mt-1 text-xs text-[#8b95a6]">
              {phase === "preview" && "预览模式：以下为同步预览结果，确认后将实际写入"}
              {phase === "syncing" && "正在同步中，请勿关闭窗口..."}
              {phase === "result" && "同步完成"}
              {phase === "error" && "同步失败"}
            </p>
          </div>
          {phase !== "syncing" ? (
            <button
              onClick={onClose}
              className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]"
            >
              <XIcon size={16} />
            </button>
          ) : null}
        </div>

        {/* 内容区 */}
        <div className="px-5 py-5 text-xs">
          {(phase === "preview" || phase === "result") && data ? (
            <>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "从上游拉取", value: data.fetched },
                  { label: "映射成功", value: data.mapped },
                  { label: "新建", value: data.created },
                  { label: "更新", value: data.updated },
                  { label: "跳过（已存在）", value: data.skipped },
                  { label: "自动分配", value: data.assigned },
                ].map((item) => (
                  <div key={item.label} className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 py-2 text-center">
                    <div className="text-lg font-bold text-[#1a1f2e]">{item.value}</div>
                    <div className="mt-0.5 text-[10px] text-[#8b95a6]">{item.label}</div>
                  </div>
                ))}
              </div>

              {items.length > 0 ? (
                <div className="mt-4">
                  <p className="mb-2 font-semibold text-[#1a1f2e]">
                    线索预览（前 {items.length} 条）
                  </p>
                  <div className="space-y-2">
                    {items.map((item, index) => (
                      <div
                        key={index}
                        className="flex items-center justify-between rounded-lg border border-[#e4e8f0] px-3 py-2"
                      >
                        <div className="min-w-0">
                          <span className="font-semibold text-[#1a1f2e]">
                            {item.customer_name || "-"}
                          </span>
                          <span className="ml-2 text-[#64748b]">
                            {item.source_id || "-"}
                          </span>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <span className="rounded-md bg-[#f4f6f8] px-2 py-0.5 text-[10px] font-semibold text-[#64748b]">
                            {item.action || "-"}
                          </span>
                          <span className="text-[10px] text-[#8b95a6]">{item.reason || "-"}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          ) : null}

          {phase === "syncing" ? (
            <div className="flex flex-col items-center py-8">
              <LoaderIcon size={32} className="animate-spin text-[#2563eb]" />
              <p className="mt-4 text-sm font-semibold text-[#1a1f2e]">正在同步线索...</p>
              <p className="mt-1 text-[11px] text-[#8b95a6]">请勿关闭窗口</p>
            </div>
          ) : null}

          {phase === "error" ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3">
              <p className="font-semibold text-red-700">同步失败</p>
              <p className="mt-1 text-[11px] text-red-600">{syncError || "未知错误"}</p>
            </div>
          ) : null}
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          {phase === "preview" ? (
            <>
              <button
                onClick={onClose}
                className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]"
              >
                取消
              </button>
              <button
                onClick={onConfirm}
                className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
              >
                确认同步（写入数据库）
              </button>
            </>
          ) : null}
          {phase === "result" ? (
            <button
              onClick={onClose}
              className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
            >
              关闭
            </button>
          ) : null}
          {phase === "error" ? (
            <button
              onClick={onClose}
              className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]"
            >
              关闭
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ========== 分配弹窗 ==========

interface AssignModalProps {
  lead: Lead;
  currentStaffName: string;
  staffList: Staff[];
  submitting: boolean;
  onConfirm: (staffId: number, remark: string) => void;
  onClose: () => void;
}

function AssignModal({ lead, currentStaffName, staffList, submitting, onConfirm, onClose }: AssignModalProps) {
  const [selectedStaffId, setSelectedStaffId] = useState<number | null>(null);
  const [remark, setRemark] = useState("");
  const canSubmit = selectedStaffId !== null && !submitting;

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (selectedStaffId !== null) {
            onConfirm(selectedStaffId, remark.trim());
          }
        }}
        className="w-full max-w-[460px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]"
      >
        {/* 标题栏 */}
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h3 className="text-base font-bold text-[#1a1f2e]">分配销售</h3>
            <p className="mt-1 text-xs text-[#8b95a6]">为当前线索选择接待销售</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8] disabled:opacity-50"
          >
            <XIcon size={16} />
          </button>
        </div>

        {/* 线索信息 */}
        <div className="grid gap-4 px-5 py-5 text-xs">
          <div className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-3">
            <div className="font-bold text-[#1a1f2e]">{lead.customer_name || "-"}</div>
            <div className="mt-1 text-[#64748b]">
              状态：{leadStatusLabel(lead)} · 当前销售：{currentStaffName}
            </div>
          </div>

          {/* 销售下拉 */}
          {staffList.length === 0 ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-amber-700">
              暂无可用销售，请先在系统中添加销售人员
            </div>
          ) : (
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">选择销售</span>
              <select
                value={selectedStaffId ?? ""}
                onChange={(event) => {
                  const val = event.target.value;
                  setSelectedStaffId(val ? Number(val) : null);
                }}
                className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-3 outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
              >
                <option value="">请选择销售</option>
                {staffList.map((staff) => (
                  <option key={staff.id} value={staff.id}>
                    {staff.name}
                    {staff.wechat_nickname ? `（${staff.wechat_nickname}）` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">分配备注</span>
            <textarea
              value={remark}
              onChange={(event) => setRemark(event.target.value)}
              rows={3}
              placeholder="填写本次分配或重新分配原因"
              className="resize-none rounded-xl border border-[#e4e8f0] bg-white px-3 py-2 outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
            />
          </label>
        </div>

        {/* 底部按钮 */}
        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151] disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "提交中..." : "确认分配"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ========== 详情面板 ==========

interface LeadDetailProps {
  lead: Lead;
  staffName: string;
  staffList: Staff[];
  checks: CheckRecord[];
  notificationRecords: NotificationRecord[];
  loadingNotifications: boolean;
  assignSubmitting: boolean;
  detectLoading: boolean;
  detectResult: WechatDetectResponse | null;
  pendingCheckId: number | null;
  isAutoDetectTarget: boolean;
  intervalSeconds: number;
  notifyLoading: boolean;
  agentStatus: AgentStatusData;
  onOpenAssign: () => void;
  onDetect: () => void;
  onSetAutoDetect: () => void;
  onClearAutoDetect: () => void;
  onSendToStaff: () => void;
}

function DouyinChatTimeline({ lead }: { lead: Lead }) {
  const [events, setEvents] = useState<WebhookEvent[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const visibleEvents = useMemo(() => events.slice(-5), [events]);
  const hiddenCount = Math.max(0, total - visibleEvents.length);

  useEffect(() => {
    let cancelled = false;

    async function loadChatEvents() {
      setLoading(true);
      setError(null);
      try {
        const leadEvents = await fetchWebhookEvents({
          page: 1,
          page_size: 1,
          lead_id: lead.id,
        });
        const leadEvent = leadEvents.data.items[0] || null;
        const convId = leadEvent?.conversation_short_id || null;
        const result = convId
          ? await fetchWebhookEvents({
              page: 1,
              page_size: 100,
              conversation_short_id: convId,
            })
          : lead.source_id
            ? await fetchWebhookEvents({
                page: 1,
                page_size: 100,
                open_id: lead.source_id,
              })
            : { data: { total: 0, items: [] as WebhookEvent[] } };

        if (cancelled) return;
        setConversationId(convId);
        setEvents(sortEventsAsc(result.data.items || []));
        setTotal(result.data.total || 0);
      } catch (err) {
        if (cancelled) return;
        setConversationId(null);
        setEvents([]);
        setTotal(0);
        setError(err instanceof Error ? err.message : "抖音私信记录加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadChatEvents();
    return () => {
      cancelled = true;
    };
  }, [lead.id, lead.source_id]);

  return (
    <section className="mb-4 rounded-xl border border-[#e4e8f0] bg-white p-3">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <MessageCircleIcon size={15} className="text-[#2563eb]" />
            <h3 className="text-sm font-bold text-[#1a1f2e]">抖音私信记录</h3>
          </div>
          <p className="mt-1 truncate text-[11px] text-[#8b95a6]" title={conversationId || undefined}>
            会话 ID：{conversationId ? shortId(conversationId, 12, 8) : "未识别，按客户 open_id 兜底"}
          </p>
        </div>
        <span className="rounded-md bg-[#f8fafc] px-2 py-0.5 text-[11px] font-semibold text-[#64748b]">
          消息数：{loading ? "..." : total}
        </span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center gap-2 rounded-lg bg-[#f8fafc] py-5 text-xs text-[#8b95a6]">
          <LoaderIcon size={14} className="animate-spin" />
          加载私信记录
        </div>
      ) : error ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          {error}
        </div>
      ) : events.length === 0 ? (
        <div className="rounded-lg bg-[#f8fafc] px-3 py-5 text-center text-xs text-[#8b95a6]">
          暂无已入库的抖音私信事件
        </div>
      ) : (
        <div className="space-y-3">
          {hiddenCount > 0 ? (
            <div className="rounded-lg bg-[#f8fafc] px-3 py-2 text-[11px] text-[#8b95a6]">
              右侧仅显示最近 {visibleEvents.length} 条私信摘要，完整会话可在抖音A小高客服页查看。
            </div>
          ) : null}
          {visibleEvents.map((event) => {
            const direction = douyinDirection(event.event);
            const messageText = event.message_text?.trim();
            return (
              <article key={event.id} className={`rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-3 ${direction.align}`}>
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${direction.tone}`}>
                    {direction.label}
                  </span>
                  <span className="font-mono text-[10px] text-[#8b95a6]">{event.event || "-"}</span>
                  <span className="ml-auto text-[10px] text-[#8b95a6]">{formatTime(event.created_at)}</span>
                </div>
                <p className="whitespace-pre-wrap break-words rounded-lg bg-white px-3 py-2 text-[12px] leading-5 text-[#334155]">
                  {messageText || "无文本内容"}
                </p>
                <div className="mt-2 grid gap-1 text-[10px] text-[#8b95a6]">
                  <div className="truncate" title={event.from_user_id || undefined}>from_user_id：{shortId(event.from_user_id)}</div>
                  <div className="truncate" title={event.to_user_id || undefined}>to_user_id：{shortId(event.to_user_id)}</div>
                  <div className="truncate" title={event.server_message_id || undefined}>server_message_id：{shortId(event.server_message_id, 12, 8)}</div>
                  <div className="flex flex-wrap gap-2">
                    <span>lead_action：{event.lead_action || "-"}</span>
                    <span>contact_extract_status：{event.contact_extract_status || "-"}</span>
                    <span>customer_contact：{event.customer_contact || "-"}</span>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function LeadDetail({ lead, staffName, staffList, checks, notificationRecords, loadingNotifications, assignSubmitting, detectLoading, detectResult, pendingCheckId, isAutoDetectTarget, intervalSeconds, notifyLoading, agentStatus, onOpenAssign, onDetect, onSetAutoDetect, onClearAutoDetect, onSendToStaff }: LeadDetailProps) {
  // 按钮启用条件：有可用销售
  const canAssign = staffList.length > 0 && !assignSubmitting;
  const scorePercent = leadScorePercent(lead);
  const city = leadDerivedValue(lead, "city") || "未提供";
  const carModel = leadDerivedValue(lead, "car_model") || "未提供";
  const budget = leadDerivedValue(lead, "budget") || "未提供";
  const traceItems = leadTraceItems(lead);
  const currentStaffName = lead.assigned_staff?.name || staffName || "未分配";
  const operationalTags = deriveOperationalTags(lead, checks, notificationRecords);
  const followUpTag = operationalTags.find((tag) => tag.key === "follow_up");
  const conversationUrl = buildDouyinConversationUrl(lead);

  // 检测按钮可用条件
  const agentReason = agentDisabledReason(agentStatus);
  const canDetect = lead.status === "assigned" && lead.assigned_staff_id !== null && !detectLoading && agentStatus.can_run_wechat_action;
  const canSetAutoDetect = Boolean(pendingCheckId) && agentStatus.can_run_wechat_action;
  const canSendToStaff = lead.status === "assigned" && lead.assigned_staff_id !== null && !notifyLoading && agentStatus.can_run_wechat_action;

  // 检测按钮禁用提示
  let detectDisabledReason = "";
  if (lead.status === "pending") detectDisabledReason = "请先分配销售";
  else if (lead.status === "replied") detectDisabledReason = "该线索已跟进";
  else if (lead.status === "timeout") detectDisabledReason = "该线索已超时";
  else if (lead.status === "closed") detectDisabledReason = "该线索已关闭";
  else if (!lead.assigned_staff_id) detectDisabledReason = "请先分配销售";

  return (
    <aside className="h-full min-h-0 overflow-y-auto overflow-x-hidden border-l border-[#e4e8f0] bg-white">
      <section className="border-b border-[#e4e8f0] p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <img
              src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${lead.customer_name || lead.id}&backgroundColor=b6e3f4,c0aede,d1d4f9`}
              alt={lead.customer_name || "-"}
              className="h-12 w-12 rounded-full bg-[#e0edff] ring-4 ring-[#f1f5f9]"
            />
            <div>
              <p className="text-[11px] font-semibold text-[#8b95a6]">客户信息</p>
              <h3 className="mt-1 text-[15px] font-bold text-[#1a1f2e]">
                {lead.customer_name || "-"}
              </h3>
            </div>
          </div>
          <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${statusClass(lead.status)}`}>
            {leadStatusLabel(lead)}
          </span>
        </div>

        <div className="mt-4 grid gap-3 text-xs">
          {[
            ["联系方式", leadPrimaryContact(lead)],
            ["提取状态", contactStatusLabel(lead.contact_extract_status)],
            ["来源", lead.source],
            ["线索类型", lead.lead_type || "-"],
            ["意向车型", carModel],
            ["预算", budget],
            ["城市", city],
            ["当前销售", currentStaffName],
          ].map(([label, value]) => {
            const display = detailValue(label, value);
            return (
              <div key={label} className="flex min-w-0 justify-between gap-4">
                <span className="shrink-0 text-[#8b95a6]">{label}</span>
                <strong className="min-w-0 break-words text-right font-semibold text-[#374151]" title={display.title}>
                  {display.text}
                </strong>
              </div>
            );
          })}
        </div>

        <div className="mt-4 rounded-xl border border-[#e4e8f0] bg-white p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold text-[#1a1f2e]">运营标签</p>
            {loadingNotifications ? <span className="text-[10px] text-[#8b95a6]">正在读取跟进状态...</span> : null}
          </div>
          {operationalTags.length ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {operationalTags.map((tag) => (
                <span
                  key={tag.key}
                  title={tag.reasons.join("；")}
                  className={`rounded-md px-2 py-1 text-[11px] font-semibold ring-1 ${tag.tone}`}
                >
                  {tag.cautious ? `可能${tag.label}` : tag.label}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-[11px] text-[#8b95a6]">暂无明确运营标签</p>
          )}
          {followUpTag ? (
            <div className="mt-2 rounded-lg bg-[#f8fafc] px-3 py-2 text-[11px] leading-5 text-[#64748b]">
              <div className="font-semibold text-[#374151]">{followUpTag.cautious ? "可能待回访依据" : "待回访依据"}</div>
              {followUpTag.reasons.map((reason) => (
                <div key={reason}>- {reason}</div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="mt-3">
          {conversationUrl ? (
            <a
              href={conversationUrl}
              className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50 text-xs font-semibold text-blue-700 hover:bg-blue-100"
            >
              <MessageCircleIcon size={14} />
              查看抖音会话
            </a>
          ) : (
            <div className="rounded-xl border border-dashed border-[#e4e8f0] bg-[#f8fafc] px-3 py-2 text-center text-[11px] text-[#8b95a6]">
              暂无可跳转的抖音会话
            </div>
          )}
        </div>

        {lead.content ? (
          <div className="mt-4 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-3">
            <p className="mb-1 text-xs font-semibold text-[#1a1f2e]">线索内容</p>
            <p className="break-words text-[11px] leading-relaxed text-[#64748b]">{lead.content}</p>
          </div>
        ) : null}

        {lead.lead_score && scorePercent !== null ? (
          <div className="mt-4 rounded-xl border border-[#e4e8f0] bg-white p-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-[#1a1f2e]">线索评分</p>
              <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                {leadScoreLevelLabel(lead.lead_score.level)} · {scorePercent}%
              </span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#e5e7eb]">
              <div
                className="h-full rounded-full bg-emerald-500 transition-all"
                style={{ width: `${scorePercent}%` }}
              />
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(lead.lead_score.reasons || []).map((reason) => (
                <span key={reason} className="rounded-md bg-[#f8fafc] px-2 py-1 text-[11px] text-[#64748b]">
                  {reason}
                </span>
              ))}
            </div>
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-[#e4e8f0] bg-white p-3 text-xs text-[#8b95a6]">
            暂无评分
          </div>
        )}

        <div className="mt-4 rounded-xl border border-[#e4e8f0] bg-white p-3">
          <p className="text-xs font-semibold text-[#1a1f2e]">销售跟进记录</p>
          {lead.timeline && lead.timeline.length > 0 ? (
            <div className="mt-3 space-y-2">
              {lead.timeline.map((item) => {
                const action = item.action_label || timelineTypeLabel(item.record_type);
                const remark = item.remark || item.content || "无备注";
                return (
                  <div key={`${item.record_type}-${item.id}`} className="rounded-lg bg-[#f8fafc] px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-[#374151] ring-1 ring-[#e4e8f0]">
                        {action}
                      </span>
                      <span className="text-[10px] text-[#8b95a6]">{formatTime(item.created_at)}</span>
                    </div>
                    <div className="mt-2 grid gap-1 text-[11px] leading-relaxed">
                      <div className="flex gap-2">
                        <span className="shrink-0 text-[#8b95a6]">操作内容</span>
                        <span className="min-w-0 break-words font-semibold text-[#374151]">{item.content || action}</span>
                      </div>
                      <div className="flex gap-2">
                        <span className="shrink-0 text-[#8b95a6]">备注信息</span>
                        <span className="min-w-0 break-words text-[#64748b]">{remark}</span>
                      </div>
                      {item.staff_name || item.staff_id ? (
                        <div className="flex gap-2">
                          <span className="shrink-0 text-[#8b95a6]">操作人</span>
                          <span className="min-w-0 break-words text-[#64748b]">{item.staff_name || `销售 #${item.staff_id}`}</span>
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="mt-3 rounded-lg bg-[#f8fafc] px-3 py-5 text-center text-xs text-[#8b95a6]">
              暂无销售跟进记录
            </div>
          )}
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2">
          <button
            onClick={onOpenAssign}
            disabled={!canAssign}
            title={staffList.length === 0 ? "暂无可用销售" : "分配销售"}
            className="h-9 rounded-xl bg-[#2563eb] text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {assignSubmitting ? "提交中..." : "重新分配"}
          </button>
          <button
            onClick={onDetect}
            disabled={!canDetect}
            title={detectDisabledReason || (!agentStatus.can_run_wechat_action ? agentReason : "检测微信回复")}
            className="h-9 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] text-xs font-semibold text-[#374151] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {detectLoading ? "检测中..." : "检测微信回复"}
          </button>
        </div>
        {/* 自动检测目标按钮 */}
        {lead.status === "assigned" && lead.assigned_staff_id ? (
          <div className="mt-2">
            {isAutoDetectTarget ? (
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1.5 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700">
                  <LoaderIcon size={12} className="animate-spin" />
                  监听中（每 {intervalSeconds} 秒）
                </span>
                <button
                  onClick={onClearAutoDetect}
                  className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 py-2 text-xs font-semibold text-[#64748b] hover:bg-white"
                >
                  取消监听
                </button>
              </div>
            ) : (
              <button
                onClick={onSetAutoDetect}
                disabled={!canSetAutoDetect}
                title={!agentStatus.can_run_wechat_action ? agentReason : pendingCheckId ? `设为自动检测目标，每 ${intervalSeconds} 秒自动检测` : "暂无待检测任务"}
                className="h-9 w-full rounded-xl border border-emerald-200 bg-emerald-50 text-xs font-semibold text-emerald-700 disabled:cursor-not-allowed disabled:opacity-50 hover:bg-emerald-100"
              >
                设为自动检测目标
              </button>
            )}
          </div>
        ) : null}
        {/* 发送线索给销售按钮（Demo） */}
        {lead.status === "assigned" && lead.assigned_staff_id ? (
          <div className="mt-2">
            <button
              onClick={onSendToStaff}
              disabled={!canSendToStaff}
              title={!agentStatus.can_run_wechat_action ? agentReason : "自动搜索销售微信并发送线索通知"}
              className="h-9 w-full rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 text-xs font-semibold text-white shadow-[0_4px_12px_rgba(37,99,235,0.3)] disabled:cursor-not-allowed disabled:opacity-50 hover:from-blue-700 hover:to-indigo-700"
            >
              {notifyLoading ? "发送中..." : "发送线索给销售"}
            </button>
          </div>
        ) : null}
      </section>

      <section className="p-4">
        <DouyinChatTimeline lead={lead} />

        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-bold text-[#1a1f2e]">销售跟进</h3>
          <button className="grid h-7 w-7 place-items-center rounded-lg text-[#8b95a6] hover:bg-[#f4f6f8]">
            <MoreHorizontalIcon size={15} />
          </button>
        </div>
        {/* 销售跟进状态提示：未反馈 / 已联系 / 联系方式错误（纯派生，P0-DY-LEAD-CAPTURE 状态口径） */}
        {lead.sales_followup_status === "contacted" ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-xs">
            <div className="flex items-center gap-2">
              <CheckCircleIcon size={14} className="text-emerald-600" />
              <span className="font-semibold text-emerald-700">已联系</span>
            </div>
            <p className="mt-1.5 text-[11px] text-emerald-600">已检测到销售有效回复</p>
          </div>
        ) : lead.sales_followup_status === "no_feedback" ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs">
            <div className="flex items-center gap-2">
              <CheckCircleIcon size={14} className="text-amber-600" />
              <span className="font-semibold text-amber-700">未反馈</span>
            </div>
            <p className="mt-1.5 text-[11px] text-amber-600">
              已分配销售并发送通知，暂无销售反馈（不会重新分配）
            </p>
          </div>
        ) : lead.sales_followup_status === "contact_invalid" ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-3 text-xs">
            <div className="flex items-center gap-2">
              <CheckCircleIcon size={14} className="text-rose-600" />
              <span className="font-semibold text-rose-700">联系方式错误</span>
            </div>
            <p className="mt-1.5 text-[11px] text-rose-600">
              销售反馈号码无效，建议抖音私信向客户核实
            </p>
          </div>
        ) : null}

        {/* 本次检测结果展示 */}
        {detectResult && detectResult.matched_content ? (
          <div className="mt-3 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 py-3 text-xs">
            <p className="font-semibold text-[#1a1f2e]">检测结果</p>
            <div className="mt-2 grid gap-1.5 text-[11px]">
              <div className="flex justify-between gap-2">
                <span className="shrink-0 text-[#8b95a6]">回复内容</span>
                <span className="text-right font-semibold text-[#374151]">{detectResult.matched_content}</span>
              </div>
              {detectResult.effectiveness_reason ? (
                <div className="flex justify-between gap-2">
                  <span className="shrink-0 text-[#8b95a6]">判定原因</span>
                  <span className="text-right font-semibold text-[#374151]">{detectResult.effectiveness_reason}</span>
                </div>
              ) : null}
              {detectResult.detection_mode ? (
                <div className="flex justify-between gap-2">
                  <span className="shrink-0 text-[#8b95a6]">检测模式</span>
                  <span className="text-right font-semibold text-[#374151]">{detectResult.detection_mode}</span>
                </div>
              ) : null}
            </div>
            {detectResult.warning ? (
              <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-[10px] text-amber-700">
                ⚠ {detectResult.warning}
              </div>
            ) : null}
          </div>
        ) : !detectResult && lead.status !== "replied" ? (
          <div className="px-3 py-6 text-center text-xs text-[#8b95a6]">
            暂无跟进记录
          </div>
        ) : null}
      </section>
    </aside>
  );
}

// ========== 主页面 ==========

export default function LeadsManagement() {
  // API 数据
  const [leads, setLeads] = useState<Lead[]>([]);
  const [totalLeads, setTotalLeads] = useState(0);
  const [staffList, setStaffList] = useState<Staff[]>([]);
  const [summary, setSummary] = useState<ReportSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 同步弹窗状态
  const [syncPhase, setSyncPhase] = useState<SyncPhase | null>(null);
  const [syncPreview, setSyncPreview] = useState<DouyinSyncResponse | null>(null);
  const [syncResult, setSyncResult] = useState<DouyinSyncResponse | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);

  // 分配弹窗状态
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [assignLeadDraft, setAssignLeadDraft] = useState<Lead | null>(null);
  const [assignSubmitting, setAssignSubmitting] = useState(false);

  // 检测状态
  const [detectLoading, setDetectLoading] = useState(false);
  const [detectResult, setDetectResult] = useState<WechatDetectResponse | null>(null);

  // 自动检测状态
  const [checksData, setChecksData] = useState<CheckRecord[]>([]);
  const [autoDetectStatus, setAutoDetectStatus] = useState<WechatAutoDetectStatus | null>(null);
  const [notifyLoading, setNotifyLoading] = useState(false);
  const [notificationRecords, setNotificationRecords] = useState<NotificationRecord[]>([]);
  const [loadingNotifications, setLoadingNotifications] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AgentStatusData>(AGENT_STATUS_FALLBACK);

  // 筛选与分页
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState<LeadStatus | "全部状态">("全部状态");
  const [source, setSource] = useState("all");
  const [assignedStaffFilter, setAssignedStaffFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // staffId → staffName 映射
  const staffMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const s of staffList) {
      map.set(s.id, s.name);
    }
    return map;
  }, [staffList]);

  const getStaffName = useCallback(
    (staffId: number | null) => {
      if (!staffId) return "未分配";
      return staffMap.get(staffId) || "未知销售";
    },
    [staffMap],
  );

  // 刷新全部数据
  const refreshData = useCallback(async () => {
    const [leadsData, staffData, summaryData, checksRes, autoStatusRes, agentStatusRes] = await Promise.all([
      fetchLeadsPage({
        keyword: keyword.trim() || undefined,
        source: source === "all" ? undefined : source,
        status: status === "全部状态" ? undefined : status,
        assigned_staff_id: assignedStaffFilter === "all" ? undefined : assignedStaffFilter,
        page,
        page_size: pageSize,
      }),
      fetchStaffList("active"),
      fetchSummary(),
      fetchChecks(),
      fetchWechatAutoDetectStatus().catch(() => null),
      fetchAgentStatus().catch(() => null),
    ]);
    setLeads(leadsData.data.items);
    setTotalLeads(leadsData.data.total);
    setStaffList(staffData);
    setSummary(summaryData);
    setChecksData(checksRes);
    if (autoStatusRes) setAutoDetectStatus(autoStatusRes);
    setAgentStatus(agentStatusRes?.success ? agentStatusRes.data : AGENT_STATUS_FALLBACK);
  }, [assignedStaffFilter, keyword, page, pageSize, source, status]);

  // 页面加载时拉取数据
  useEffect(() => {
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        await refreshData();
      } catch (err) {
        setError(err instanceof Error ? err.message : "数据加载失败");
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [refreshData]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;

    async function loadSelectedLeadDetail() {
      try {
        const detail = await fetchLead(selectedId);
        if (cancelled) return;
        setLeads((current) => current.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof Error ? err.message : "线索详情加载失败");
        }
      }
    }

    void loadSelectedLeadDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setNotificationRecords([]);
      return;
    }
    let cancelled = false;

    async function loadNotificationRecords() {
      setLoadingNotifications(true);
      try {
        const result = await fetchNotificationRecords({ lead_id: selectedId, limit: 20 });
        if (!cancelled) {
          setNotificationRecords(result.records || []);
        }
      } catch (err) {
        if (!cancelled) {
          setNotificationRecords([]);
          toast.error(err instanceof Error ? err.message : "线索通知记录加载失败");
        }
      } finally {
        if (!cancelled) {
          setLoadingNotifications(false);
        }
      }
    }

    void loadNotificationRecords();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  // ========== 同步流程 ==========

  const handleSyncPreview = async () => {
    setSyncLoading(true);
    try {
      const result = await syncDouyinLeads({ dryRun: true, autoAssign: false });
      setSyncPreview(result);
      setSyncResult(null);
      setSyncError(null);
      setSyncPhase("preview");
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "预览请求失败");
      setSyncPhase("error");
    } finally {
      setSyncLoading(false);
    }
  };

  const handleSyncConfirm = async () => {
    setSyncPhase("syncing");
    try {
      const result = await syncDouyinLeads({ dryRun: false, autoAssign: false });
      setSyncResult(result);
      setSyncPhase("result");
      await refreshData();
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "同步失败");
      setSyncPhase("error");
    }
  };

  const handleSyncClose = () => {
    setSyncPhase(null);
    setSyncPreview(null);
    setSyncResult(null);
    setSyncError(null);
  };

  // ========== 分配流程 ==========

  const handleOpenAssign = () => {
    if (!selectedLead) return;
    setAssignLeadDraft(selectedLead);
    setShowAssignModal(true);
  };

  const handleAssignConfirm = async (staffId: number, remark: string) => {
    const targetLead = assignLeadDraft || selectedLead;
    if (!targetLead) return;
    setAssignSubmitting(true);
    try {
      await assignLead(targetLead.id, staffId, remark || undefined);
      toast.success(`已分配给 ${getStaffName(staffId)}`);
      setShowAssignModal(false);
      setAssignLeadDraft(null);
      // 刷新列表，保持选中线索
      await refreshData();
    } catch (err) {
      const message = err instanceof Error ? err.message : "分配失败";
      toast.error(message);
    } finally {
      setAssignSubmitting(false);
    }
  };

  const handleAssignClose = () => {
    if (!assignSubmitting) {
      setShowAssignModal(false);
      setAssignLeadDraft(null);
    }
  };

  // ========== 检测流程 ==========

  // 切换线索时清空检测结果
  useEffect(() => {
    setDetectResult(null);
  }, [selectedId]);

  const handleDetect = async () => {
    if (!selectedLead || !selectedLead.assigned_staff_id) return;
    if (!agentStatus.can_run_wechat_action) {
      toast.warning(agentDisabledReason(agentStatus));
      return;
    }

    const confirmed = window.confirm(
      `请确认主机微信当前已打开对应销售的聊天窗口，并且销售已回复「收到，已添加微信」。`,
    );
    if (!confirmed) return;

    setDetectLoading(true);
    try {
      const result = await detectWechatReply({
        leadId: selectedLead.id,
        staffId: selectedLead.assigned_staff_id,
        maxMessages: 20,
        confirmCurrentChat: true,
      });
      setDetectResult(result);

      if (!result.success) {
        toast.error(result.message);
      } else if (result.is_effective === 1) {
        toast.success("检测到有效回复，线索已标记为已跟进");
        if (result.warning) {
          toast.warning(result.warning);
        }
        await refreshData();
      } else {
        toast.warning("未检测到有效回复");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "检测请求失败");
    } finally {
      setDetectLoading(false);
    }
  };

  // 前端搜索与状态筛选
  const filtered = leads;
  const hasActiveFilters =
    keyword.trim() || status !== "全部状态" || source !== "all" || assignedStaffFilter !== "all";
  const totalPages = Math.max(1, Math.ceil(totalLeads / pageSize));
  const currentPage = page;
  const pagedLeads = filtered;
  const selectedLead = leads.find((lead) => lead.id === selectedId) || null;

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  // ========== 自动检测目标流程 ==========

  // 找到当前线索对应的 pending check
  const findPendingCheck = useCallback(() => {
    if (!selectedLead || !selectedLead.assigned_staff_id) return null;
    return checksData.find(
      (c) =>
        c.lead_id === selectedLead.id &&
        c.staff_id === selectedLead.assigned_staff_id &&
        c.check_status === "pending",
    ) ?? null;
  }, [selectedLead, checksData]);

  // 当前线索是否是自动检测目标
  const isAutoDetectTarget = selectedLead
    ? autoDetectStatus?.active_check_id != null &&
      checksData.find((c) => c.id === autoDetectStatus.active_check_id)?.lead_id === selectedLead.id
    : false;

  // 设置自动检测目标
  const handleSetAutoDetect = async () => {
    const check = findPendingCheck();
    if (!check) return;
    if (!agentStatus.can_run_wechat_action) {
      toast.warning(agentDisabledReason(agentStatus));
      return;
    }

    const confirmed = window.confirm(
      `请确认主机微信当前停留在该销售聊天窗口，否则可能误判。\n\n设置后系统将每 ${autoDetectStatus?.interval_seconds ?? 10} 秒自动检测微信回复。`,
    );
    if (!confirmed) return;

    try {
      const result = await setWechatAutoDetectTarget(check.id);
      if (result.success) {
        toast.success("已设为自动检测目标");
        setAutoDetectStatus(result);
      } else {
        toast.error(result.message);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "设置自动检测目标失败");
    }
  };

  // 取消自动检测目标
  const handleClearAutoDetect = async () => {
    try {
      const result = await clearWechatAutoDetectTarget();
      if (result.success) {
        toast.success("已取消自动检测");
        setAutoDetectStatus(result);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "取消自动检测失败");
    }
  };

  // 发送线索给销售（自动搜索 + 发送 + 设置自动检测）
  const handleSendToStaff = async () => {
    if (!selectedLead || !selectedLead.assigned_staff_id) return;
    if (!agentStatus.can_run_wechat_action) {
      toast.warning(agentDisabledReason(agentStatus));
      return;
    }

    const confirmed = window.confirm(
      `将自动搜索销售微信并发送线索通知。\n系统将自动打开销售聊天窗口并粘贴消息。`,
    );
    if (!confirmed) return;

    setNotifyLoading(true);
    try {
      const result = await sendLeadToStaff(selectedLead.id, true);
      if (result.success) {
        toast.success(result.message || "线索已发送给销售，正在等待回复");
        // 刷新数据
        refreshData();
      } else {
        toast.error(result.message || "发送失败");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "发送线索通知失败");
    } finally {
      setNotifyLoading(false);
    }
  };

  // 统计卡片
  const statCards = summary
    ? [
        {
          label: "累计线索",
          value: String(summary.total_leads),
          hint: leadGrowthHint(summary),
          icon: <InboxIcon size={17} />,
          tone: "bg-blue-100 text-blue-700 ring-blue-200",
        },
        {
          label: "已分配",
          value: String(summary.assigned_count),
          hint: formatPercent(summary.sales_response_rate) ? `销售响应率 ${formatPercent(summary.sales_response_rate)}` : "暂无响应数据",
          icon: <UserCheckIcon size={17} />,
          tone: "bg-slate-100 text-slate-700 ring-slate-200",
        },
        {
          label: "已留资",
          value: String(summary.retained_contact_count ?? 0),
          hint: formatPercent(summary.retained_contact_rate) ? `转化率 ${formatPercent(summary.retained_contact_rate)}` : "暂无转化数据",
          icon: <CheckCircleIcon size={17} />,
          tone: "bg-emerald-100 text-emerald-700 ring-emerald-200",
        },
        {
          label: "高意向",
          value: String(summary.high_intent_count ?? 0),
          hint: summary.high_intent_hint || "暂无高意向线索",
          icon: <AlertTriangleIcon size={17} />,
          tone: "bg-amber-100 text-amber-700 ring-amber-200",
        },
      ]
    : [];

  // 加载状态
  if (loading) {
    return (
      <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
        <div className="grid h-full place-items-center">
          <p className="text-sm text-[#8b95a6]">加载中...</p>
        </div>
      </section>
    );
  }

  // 错误状态
  if (error) {
    return (
      <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
        <div className="grid h-full place-items-center px-8">
          <div className="text-center">
            <p className="text-sm font-semibold text-[#1a1f2e]">数据加载失败</p>
            <p className="mt-2 text-xs text-[#8b95a6]">{error}</p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <div className="shrink-0 bg-white">
        <header className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">AI小高线索</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">聚合 AI 识别、留资和销售跟进状态</p>
          </div>
        </header>

        <div className="grid grid-cols-4 gap-0 border-b border-[#e4e8f0]">
          {statCards.map((card) => (
            <div key={card.label} className="border-r border-[#f0f2f7] bg-white p-4 last:border-r-0">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold text-[#8b95a6]">{card.label}</p>
                  <strong className="mt-3 block text-2xl leading-none text-[#1a1f2e]">{card.value}</strong>
                  <p className="mt-2 text-[11px] font-semibold text-[#64748b]">{card.hint}</p>
                </div>
                <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ring-1 ${card.tone}`}>
                  {card.icon}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3 border-b border-[#e4e8f0] bg-[#f8fafc] px-5 py-2 text-[11px] text-[#64748b]">
          <span className="font-semibold text-[#1a1f2e]">本地微信助手：{agentStatusLabel(agentStatus.agent_status)}</span>
          <span>微信状态：{wechatStatusLabel(agentStatus.wechat_status || agentStatus.wechat_available)}</span>
          <span className={agentStatus.can_run_wechat_action ? "font-semibold text-emerald-700" : "font-semibold text-amber-700"}>
            微信自动化：{agentStatus.can_run_wechat_action ? "可用" : "不可用"}
          </span>
          {!agentStatus.can_run_wechat_action ? (
            <span className="min-w-0 truncate text-amber-700">原因：{agentDisabledReason(agentStatus)}</span>
          ) : null}
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_280px] overflow-hidden max-[1180px]:grid-cols-1">
        <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-white">
          <div className="shrink-0 flex items-center justify-between gap-3 border-b border-[#e4e8f0] bg-white px-5 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <label className="relative w-[280px] shrink-0">
                <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
                <input
                  value={keyword}
                  onChange={(event) => {
                    setKeyword(event.target.value);
                    setPage(1);
                  }}
                  placeholder="输入联系人、内容或电话"
                  className="h-9 w-full rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                />
              </label>
              <select
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value as LeadStatus | "全部状态");
                  setPage(1);
                }}
                className="h-9 shrink-0 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none"
              >
                <option>全部状态</option>
                {STATUS_OPTIONS.map((item) => (
                  <option key={item} value={item}>{statusLabel(item)}</option>
                ))}
              </select>
              <select
                value={source}
                onChange={(event) => {
                  setSource(event.target.value);
                  setPage(1);
                }}
                className="h-9 shrink-0 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none"
              >
                <option value="all">全部来源</option>
                {SOURCE_OPTIONS.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
              <select
                value={assignedStaffFilter}
                onChange={(event) => {
                  setAssignedStaffFilter(event.target.value);
                  setPage(1);
                }}
                className="h-9 shrink-0 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] outline-none"
              >
                <option value="all">全部销售</option>
                {staffList.map((staff) => (
                  <option key={staff.id} value={staff.id}>{staff.name}</option>
                ))}
              </select>
              {hasActiveFilters ? (
                <button
                  onClick={() => {
                    setKeyword("");
                    setSource("all");
                    setAssignedStaffFilter("all");
                    setStatus("全部状态");
                    setPage(1);
                  }}
                  className="h-9 shrink-0 rounded-xl px-3 text-xs font-semibold text-[#2563eb] transition-smooth hover:bg-[#eff6ff]"
                >
                  重置
                </button>
              ) : null}
            </div>

            <div className="flex shrink-0 items-center gap-3">
              <span className="text-xs font-semibold text-[#8b95a6]">
                共 <b className="text-[#2563eb]">{totalLeads}</b> 条
              </span>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {pagedLeads.length === 0 ? (
              <div className="px-5 py-12 text-center text-xs text-[#8b95a6]">
                暂无线索数据
              </div>
            ) : (
            <table className="w-full table-fixed text-left text-xs">
              <thead className="bg-[#f8fafc] text-[#64748b]">
                <tr>
                  <th className="w-[15%] px-4 py-3 font-semibold">联系人</th>
                  <th className="w-[17%] px-4 py-3 font-semibold">线索信息</th>
                  <th className="w-[14%] px-4 py-3 font-semibold">联系电话</th>
                  <th className="w-[10%] px-4 py-3 font-semibold">线索状态</th>
                  <th className="w-[16%] px-4 py-3 font-semibold">运营标签</th>
                  <th className="w-[10%] px-4 py-3 font-semibold">分配销售</th>
                  <th className="w-[18%] px-4 py-3 font-semibold">操作</th>
                </tr>
              </thead>
              <tbody>
                {pagedLeads.map((lead) => {
                  const active = selectedId === lead.id;
                  const city = leadDerivedValue(lead, "city") || "城市未提供";
                  const carModel = leadDerivedValue(lead, "car_model") || "车型未提供";
                  const budget = leadDerivedValue(lead, "budget") || "预算未提供";
                  const tags = deriveOperationalTags(lead, checksData);
                  const conversationUrl = buildDouyinConversationUrl(lead);
                  return (
                    <tr
                      key={lead.id}
                      onClick={() => setSelectedId(lead.id)}
                      className={`cursor-pointer border-t border-[#f0f2f7] transition-smooth ${
                        active ? "bg-[#eff6ff]" : "hover:bg-[#f8fafc]"
                      }`}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <img
                            src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${lead.customer_name || lead.id}&backgroundColor=b6e3f4,c0aede,d1d4f9`}
                            alt={lead.customer_name || "-"}
                            className="h-9 w-9 rounded-full bg-[#e0edff]"
                          />
                          <div className="min-w-0">
                            <div className="truncate font-bold text-[#1a1f2e]">
                              {lead.customer_name || "-"}
                            </div>
                            <div className="mt-1 text-[10px] text-[#8b95a6]">
                              {city}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="truncate font-semibold text-[#374151]" title={lead.content || undefined}>
                          {lead.source || "-"} · {carModel}
                        </div>
                        <div className="mt-1 truncate text-[10px] text-[#8b95a6]">{budget}</div>
                        <div className="mt-1 text-[10px] text-[#8b95a6]">{formatTime(lead.created_at)}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="space-y-1 text-[#374151]">
                          {lead.phone ? <div className="truncate">手机号：{lead.phone}</div> : null}
                          {lead.wechat ? <div className="truncate">微信号：{lead.wechat}</div> : null}
                          {!lead.phone && !lead.wechat ? (
                            <div className="truncate">
                              {getLeadContactValues(lead)[0]
                                ? `联系方式：${getLeadContactValues(lead)[0]}`
                                : "-"}
                            </div>
                          ) : null}
                          <div className="text-[10px] text-[#8b95a6]">
                            状态：{contactStatusLabel(lead.contact_extract_status)}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${statusClass(lead.status)}`}>
                          {leadStatusLabel(lead)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {tags.length ? (
                          <div className="flex flex-wrap gap-1.5">
                            {tags.map((tag) => (
                              <span
                                key={tag.key}
                                title={tag.reasons.join("；")}
                                className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ${tag.tone}`}
                              >
                                {tag.cautious ? `可能${tag.label}` : tag.label}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-[11px] text-[#8b95a6]">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-[#374151]">{getStaffName(lead.assigned_staff_id)}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1.5">
                          {conversationUrl ? (
                            <a
                              href={conversationUrl}
                              onClick={(event) => event.stopPropagation()}
                              className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-2 py-1.5 text-[11px] font-semibold text-blue-700 hover:bg-blue-100"
                            >
                              查看抖音会话
                            </a>
                          ) : null}
                          <button
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedId(lead.id);
                              setAssignLeadDraft(lead);
                              setShowAssignModal(true);
                            }}
                            disabled={staffList.length === 0 || assignSubmitting}
                            className="inline-flex items-center gap-1 rounded-lg bg-[#2563eb] px-2 py-1.5 text-[11px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                            title={staffList.length === 0 ? "暂无可用销售" : "重新分配销售"}
                          >
                            重新分配
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            )}
          </div>

          <div className="shrink-0 flex items-center justify-between border-t border-[#e4e8f0] px-5 py-3 text-xs">
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-[#64748b]">
                每页
                <select
                  value={pageSize}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    setPage(1);
                  }}
                  className="h-8 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs font-semibold text-[#374151] outline-none"
                >
                  {[10, 20, 50].map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
                条
              </label>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                disabled={currentPage === 1}
                className="grid h-8 w-8 place-items-center rounded-lg border border-[#e4e8f0] bg-white text-[#64748b] transition-smooth enabled:hover:bg-[#f8fafc] disabled:cursor-not-allowed disabled:opacity-45"
              >
                <ChevronLeftIcon size={14} />
              </button>
              {Array.from({ length: totalPages }).map((_, index) => {
                const pageNo = index + 1;
                return (
                  <button
                    key={pageNo}
                    onClick={() => setPage(pageNo)}
                    className={`h-8 min-w-8 rounded-lg px-2 text-xs font-semibold transition-smooth ${
                      currentPage === pageNo
                        ? "bg-[#2563eb] text-white"
                        : "border border-[#e4e8f0] bg-white text-[#64748b] hover:bg-[#f8fafc]"
                    }`}
                  >
                    {pageNo}
                  </button>
                );
              })}
              <button
                onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                disabled={currentPage === totalPages}
                className="grid h-8 w-8 place-items-center rounded-lg border border-[#e4e8f0] bg-white text-[#64748b] transition-smooth enabled:hover:bg-[#f8fafc] disabled:cursor-not-allowed disabled:opacity-45"
              >
                <ChevronRightIcon size={14} />
              </button>
            </div>
          </div>
        </div>

        {selectedLead ? (
          <LeadDetail
            lead={selectedLead}
            staffName={getStaffName(selectedLead.assigned_staff_id)}
            staffList={staffList}
            checks={checksData}
            notificationRecords={notificationRecords}
            loadingNotifications={loadingNotifications}
            assignSubmitting={assignSubmitting}
            detectLoading={detectLoading}
            detectResult={detectResult}
            pendingCheckId={findPendingCheck()?.id ?? null}
            isAutoDetectTarget={isAutoDetectTarget}
            intervalSeconds={autoDetectStatus?.interval_seconds ?? 10}
            agentStatus={agentStatus}
            onOpenAssign={handleOpenAssign}
            onDetect={handleDetect}
            onSetAutoDetect={handleSetAutoDetect}
            onClearAutoDetect={handleClearAutoDetect}
            notifyLoading={notifyLoading}
            onSendToStaff={handleSendToStaff}
          />
        ) : (
          <aside className="flex h-full min-h-0 flex-col overflow-hidden border-l border-[#e4e8f0] bg-white">
            <div className="grid h-full place-items-center">
              <p className="text-xs text-[#8b95a6]">请选择一条线索</p>
            </div>
          </aside>
        )}
      </div>

      {/* 同步弹窗 */}
      {syncPhase ? (
        <SyncModal
          phase={syncPhase}
          preview={syncPreview}
          result={syncResult}
          syncError={syncError}
          onConfirm={handleSyncConfirm}
          onClose={handleSyncClose}
        />
      ) : null}

      {/* 分配弹窗 */}
      {showAssignModal && (assignLeadDraft || selectedLead) ? (
        <AssignModal
          lead={(assignLeadDraft || selectedLead)!}
          currentStaffName={getStaffName((assignLeadDraft || selectedLead)!.assigned_staff_id)}
          staffList={staffList}
          submitting={assignSubmitting}
          onConfirm={handleAssignConfirm}
          onClose={handleAssignClose}
        />
      ) : null}
    </section>
  );
}
