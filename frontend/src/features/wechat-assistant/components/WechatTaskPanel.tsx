/**
 * 微信任务队列面板（P0-5A-3 / P0-FE-MAIN-1 / P0-REPLY-2）
 *
 * 展示 pending 状态的 WechatTask 列表。
 * 通过主系统后端（VITE_AUTO_WECHAT_API_BASE_URL）查询，
 * 不调用本机 Agent，不执行微信自动化。
 *
 * P0-FE-MAIN-1 新增：
 * - 「创建测试任务并执行」按钮
 * - 调 POST /wechat-tasks 创建 paste_only Aw3 任务
 * - 调 POST 19000 /agent/tasks/poll-and-execute 触发执行
 * - 每 2 秒轮询 GET /wechat-tasks/{task_id} 刷新状态
 *
 * P0-REPLY-2 新增：
 * - 「检测销售回复」按钮
 * - 调 POST 19000 /agent/replies/detect 读取微信消息
 * - 展示检测结果：detected_status / matched_reply / failure_stage
 * - 检测后刷新 checks + notifications + task
 *
 * 安全约束：
 * - 测试面板用于创建本机 Agent 任务并查看回写结果
 * - 真实派单发送由任务 mode 与安全门禁共同决定
 */

import {
  CheckCircle2Icon,
  ClockIcon,
  EyeIcon,
  FileTextIcon,
  InfoIcon,
  Loader2Icon,
  PlayIcon,
  RefreshCwIcon,
  SendIcon,
  XCircleIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  createWechatTask,
  fetchBrowserPendingWechatTasks,
  fetchWechatTask,
} from "../api";
import { pollAndExecuteWechatTask, detectReply, pollAndDetectReply } from "../api";
import { fetchNotificationRecords } from "../api";
import { fetchChecks } from "../api";
import { fetchStaffList, createStaff } from "../api";
import { createLead, assignLead } from "../api";
import { formatDateTimeLocal } from "../../../lib/datetime";
import type {
  WechatTask,
  PollAndExecuteResponse,
  NotificationRecord,
  AgentReplyDetectResponse,
  CheckRecord,
  PollAndDetectResponse,
} from "../types";

// ========== 状态配置 ==========

const TASK_STATUS_LABELS: Record<string, string> = {
  pending: "待执行",
  running: "执行中",
  pasted: "已粘贴",
  sent: "已发送",
  completed: "已完成",
  failed: "失败",
  blocked: "已阻止",
  replied: "已回复",
  timeout: "超时",
  manual_review: "需人工复核",
};

const TASK_STATUS_TONES: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  running: "bg-blue-100 text-blue-700",
  pasted: "bg-sky-100 text-sky-700",
  sent: "bg-emerald-100 text-emerald-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  blocked: "bg-slate-100 text-slate-700",
  replied: "bg-emerald-100 text-emerald-700",
  timeout: "bg-red-100 text-red-700",
  manual_review: "bg-amber-100 text-amber-700",
};

const MODE_LABELS: Record<string, string> = {
  paste_only: "仅粘贴",
  single_send: "单条发送",
};

const SEND_STATUS_LABELS: Record<string, string> = {
  pending: "等待处理",
  pasted: "已粘贴，未发送",
  sent: "已发送",
  failed: "执行失败",
  blocked: "安全门禁阻止",
  replied: "销售已回复",
  timeout: "超时未回复",
  manual_review: "需要人工复核",
};

const SEND_STATUS_TONES: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  pasted: "bg-sky-100 text-sky-700",
  sent: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  blocked: "bg-slate-100 text-slate-700",
  replied: "bg-emerald-100 text-emerald-700",
  timeout: "bg-red-100 text-red-700",
  manual_review: "bg-amber-100 text-amber-700",
};

/** P0-REPLY-2：检测状态标签 */
const DETECT_STATUS_LABELS: Record<string, string> = {
  replied: "检测到有效回复",
  pending: "未检测到有效回复",
  manual_review: "需人工确认",
  failed: "检测失败",
  blocked: "安全门禁阻止",
};

const DETECT_STATUS_TONES: Record<string, string> = {
  replied: "bg-emerald-100 text-emerald-700",
  pending: "bg-amber-100 text-amber-700",
  manual_review: "bg-orange-100 text-orange-700",
  failed: "bg-red-100 text-red-700",
  blocked: "bg-slate-100 text-slate-700",
};

/** P0-FE-MAIN-2A：确保存在 Aw3 销售，返回 staff_id */
async function ensureAw3Staff(): Promise<number> {
  const list = await fetchStaffList("active");
  const existing = list.find((s) => s.wechat_nickname === "Aw3");
  if (existing) return existing.id;
  const created = await createStaff({ name: "Aw3", wechat_nickname: "Aw3" });
  return created.id;
}

/** P0-FE-MAIN-2A：创建测试线索并分配给销售，返回 lead_id */
async function createTestLeadAndAssign(staffId: number): Promise<number> {
  const ts = Date.now();
  const lead = await createLead({
    source: "test",
    customer_name: "测试客户-" + ts,
    content: "[P0-FE-MAIN-2A 自动创建的测试线索]",
    source_id: "test_" + ts,
  });
  await assignLead(lead.id, staffId);
  return lead.id;
}

// ========== 工具函数 ==========

function taskStatusLabel(status: string): string {
  return TASK_STATUS_LABELS[status] || status;
}

function taskStatusTone(status: string): string {
  return TASK_STATUS_TONES[status] || "bg-slate-100 text-slate-700";
}

const TASK_FAILURE_STATUSES = new Set(["failed", "blocked", "timeout"]);

function shouldShowFailureReason(task: WechatTask): boolean {
  return Boolean(task.failure_stage && TASK_FAILURE_STATUSES.has(task.status));
}

function taskStageLabel(task: WechatTask): string {
  return shouldShowFailureReason(task) ? "失败原因" : "系统提示";
}

function taskStageTone(task: WechatTask): string {
  return shouldShowFailureReason(task) ? "text-amber-700" : "text-[#64748b]";
}

function formatTime(value: string | null): string {
  return formatDateTimeLocal(value, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function truncate(text: string | null, maxLen: number): string {
  if (!text) return "-";
  return text.length > maxLen ? text.slice(0, maxLen) + "..." : text;
}

/** 从 raw_result JSON 字符串中提取简要摘要 */
function rawResultSummary(raw: string | null): string {
  if (!raw) return "（raw_result 为空）";
  try {
    const obj = JSON.parse(raw);
    const parts: string[] = [];
    if (obj.failure_stage) parts.push(`失败阶段: ${obj.failure_stage}`);
    if (obj.action?.pasted) parts.push("已粘贴");
    if (obj.action?.sent) parts.push("已发送");
    if (obj.write_back?.ok) parts.push("回写成功");
    if (obj.message) parts.push(String(obj.message).slice(0, 60));
    return parts.length > 0 ? parts.join(" · ") : JSON.stringify(obj).slice(0, 100);
  } catch {
    return raw.slice(0, 100);
  }
}

// ========== 状态指示组件 ==========

function BooleanPill({ value, label }: { value?: boolean | null; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-semibold ${
        value ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
      }`}
    >
      {value ? <CheckCircle2Icon size={10} /> : <XCircleIcon size={10} />}
      {label}: {value ? "✓" : "✗"}
    </span>
  );
}

// ========== 主组件 ==========

export default function WechatTaskPanel() {
  const [tasks, setTasks] = useState<WechatTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<number | null>(null);

  // P0-FE-MAIN-1：创建任务并执行的状态
  const [creating, setCreating] = useState(false);
  const [latestTaskId, setLatestTaskId] = useState<number | null>(null);
  const [latestTask, setLatestTask] = useState<WechatTask | null>(null);
  const [pollResult, setPollResult] = useState<PollAndExecuteResponse | null>(null);
  const [pollingTask, setPollingTask] = useState(false);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // P0-FE-MAIN-2: 通知状态
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [notifLoading, setNotifLoading] = useState(false);

  // P0-REPLY-2：检测回复状态
  const [detecting, setDetecting] = useState(false);
  const [detectResult, setDetectResult] = useState<AgentReplyDetectResponse | null>(null);
  const [checks, setChecks] = useState<CheckRecord[]>([]);

  // P1-AUTO-1D：自动回复检测状态
  const [detectReplyTasks, setDetectReplyTasks] = useState<WechatTask[]>([]);
  const [pollDetectResult, setPollDetectResult] = useState<PollAndDetectResponse | null>(null);
  const [pollDetecting, setPollDetecting] = useState(false);
  const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /** 刷新 pending 任务列表 */
  const refreshTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBrowserPendingWechatTasks({ limit: 50 });
      setTasks(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "任务列表加载失败";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  /** 刷新通知记录（P0-FE-MAIN-2） */
  const refreshNotifications = useCallback(async () => {
    setNotifLoading(true);
    try {
      const resp = await fetchNotificationRecords({ limit: 10 });
      setNotifications(resp.records);
    } catch {
      // 不报 toast，静默失败
    } finally {
      setNotifLoading(false);
    }
  }, []);

  /** 刷新检测记录（P0-REPLY-2，拉取所有状态） */
  const refreshChecks = useCallback(async () => {
    try {
      const data = await fetchChecks();
      setChecks(data);
    } catch {
      // 静默失败
    }
  }, []);

  /** P1-AUTO-1D：刷新 detect_reply 任务列表 */
  const refreshDetectReplyTasks = useCallback(async () => {
    try {
      const data = await fetchBrowserPendingWechatTasks({ task_type: "detect_reply", limit: 10 });
      setDetectReplyTasks(data);
    } catch {
      // 静默失败
    }
  }, []);

  /** P1-AUTO-1D：统一刷新所有自动检测相关数据 */
  const refreshAutoDetectData = useCallback(async () => {
    await Promise.all([
      refreshDetectReplyTasks(),
      refreshNotifications(),
      refreshChecks(),
    ]);
  }, [refreshDetectReplyTasks, refreshNotifications, refreshChecks]);

  useEffect(() => {
    refreshTasks();
    refreshAutoDetectData();
  }, [refreshTasks, refreshAutoDetectData]);

  /** P1-AUTO-1D：自动刷新定时器（每 10 秒） */
  useEffect(() => {
    if (autoRefreshRef.current) {
      clearInterval(autoRefreshRef.current);
    }
    autoRefreshRef.current = setInterval(() => {
      refreshAutoDetectData();
    }, 10000);
    return () => {
      if (autoRefreshRef.current) {
        clearInterval(autoRefreshRef.current);
        autoRefreshRef.current = null;
      }
    };
  }, [refreshAutoDetectData]);

  /** 清理轮询定时器 */
  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => clearPollTimer();
  }, [clearPollTimer]);

  /** 轮询任务状态直到不再是 pending/running */
  const startPollingTask = useCallback(
    (taskId: number) => {
      clearPollTimer();
      setPollingTask(true);
      let attempts = 0;
      const maxAttempts = 10;

      const poll = async () => {
        attempts++;
        try {
          const task = await fetchWechatTask(taskId);
          setLatestTask(task);
          if (task.status !== "pending" && task.status !== "running") {
            // 任务已结束，停止轮询
            clearPollTimer();
            setPollingTask(false);
            // 刷新列表和通知
            await refreshTasks();
            refreshNotifications();
            if (task.status === "pasted") {
              toast.success(`任务 #${taskId} 已粘贴成功`);
            } else if (task.status === "failed" || task.status === "blocked") {
              toast.warning(`任务 #${taskId} ${taskStatusLabel(task.status)}: ${task.failure_stage || "未知原因"}`);
            }
            return;
          }
          if (attempts >= maxAttempts) {
            clearPollTimer();
            setPollingTask(false);
            toast.info("轮询超时，任务可能仍在执行。请手动刷新。");
          }
        } catch {
          if (attempts >= maxAttempts) {
            clearPollTimer();
            setPollingTask(false);
          }
        }
      };

      // 立即执行一次
      poll();
      // 每 2 秒轮询
      pollTimerRef.current = setInterval(poll, 2000);
    },
    [clearPollTimer, refreshTasks, refreshNotifications],
  );

  /** 创建测试任务并触发 Local Agent 执行 */
  const handleCreateAndExecute = async () => {
    setCreating(true);
    setLatestTask(null);
    setLatestTaskId(null);
    setPollResult(null);
    clearPollTimer();

    let taskId: number | null = null;

    // P0-FE-MAIN-2A：先确保 Aw3 销售 + 创建测试线索
    let staffId: number | null = null;
    let leadId: number | null = null;

    try {
      staffId = await ensureAw3Staff();
      leadId = await createTestLeadAndAssign(staffId);
      toast.info(`已准备测试数据：staff #${staffId}，lead #${leadId}`);
    } catch (err) {
      toast.warning(`测试数据准备失败（将使用无关联数据创建任务）：${err instanceof Error ? err.message : "未知错误"}`);
    }

    try {
      // 1. 在主系统创建 paste_only Aw3 测试任务（带 lead_id / staff_id）
      const created = await createWechatTask({
        task_type: "notify_sales",
        target_nickname: "Aw3",
        message: "[P0-FE-MAIN-2A 测试] paste_only 任务，lead #" + (leadId ?? "?") + " → staff #" + (staffId ?? "?"),
        mode: "paste_only",
        lead_id: leadId ?? undefined,
        staff_id: staffId ?? undefined,
      });
      taskId = created.id;
      setLatestTaskId(taskId);
      setLatestTask(created);
      toast.info(`已创建任务 #${taskId}（lead #${leadId} → staff #${staffId}），正在触发 Local Agent...`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建任务失败");
      setCreating(false);
      return;
    }

    try {
      // 2. 调用 Local Agent 19000 poll-and-execute
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 180000);

      // P1-AUTO-1D-FIX2：传入刚创建的 task_id，避免被旧 pending 队列阻塞
      const result = await pollAndExecuteWechatTask(taskId, controller.signal);
      window.clearTimeout(timeout);
      setPollResult(result);

      if (result.success) {
        toast.success("Local Agent 执行完成");
      } else {
        toast.warning(`Local Agent 执行结果: ${result.failure_stage || result.message || "未成功"}`);
      }
    } catch (err) {
      if ((err as Error)?.name === "AbortError") {
        toast.error("Local Agent 执行超时（180 秒）");
      } else {
        toast.error("Local Agent 未启动或请求失败，请确认本机已启动小高AI微信助手");
      }
      setPollResult({
        success: false,
        failure_stage: "agent_request_failed",
        message: err instanceof Error ? err.message : "请求失败",
      });
    }

    // 3. 开始轮询任务状态
    if (taskId) {
      startPollingTask(taskId);
    }

    setCreating(false);
    // 同时刷新列表和通知
    refreshTasks();
    refreshNotifications();
  };

  /** P0-REPLY-2：检测销售回复 */
  const handleDetectReply = async () => {
    if (!latestTask?.lead_id || !latestTask?.staff_id) {
      toast.warning("当前任务缺少 lead_id 或 staff_id，无法检测回复");
      return;
    }

    setDetecting(true);
    setDetectResult(null);

    try {
      const result = await detectReply({
        lead_id: latestTask.lead_id,
        staff_id: latestTask.staff_id,
        task_id: latestTask.id,
        target_nickname: "Aw3",
      });
      setDetectResult(result);

      if (result.success) {
        if (result.detected_status === "replied") {
          toast.success(`检测到有效回复: ${result.matched_reply || ""}`);
        } else if (result.detected_status === "manual_review") {
          toast.info("候选消息命中关键词但发送方无法确认，需人工复核");
        } else {
          toast.info(`检测结果: ${DETECT_STATUS_LABELS[result.detected_status] || result.detected_status}`);
        }
      } else {
        toast.warning(`检测失败: ${result.failure_stage || result.message || "未知原因"}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "请求失败";
      toast.error("检测回复失败: " + msg);
      setDetectResult({
        success: false,
        detected_status: "failed",
        matched_reply: null,
        messages_read: 0,
        messages: [],
        failure_stage: "agent_request_failed",
        write_back: null,
        message: msg,
        raw_result: null,
      });
    }

    // 刷新 checks / notifications / task
    refreshChecks();
    refreshNotifications();
    if (latestTaskId) {
      try {
        const updated = await fetchWechatTask(latestTaskId);
        setLatestTask(updated);
      } catch {
        // 静默
      }
    }

    setDetecting(false);
  };

  /** P1-AUTO-1D / FIX3：执行一次自动检测（poll-and-detect）
   *  FIX3：如果当前面板展示了 pending detect_reply task，传其 task.id 给 Agent，
   *  避免 Agent 优先消费旧 pending 队列。
   */
  const handlePollAndDetect = async () => {
    setPollDetecting(true);
    setPollDetectResult(null);

    // P1-AUTO-1D-FIX3：取当前面板第一条 pending detect_reply task 的 id
    const currentDetectTaskId = detectReplyTasks.length > 0 ? detectReplyTasks[0].id : null;

    try {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 120000);

      const result = await pollAndDetectReply(20, controller.signal, currentDetectTaskId);
      window.clearTimeout(timeout);
      setPollDetectResult(result);

      if (result.success && result.task) {
        if (result.detect_result?.detected_status === "replied") {
          toast.success(`检测到销售回复: ${result.detect_result.matched_reply || ""}`);
        } else if (result.message === "无待检测任务") {
          toast.info("无待检测的回复任务");
        } else {
          toast.info(`检测结果: ${result.detect_result?.detected_status || result.message}`);
        }
      } else {
        toast.warning(`自动检测: ${result.failure_stage || result.message || "未成功"}`);
      }
    } catch (err) {
      if ((err as Error)?.name === "AbortError") {
        toast.error("自动检测超时（120 秒）");
      } else {
        toast.error("Local Agent 未启动或请求失败，请确认本机已启动小高AI微信助手");
      }
      setPollDetectResult({
        success: false,
        message: err instanceof Error ? err.message : "请求失败",
        task: null,
        failure_stage: "agent_request_failed",
      });
    }

    // 刷新所有自动检测相关数据
    await refreshAutoDetectData();
    setPollDetecting(false);
  };

  return (
    <div className="rounded-xl border border-[#e4e8f0] bg-white p-4">
      {/* 面板标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-amber-50 text-amber-600">
            <FileTextIcon size={16} />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[#1a1f2e]">微信任务队列</h3>
            <p className="text-[11px] text-[#8b95a6]">
              主系统 9000 创建任务 → Local Agent 19000 拉取执行 → 回写结果
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              refreshTasks();
              toast.info("任务列表已刷新");
            }}
            disabled={loading}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] transition-colors hover:bg-white disabled:opacity-50"
          >
            {loading ? (
              <Loader2Icon size={14} className="animate-spin" />
            ) : (
              <RefreshCwIcon size={14} />
            )}
            刷新
          </button>

          {/* P0-FE-MAIN-1：创建测试任务并执行 */}
          <button
            onClick={handleCreateAndExecute}
            disabled={creating || pollingTask}
            className="flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-3 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:opacity-50"
          >
            {creating || pollingTask ? (
              <Loader2Icon size={14} className="animate-spin" />
            ) : (
              <PlayIcon size={14} />
            )}
            {creating ? "创建中..." : pollingTask ? "执行中..." : "创建测试任务并执行"}
          </button>

          {/* P0-REPLY-2：检测销售回复 */}
          {latestTask && latestTask.lead_id && latestTask.staff_id && (
            <button
              onClick={handleDetectReply}
              disabled={detecting}
              className="flex h-9 items-center gap-1.5 rounded-xl bg-violet-600 px-3 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(91,33,182,0.22)] disabled:opacity-50"
            >
              {detecting ? (
                <Loader2Icon size={14} className="animate-spin" />
              ) : (
                <EyeIcon size={14} />
              )}
              {detecting ? "检测中..." : "检测销售回复"}
            </button>
          )}
        </div>
      </div>

      {/* 安全提示 */}
      <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-700">
        <InfoIcon size={14} className="mt-0.5 shrink-0" />
        <div>
          <span className="font-semibold">安全提示：</span>
          测试面板用于创建本机 Agent 任务并查看回写结果；真实派单发送由任务 mode 与安全门禁共同决定。
        </div>
      </div>

      {/* P0-REPLY-2：检测结果面板 */}
      {detectResult && (
        <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50 p-3">
          <div className="flex items-center gap-2 text-xs font-bold text-violet-800">
            <EyeIcon size={14} />
            检测销售回复结果
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
            <div className="rounded-lg bg-white px-2 py-1.5 text-center">
              <BooleanPill value={detectResult.success} label="Agent 执行" />
            </div>
            <div className="rounded-lg bg-white px-2 py-1.5 text-center">
              <BooleanPill value={detectResult.write_back?.ok} label="主系统回写" />
            </div>
            <div className="rounded-lg bg-white px-2 py-1.5 text-center">
              <span className="text-[10px] text-[#64748b]">消息数: </span>
              <span className="font-semibold text-[#334155]">{detectResult.messages_read}</span>
            </div>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] text-[#64748b]">
            <div>
              detected_status:{" "}
              <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${DETECT_STATUS_TONES[detectResult.detected_status] || "bg-slate-100 text-slate-700"}`}>
                {DETECT_STATUS_LABELS[detectResult.detected_status] || detectResult.detected_status}
              </span>
            </div>
            <div>
              matched_reply: <span className="font-semibold text-[#334155]">{detectResult.matched_reply || "-"}</span>
            </div>
            <div>
              failure_stage: <span className="font-semibold text-[#334155]">{detectResult.failure_stage || "-"}</span>
            </div>
            <div>
              message: <span className="font-semibold text-[#334155]">{truncate(detectResult.message, 60)}</span>
            </div>
          </div>
          {/* 检测到的消息列表（最多展示 5 条） */}
          {detectResult.messages.length > 0 && (
            <div className="mt-2 space-y-1">
              <div className="text-[10px] font-semibold text-violet-700">读取到的消息（最近 {Math.min(detectResult.messages.length, 5)} 条）</div>
              {detectResult.messages.slice(-5).map((msg, idx) => (
                <div key={idx} className="rounded border border-[#e4e8f0] bg-white px-2 py-1 text-[10px]">
                  <span className="font-semibold text-[#334155]">[{msg.sender}]</span>{" "}
                  <span className="text-[#64748b]">{truncate(msg.content, 60)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* P0-FE-MAIN-1：最新任务执行结果面板 */}
      {(latestTask || pollResult) && (
        <div className="mt-3 rounded-lg border border-[#e4e8f0] bg-[#f8fafc] p-3">
          <div className="flex items-center gap-2 text-xs font-bold text-[#1a1f2e]">
            <PlayIcon size={14} className="text-[#2563eb]" />
            最新执行结果
          </div>

          {/* poll-and-execute 原始返回 */}
          {pollResult && (
            <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
              <div className="rounded-lg bg-white px-2 py-1.5 text-center">
                <BooleanPill value={pollResult.success} label="Agent 执行" />
              </div>
              <div className="rounded-lg bg-white px-2 py-1.5 text-center">
                <BooleanPill value={pollResult.action?.pasted} label="已粘贴" />
              </div>
              <div className="rounded-lg bg-white px-2 py-1.5 text-center">
                <BooleanPill value={pollResult.write_back?.ok} label="回写成功" />
              </div>
            </div>
          )}

          {pollResult && (
            <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] text-[#64748b]">
              <div>
                failure_stage: <span className="font-semibold text-[#334155]">{pollResult.failure_stage || "-"}</span>
              </div>
              <div>
                message: <span className="font-semibold text-[#334155]">{truncate(pollResult.message || null, 60)}</span>
              </div>
              {pollResult.agent_machine && (
                <div>
                  agent: <span className="font-semibold text-[#334155]">{pollResult.agent_machine.hostname}</span>
                </div>
              )}
              {pollResult.task && (
                <div>
                  拉取任务: <span className="font-semibold text-[#334155]">#{pollResult.task.id} → {pollResult.task.target_nickname}</span>
                </div>
              )}
            </div>
          )}

          {/* 主系统任务状态（轮询结果） */}
          {latestTask && (
            <div className="mt-3 border-t border-[#e4e8f0] pt-2">
              <div className="flex items-center gap-2 text-[11px]">
                <span
                  className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-semibold ${taskStatusTone(latestTask.status)}`}
                >
                  {taskStatusLabel(latestTask.status)}
                </span>
                <span className="font-semibold text-[#334155]">任务 #{latestTask.id}</span>
                <span className="text-[#64748b]">
                  → {latestTask.target_nickname || "-"} · {MODE_LABELS[latestTask.mode] || latestTask.mode}
                </span>
                {pollingTask && (
                  <span className="flex items-center gap-1 text-blue-600">
                    <Loader2Icon size={10} className="animate-spin" />
                    轮询中...
                  </span>
                )}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] text-[#64748b]">
                <div>
                  {taskStageLabel(latestTask)}:{" "}
                  <span className={`font-semibold ${taskStageTone(latestTask)}`}>
                    {latestTask.failure_stage || "-"}
                  </span>
                </div>
                <div>
                  agent: <span className="font-semibold text-[#334155]">{latestTask.agent_hostname || "-"} (PID {latestTask.agent_pid ?? "-"})</span>
                </div>
                <div>
                  pasted_at: <span className="font-semibold text-[#334155]">{formatTime(latestTask.pasted_at)}</span>
                </div>
                <div>
                  sent_at: <span className="font-semibold text-[#334155]">{latestTask.sent_at ? formatTime(latestTask.sent_at) : "null（禁止发送）"}</span>
                </div>
                <div className="col-span-2">
                  raw_result: <span className="font-semibold text-[#334155]">{rawResultSummary(latestTask.raw_result)}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* P0-FE-MAIN-2: 最新线索通知状态（含匹配高亮） */}
      <div className="mt-3 rounded-lg border border-[#e4e8f0] bg-white p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="grid h-6 w-6 place-items-center rounded bg-violet-50 text-violet-600">
              <FileTextIcon size={13} />
            </div>
            <span className="text-xs font-bold text-[#1a1f2e]">最新线索通知状态</span>
            <span className="text-[10px] text-[#8b95a6]">最近 {notifications.length} 条</span>
            {latestTask && (() => {
              const matched = notifications.find(
                (n) => n.lead_id === latestTask!.lead_id && n.staff_id === latestTask!.staff_id,
              );
              return matched
                ? <span className="text-[10px] font-semibold text-emerald-600">已匹配通知 #{matched.id}</span>
                : latestTask.lead_id
                  ? <span className="text-[10px] text-amber-600">未找到当前任务对应通知（回写后自动出现）</span>
                  : null;
            })()}
          </div>
          <button
            onClick={() => { refreshNotifications(); toast.info("通知状态已刷新"); }}
            disabled={notifLoading}
            className="flex h-7 items-center gap-1 rounded-lg border border-[#e4e8f0] bg-[#f8fafc] px-2 text-[10px] font-semibold text-[#374151] hover:bg-white disabled:opacity-50"
          >
            {notifLoading ? <Loader2Icon size={10} className="animate-spin" /> : <RefreshCwIcon size={10} />}
            刷新通知
          </button>
        </div>

        {/* 当前任务匹配的通知详情 */}
        {latestTask && (() => {
          const matched = notifications.find(
            (n) => n.lead_id === latestTask!.lead_id && n.staff_id === latestTask!.staff_id,
          );
          if (!matched) return null;
          return (
            <div className="mt-2 rounded-lg border-2 border-emerald-200 bg-emerald-50 px-3 py-2">
              <div className="text-[11px] font-bold text-emerald-800">当前任务匹配的通知</div>
              <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px]">
                <div>通知 ID: <span className="font-semibold">#{matched.id}</span></div>
                <div>send_status: <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${SEND_STATUS_TONES[matched.send_status] || "bg-slate-100 text-slate-700"}`}>{SEND_STATUS_LABELS[matched.send_status] || matched.send_status}</span></div>
                <div>lead_id: <span className="font-semibold">#{matched.lead_id}</span></div>
                <div>staff: <span className="font-semibold">{matched.staff_name || "#" + matched.staff_id}</span></div>
                <div>send_mode: <span className="font-semibold">{matched.send_mode || "-"}</span></div>
                <div>sent_at: <span className="font-semibold">{matched.sent_at ? formatTime(matched.sent_at) : "null（未发送）"}</span></div>
                {matched.error_message && (
                  <div className="col-span-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-red-600">
                    错误: {matched.error_message}
                  </div>
                )}
                {matched.notification_text && (
                  <div className="col-span-2 text-[#64748b] truncate">
                    通知内容: {matched.notification_text}
                  </div>
                )}
              </div>
            </div>
          );
        })()}

        {notifications.length === 0 ? (
          <div className="mt-2 text-[11px] text-[#8b95a6]">暂无通知记录，创建测试任务并执行后，回写成功会自动出现通知</div>
        ) : (
          <div className="mt-2 space-y-1.5">
            {notifications.slice(0, 5).map((n) => {
              const isMatched = latestTask && latestTask.lead_id === n.lead_id && latestTask.staff_id === n.staff_id;
              return (
                <div key={n.id} className={`rounded-lg border px-3 py-2 ${isMatched ? "border-emerald-300 bg-emerald-50/50" : "border-[#f0f2f7] bg-[#f8fafc]"}`}>
                  <div className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-[#1a1f2e]">通知 #{n.id}</span>
                      {isMatched && <span className="text-[9px] font-semibold text-emerald-600">当前任务</span>}
                      <span className="text-[#8b95a6]">
                        线索 #{n.lead_id} &middot; {n.customer_name || "-"} &middot; 销售: {n.staff_name || "#" + n.staff_id}
                      </span>
                    </div>
                    <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${SEND_STATUS_TONES[n.send_status] || "bg-slate-100 text-slate-700"}`}>
                      {SEND_STATUS_LABELS[n.send_status] || n.send_status}
                    </span>
                  </div>
                  <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] text-[#64748b]">
                    <div>send_mode: <span className="font-medium text-[#334155]">{n.send_mode || "-"}</span></div>
                    <div>sent_at: <span className="font-medium text-[#334155]">{n.sent_at ? formatTime(n.sent_at) : "null（未发送）"}</span></div>
                    <div>created_at: <span className="font-medium text-[#334155]">{formatTime(n.created_at)}</span></div>
                    <div>chat_title: <span className="font-medium text-[#334155]">{n.chat_title || "-"}</span></div>
                  </div>
                  {n.error_message && (
                    <div className="mt-1 rounded border border-red-200 bg-red-50 px-2 py-1 text-[10px] text-red-600">
                      错误: {n.error_message}
                    </div>
                  )}
                  {n.notification_text && (
                    <div className="mt-1 text-[10px] text-[#8b95a6] truncate">
                      通知内容: {n.notification_text}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ========== P1-AUTO-1D：自动回复检测面板 ========== */}
      <div className="mt-3 rounded-lg border border-[#e4e8f0] bg-white p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="grid h-6 w-6 place-items-center rounded bg-teal-50 text-teal-600">
              <EyeIcon size={13} />
            </div>
            <span className="text-xs font-bold text-[#1a1f2e]">自动回复检测</span>
            <span className="text-[10px] text-[#8b95a6]">
              P1-AUTO-1D · 每 10 秒自动刷新
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => { refreshAutoDetectData(); toast.info("检测状态已刷新"); }}
              className="flex h-7 items-center gap-1 rounded-lg border border-[#e4e8f0] bg-[#f8fafc] px-2 text-[10px] font-semibold text-[#374151] hover:bg-white"
            >
              <RefreshCwIcon size={10} />
              刷新状态
            </button>
            <button
              onClick={handlePollAndDetect}
              disabled={pollDetecting}
              className="flex h-7 items-center gap-1 rounded-lg bg-teal-600 px-2 text-[10px] font-semibold text-white disabled:opacity-50"
            >
              {pollDetecting ? <Loader2Icon size={10} className="animate-spin" /> : <EyeIcon size={10} />}
              {pollDetecting
                ? "检测中..."
                : detectReplyTasks.length > 0
                  ? `执行当前检测任务 #${detectReplyTasks[0].id}`
                  : "执行一次自动检测"}
            </button>
          </div>
        </div>

        {/* 安全提示 */}
        <div className="mt-2 flex items-start gap-1.5 text-[10px] text-teal-700">
          <InfoIcon size={11} className="mt-0.5 shrink-0" />
          此操作只读取微信消息，不粘贴、不发送。调用 19000 /agent/tasks/poll-and-detect。
        </div>

        {/* poll-and-detect 执行结果 */}
        {pollDetectResult && (
          <div className={`mt-2 rounded-lg border p-2 ${pollDetectResult.success ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
            <div className="text-[11px] font-bold text-[#1a1f2e]">最近一次检测结果</div>
            <div className="mt-1 grid grid-cols-3 gap-2 text-[10px]">
              <div className="rounded bg-white px-2 py-1 text-center">
                <BooleanPill value={pollDetectResult.success} label="执行" />
              </div>
              <div className="rounded bg-white px-2 py-1 text-center">
                <BooleanPill value={pollDetectResult.action?.pasted} label="pasted" />
              </div>
              <div className="rounded bg-white px-2 py-1 text-center">
                <BooleanPill value={pollDetectResult.action?.sent} label="sent" />
              </div>
            </div>
            <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] text-[#64748b]">
              <div>
                message: <span className="font-semibold text-[#334155]">{pollDetectResult.message}</span>
              </div>
              <div>
                failure_stage: <span className="font-semibold text-[#334155]">{pollDetectResult.failure_stage || "-"}</span>
              </div>
              {pollDetectResult.task && (
                <>
                  <div>
                    任务: <span className="font-semibold text-[#334155]">#{pollDetectResult.task.id} · {pollDetectResult.task.task_type}</span>
                  </div>
                  <div>
                    目标: <span className="font-semibold text-[#334155]">{pollDetectResult.task.target_nickname || "-"} · mode={pollDetectResult.task.mode}</span>
                  </div>
                </>
              )}
            </div>
            {pollDetectResult.detect_result && (
              <div className="mt-1.5 border-t border-[#e4e8f0] pt-1.5">
                <div className="text-[10px] font-semibold text-teal-700">detect_result 详情</div>
                <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] text-[#64748b]">
                  <div>
                    detected_status:{" "}
                    <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${DETECT_STATUS_TONES[pollDetectResult.detect_result.detected_status || ""] || "bg-slate-100 text-slate-700"}`}>
                      {DETECT_STATUS_LABELS[pollDetectResult.detect_result.detected_status || ""] || pollDetectResult.detect_result.detected_status || "-"}
                    </span>
                  </div>
                  <div>
                    matched_reply: <span className="font-semibold text-[#334155]">{pollDetectResult.detect_result.matched_reply || "-"}</span>
                  </div>
                  <div>
                    messages_read: <span className="font-semibold text-[#334155]">{pollDetectResult.detect_result.messages_read}</span>
                  </div>
                  <div>
                    write_back: <BooleanPill value={pollDetectResult.detect_result.write_back?.ok} label="ok" />
                  </div>
                  {pollDetectResult.detect_result.failure_stage && (
                    <div className="col-span-2 text-red-600">
                      failure_stage: {pollDetectResult.detect_result.failure_stage}
                    </div>
                  )}
                </div>
                {/* raw_result 可展开 */}
                {pollDetectResult.detect_result.raw_result && (
                  <details className="mt-1.5">
                    <summary className="cursor-pointer text-[10px] font-semibold text-[#8b95a6]">
                      raw_result（点击展开）
                    </summary>
                    <pre className="mt-1 max-h-32 overflow-auto rounded bg-white p-1.5 text-[9px] font-mono text-[#475569]">
                      {JSON.stringify(pollDetectResult.detect_result.raw_result, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            )}
          </div>
        )}

        {/* detect_reply 任务列表 */}
        <div className="mt-2">
          <div className="text-[11px] font-semibold text-[#334155]">
            detect_reply 任务
            <span className="ml-1 text-[10px] font-normal text-[#8b95a6]">
              （{detectReplyTasks.length} 条 pending）
            </span>
          </div>
          {detectReplyTasks.length === 0 ? (
            <div className="mt-1 text-[10px] text-[#8b95a6]">暂无待检测回复任务。系统产生 detect_reply 任务后，会自动出现在此列表。</div>
          ) : (
            <div className="mt-1 space-y-1">
              {detectReplyTasks.map((t) => {
                let rawParsed: Record<string, unknown> | null = null;
                try { rawParsed = t.raw_result ? JSON.parse(t.raw_result) : null; } catch { /* 忽略 */ }
                return (
                  <div key={t.id} className="rounded-lg border border-[#f0f2f7] bg-[#f8fafc] px-3 py-2">
                    <div className="flex items-center justify-between text-[10px]">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-[#1a1f2e]">#{t.id}</span>
                        <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${taskStatusTone(t.status)}`}>
                          {taskStatusLabel(t.status)}
                        </span>
                        <span className="text-[#8b95a6]">
                          目标: {t.target_nickname || "-"} · mode: {t.mode}
                        </span>
                      </div>
                      <span className="text-[#8b95a6]">{formatTime(t.updated_at)}</span>
                    </div>
                    <div className="mt-1 grid grid-cols-3 gap-x-4 gap-y-0.5 text-[10px] text-[#64748b]">
                      <div>lead: <span className="font-semibold">#{t.lead_id ?? "-"}</span></div>
                      <div>staff: <span className="font-semibold">#{t.staff_id ?? "-"}</span></div>
                      <div>check: <span className="font-semibold">#{t.reply_check_id ?? "-"}</span></div>
                    </div>
                    {/* 安全字段展示 */}
                    <div className="mt-1 flex flex-wrap gap-1">
                      <BooleanPill value={false} label="sent" />
                      <BooleanPill value={false} label="pasted" />
                      <span className="inline-flex items-center rounded-md bg-teal-50 px-1.5 py-0.5 text-[10px] font-semibold text-teal-700">
                        read_only
                      </span>
                      <span className="inline-flex items-center rounded-md bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">
                        Aw3
                      </span>
                    </div>
                    {t.failure_stage && (
                      <div className={`mt-1 text-[10px] ${
                        shouldShowFailureReason(t) ? "text-red-600" : "text-slate-500"
                      }`}>
                        {taskStageLabel(t)}: {t.failure_stage}
                      </div>
                    )}
                    {/* raw_result 展示 */}
                    {rawParsed && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-[10px] text-[#8b95a6]">
                          raw_result（点击展开）
                        </summary>
                        <pre className="mt-0.5 max-h-24 overflow-auto rounded bg-white p-1 text-[9px] font-mono text-[#475569]">
                          {JSON.stringify(rawParsed, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 最新 check 状态 */}
        {checks.length > 0 && (
          <div className="mt-2">
            <div className="text-[11px] font-semibold text-[#334155]">
              最新检测记录（checks）
              <span className="ml-1 text-[10px] font-normal text-[#8b95a6]">
                （{checks.length} 条）
              </span>
            </div>
            <div className="mt-1 space-y-1">
              {checks.slice(0, 5).map((c) => (
                <div key={c.id} className="rounded-lg border border-[#f0f2f7] bg-[#f8fafc] px-3 py-1.5">
                  <div className="flex items-center justify-between text-[10px]">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-[#1a1f2e]">check #{c.id}</span>
                      <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${taskStatusTone(c.check_status)}`}>
                        {taskStatusLabel(c.check_status)}
                      </span>
                      <span className="text-[#8b95a6]">
                        lead #{c.lead_id} · staff #{c.staff_id}
                      </span>
                    </div>
                    <span className="text-[#8b95a6]">{formatTime(c.checked_at)}</span>
                  </div>
                  {c.reply_content && (
                    <div className="mt-0.5 text-[10px] text-[#334155]">
                      回复内容: <span className="font-semibold">{truncate(c.reply_content, 60)}</span>
                    </div>
                  )}
                  {c.effectiveness_reason && (
                    <div className="text-[10px] text-[#8b95a6] truncate">
                      原因: {truncate(c.effectiveness_reason, 80)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 统计摘要 */}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <div className="rounded-lg bg-[#f8fafc] px-3 py-2 text-center">
          <div className="text-lg font-bold text-[#1a1f2e]">{tasks.length}</div>
          <div className="text-[10px] text-[#8b95a6]">待执行任务</div>
        </div>
        <div className="rounded-lg bg-amber-50 px-3 py-2 text-center">
          <div className="text-lg font-bold text-amber-700">
            {tasks.filter((t) => t.status === "pending").length}
          </div>
          <div className="text-[10px] text-amber-600">pending</div>
        </div>
        <div className="rounded-lg bg-sky-50 px-3 py-2 text-center">
          <div className="text-lg font-bold text-sky-700">
            {tasks.filter((t) => t.status === "pasted").length}
          </div>
          <div className="text-[10px] text-sky-600">pasted</div>
        </div>
      </div>

      {/* 任务列表 */}
      <div className="mt-4">
        {loading ? (
          <div className="rounded-xl border border-[#e4e8f0] bg-white px-4 py-8 text-center text-xs text-[#8b95a6]">
            <Loader2Icon size={16} className="mx-auto mb-2 animate-spin text-[#94a3b8]" />
            加载中...
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-center text-xs text-red-600">
            {error}
            <button onClick={() => void refreshTasks()} className="ml-2 font-semibold text-[#2563eb] underline">重试</button>
          </div>
        ) : tasks.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[#d9e0ea] bg-white/60 px-4 py-6 text-center text-xs text-[#8b95a6]">
            暂无待执行任务。点击上方「创建测试任务并执行」以创建 Aw3 paste_only 测试任务。
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map((task) => {
              const expanded = expandedTaskId === task.id;
              return (
                <div
                  key={task.id}
                  className="rounded-xl border border-[#e4e8f0] bg-white px-4 py-3 transition-colors hover:border-[#cbd5e1]"
                >
                  {/* 任务头部 */}
                  <button
                    onClick={() => setExpandedTaskId(expanded ? null : task.id)}
                    className="flex w-full items-start justify-between gap-4 text-left"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-xs font-bold text-[#1a1f2e]">
                        <span>任务 #{task.id}</span>
                        <span className="text-[10px] font-normal text-[#8b95a6]">
                          {task.target_nickname ? `→ ${task.target_nickname}` : ""}
                          {task.lead_id ? ` · 线索 #${task.lead_id}` : ""}
                          {task.staff_id ? ` · 销售 #${task.staff_id}` : ""}
                        </span>
                      </div>
                      <div className="mt-1 text-xs text-[#64748b]">
                        {truncate(task.message, 80)}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1.5">
                      <span
                        className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ${taskStatusTone(task.status)}`}
                      >
                        {taskStatusLabel(task.status)}
                      </span>
                      <div className="flex items-center gap-1 text-[10px] text-[#8b95a6]">
                        <ClockIcon size={10} />
                        {formatTime(task.created_at)}
                      </div>
                    </div>
                  </button>

                  {/* 展开详情 */}
                  {expanded && (
                    <div className="mt-3 border-t border-[#f0f2f7] pt-3">
                      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[11px]">
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">任务类型</span>
                          <span className="font-semibold text-[#374151]">{task.task_type}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">执行模式</span>
                          <span className="font-semibold text-[#374151]">
                            {MODE_LABELS[task.mode] || task.mode}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">目标联系人</span>
                          <span className="font-semibold text-[#374151]">
                            {task.target_nickname || "-"}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">线索</span>
                          <span className="font-semibold text-[#374151]">
                            {task.lead_id ?? "-"}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">销售微信</span>
                          <span className="font-semibold text-[#374151]">
                            {task.staff_id ?? "-"}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">状态</span>
                          <span
                            className={`font-semibold ${
                              task.status === "pending"
                                ? "text-amber-600"
                                : task.status === "pasted"
                                  ? "text-sky-600"
                                  : task.status === "failed"
                                    ? "text-red-600"
                                    : "text-[#374151]"
                            }`}
                          >
                            {taskStatusLabel(task.status)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">{taskStageLabel(task)}</span>
                          <span className={`font-semibold ${taskStageTone(task)}`}>
                            {task.failure_stage || "-"}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">执行电脑</span>
                          <span className="font-semibold text-[#374151]">
                            {task.agent_hostname || "-"}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">执行时间</span>
                          <span className="font-semibold text-[#374151]">
                            {formatTime(task.pasted_at)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">发送时间</span>
                          <span className="font-semibold text-[#374151]">
                            {task.sent_at ? formatTime(task.sent_at) : "未发送"}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">创建时间</span>
                          <span className="font-semibold text-[#374151]">
                            {formatTime(task.created_at)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8b95a6]">更新时间</span>
                          <span className="font-semibold text-[#374151]">
                            {formatTime(task.updated_at)}
                          </span>
                        </div>
                      </div>

                      {/* 消息完整内容 */}
                      {task.message && (
                        <div className="mt-3">
                          <div className="text-[11px] font-semibold text-[#8b95a6]">消息内容</div>
                          <div className="mt-1 rounded-lg bg-[#f8fafc] p-2 text-[11px] text-[#374151] whitespace-pre-wrap break-all">
                            {task.message}
                          </div>
                        </div>
                      )}

                      {task.failure_stage ? (
                        <div className={`mt-3 rounded-lg border px-3 py-2 text-[11px] ${
                          shouldShowFailureReason(task)
                            ? "border-amber-200 bg-amber-50 text-amber-700"
                            : "border-slate-200 bg-slate-50 text-slate-600"
                        }`}>
                          {taskStageLabel(task)}：{task.failure_stage}
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
