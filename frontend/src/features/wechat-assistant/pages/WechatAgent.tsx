import {
  CheckCircle2Icon,
  ClockIcon,
  CopyIcon,
  BanIcon,
  EyeIcon,
  PencilIcon,
  Loader2Icon,
  MessageCircleIcon,
  PauseIcon,
  PlayIcon,
  PowerIcon,
  RefreshCwIcon,
  SearchIcon,
  SendIcon,
  ShieldCheckIcon,
  Trash2Icon,
  UserPlusIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { fetchAgentStatus } from "../../../api/agent";
import { getApiErrorCode, isLocalAgentAuthErrorCode } from "../../../api/client";
import type { AgentStatusData } from "../../../api/types";
import { formatDateTimeLocal } from "../../../lib/datetime";
import {
  LOCAL_AGENT_BASE_URL,
  checkLocalAgentHealth,
  createStaff,
  createWechatTask,
  deleteStaff,
  disableLocalAgentTaskPolling,
  disableStaff,
  enableStaff,
  enableLocalAgentTaskPolling,
  fetchBrowserPendingWechatTasks,
  fetchLocalAgentRuntimeStatus,
  fetchWechatTaskHistory,
  fetchWechatTask,
  fetchStaffList,
  pollAndExecuteWechatTask,
  updateStaff,
} from "../api";
import type {
  LocalAgentRuntimeStatus,
  PollAndExecuteResponse,
  Staff,
  WechatTask,
  WechatTaskHistoryItem,
  WechatTaskRawResultSummary,
} from "../types";
import LocalWechatAgentTestPanel from "../components/LocalWechatAgentTestPanel";

const DEFAULT_TEST_NICKNAME = "Aw3";
const SOURCE_START_COMMAND = "cd E:\\work\\project\\auto_wechat\npython app\\local_agent_main.py --host 127.0.0.1 --port 19000 --server-url http://127.0.0.1:9000";
const EXE_START_COMMAND = 'Start-Process ".\\dist\\local-agent\\小高AI微信助手.exe"';

export type WechatAgentTab = "status" | "config" | "tasks" | "download-test";

const TAB_META: Record<WechatAgentTab, { title: string; description: string }> = {
  status: {
    title: "Local Agent状态",
    description: "查看本机实时连接、接收任务开关和 9000 服务端心跳记录。",
  },
  config: {
    title: "微信配置",
    description: "管理销售微信配置，启用状态会影响后续线索分配。",
  },
  tasks: {
    title: "任务记录",
    description: "查询微信任务历史、执行状态和失败阶段，完整 raw_result 仅在详情中查看。",
  },
  "download-test": {
    title: "下载/测试",
    description: "查看启动说明、复制命令，并使用本机 Agent 测试与诊断工具。",
  },
};

function formatTime(value?: string | null): string {
  return formatDateTimeLocal(value || null);
}

function taskStatusText(status?: string | null): string {
  if (status === "pending") return "待处理";
  if (status === "running") return "执行中";
  if (status === "pasted") return "已粘贴";
  if (status === "sent") return "已发送";
  if (status === "blocked") return "已阻断";
  if (status === "failed") return "失败";
  if (status === "completed") return "已完成";
  return status || "-";
}

function taskStatusClass(status?: string | null): string {
  if (status === "sent" || status === "completed") return "bg-emerald-50 text-emerald-700";
  if (status === "pasted") return "bg-blue-50 text-blue-700";
  if (status === "blocked") return "bg-amber-50 text-amber-700";
  if (status === "failed") return "bg-rose-50 text-rose-700";
  return "bg-slate-100 text-slate-600";
}

function taskTypeText(taskType?: string | null): string {
  if (taskType === "notify_sales") return "通知销售";
  if (taskType === "detect_reply") return "回复检测";
  return taskType || "-";
}

function taskModeText(mode?: string | null): string {
  if (mode === "paste_only") return "仅粘贴";
  if (mode === "single_send") return "单条发送";
  if (mode === "read_only") return "只读检测";
  return mode || "-";
}

function shortText(value?: string | null, max = 42): string {
  const text = (value || "").trim();
  if (!text) return "-";
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function rawSummaryText(summary?: WechatTaskRawResultSummary | null): string {
  if (!summary || Object.keys(summary).length === 0) return "-";
  const parts = [
    typeof summary.contact_verified === "boolean" ? `验证:${summary.contact_verified ? "是" : "否"}` : "",
    typeof summary.sent === "boolean" ? `发送:${summary.sent ? "是" : "否"}` : "",
    summary.write_action ? `动作:${summary.write_action}` : "",
    summary.verify_strategy ? `策略:${summary.verify_strategy}` : "",
    summary.manual_review_reason ? `复核:${summary.manual_review_reason}` : "",
    summary.failure_stage ? `阶段:${summary.failure_stage}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" / ") : "-";
}

function agentOnlineText(status: AgentStatusData | null, localOnline: boolean | null): string {
  if (localOnline) return "在线";
  if (status?.agent_online) return "在线";
  return "离线";
}

function staffStatusText(status?: string | null): string {
  if (status === "active") return "启用";
  if (status === "disabled" || status === "inactive") return "停用";
  if (status === "deleted") return "已删除";
  return status || "-";
}

function staffStatusClass(status?: string | null): string {
  if (status === "active") return "bg-emerald-50 text-emerald-700";
  if (status === "deleted") return "bg-slate-100 text-slate-500";
  return "bg-amber-50 text-amber-700";
}

export default function WechatAgent({ activeTab = "status" }: { activeTab?: WechatAgentTab }) {
  const [agentStatus, setAgentStatus] = useState<AgentStatusData | null>(null);
  const [localOnline, setLocalOnline] = useState<boolean | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<LocalAgentRuntimeStatus | null>(null);
  const [staffList, setStaffList] = useState<Staff[]>([]);
  const [pendingTasks, setPendingTasks] = useState<WechatTask[]>([]);
  const [taskHistory, setTaskHistory] = useState<WechatTaskHistoryItem[]>([]);
  const [taskHistoryTotal, setTaskHistoryTotal] = useState(0);
  const [taskHistoryPage, setTaskHistoryPage] = useState(1);
  const [taskHistoryPageSize] = useState(20);
  const [taskHistoryLoading, setTaskHistoryLoading] = useState(false);
  const [selectedTask, setSelectedTask] = useState<WechatTask | null>(null);
  const [loading, setLoading] = useState(false);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [taskDetailLoading, setTaskDetailLoading] = useState(false);
  const [savingStaff, setSavingStaff] = useState(false);
  const [staffActionId, setStaffActionId] = useState<number | null>(null);
  const [testing, setTesting] = useState(false);
  const [testNickname, setTestNickname] = useState(DEFAULT_TEST_NICKNAME);
  const [testMessage, setTestMessage] = useState("小高AI微信助手测试消息");
  const [advancedDiagnosticsOpen, setAdvancedDiagnosticsOpen] = useState(false);
  const [testResult, setTestResult] = useState<{
    createdTaskId?: number;
    localAgentOnline?: boolean;
    executed?: boolean;
    pollResult?: PollAndExecuteResponse | null;
    message: string;
  } | null>(null);
  const [staffKeyword, setStaffKeyword] = useState("");
  const [staffStatusFilter, setStaffStatusFilter] = useState<"all" | "active" | "disabled">("all");
  const [taskStatusFilter, setTaskStatusFilter] = useState("all");
  const [taskTypeFilter, setTaskTypeFilter] = useState("all");
  const [taskModeFilter, setTaskModeFilter] = useState("all");
  const [taskKeyword, setTaskKeyword] = useState("");
  const [taskFailureStage, setTaskFailureStage] = useState("");
  const [editingStaffId, setEditingStaffId] = useState<number | null>(null);
  const [staffForm, setStaffForm] = useState({
    name: "",
    wechat_nickname: "",
    wechat_id: "",
    phone: "",
    status: "active",
  });
  const [editStaffForm, setEditStaffForm] = useState({
    name: "",
    wechat_nickname: "",
    wechat_id: "",
    phone: "",
    status: "active",
  });

  const activeStaff = useMemo(
    () => staffList.filter((staff) => staff.status === "active"),
    [staffList],
  );

  async function loadStaffList(
    status = staffStatusFilter,
    keyword = staffKeyword,
  ) {
    const staffs = await fetchStaffList({
      status,
      keyword: keyword.trim() || undefined,
    });
    setStaffList(staffs);
  }

  async function loadTaskHistory(page = taskHistoryPage) {
    setTaskHistoryLoading(true);
    try {
      const history = await fetchWechatTaskHistory({
        page,
        page_size: taskHistoryPageSize,
        status: taskStatusFilter !== "all" ? taskStatusFilter : undefined,
        task_type: taskTypeFilter !== "all" ? taskTypeFilter : undefined,
        mode: taskModeFilter !== "all" ? taskModeFilter : undefined,
        keyword: taskKeyword.trim() || undefined,
        failure_stage: taskFailureStage.trim() || undefined,
      });
      setTaskHistory(history.items);
      setTaskHistoryTotal(history.total);
      setTaskHistoryPage(history.page);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "任务历史加载失败");
    } finally {
      setTaskHistoryLoading(false);
    }
  }

  async function loadPendingTasksForBrowser(): Promise<WechatTask[]> {
    try {
      return await fetchBrowserPendingWechatTasks({ limit: 20 });
    } catch (err) {
      if (isLocalAgentAuthErrorCode(getApiErrorCode(err))) {
        toast.warning("Local Agent 尚未完成授权或当前任务接口需要 Agent token");
        return [];
      }
      throw err;
    }
  }

  async function refreshPage() {
    setLoading(true);
    try {
      const [statusResponse, health, runtime, staffs, tasks, history] = await Promise.all([
        fetchAgentStatus().catch(() => null),
        checkLocalAgentHealth().catch(() => null),
        fetchLocalAgentRuntimeStatus().catch(() => null),
        fetchStaffList({
          status: staffStatusFilter,
          keyword: staffKeyword.trim() || undefined,
        }),
        loadPendingTasksForBrowser(),
        fetchWechatTaskHistory({
          page: taskHistoryPage,
          page_size: taskHistoryPageSize,
          status: taskStatusFilter !== "all" ? taskStatusFilter : undefined,
          task_type: taskTypeFilter !== "all" ? taskTypeFilter : undefined,
          mode: taskModeFilter !== "all" ? taskModeFilter : undefined,
          keyword: taskKeyword.trim() || undefined,
          failure_stage: taskFailureStage.trim() || undefined,
        }).catch(() => null),
      ]);
      setAgentStatus(statusResponse?.data || null);
      setLocalOnline(Boolean(health?.success));
      setRuntimeStatus(runtime);
      setStaffList(staffs);
      setPendingTasks(tasks);
      if (history) {
        setTaskHistory(history.items);
        setTaskHistoryTotal(history.total);
        setTaskHistoryPage(history.page);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "微信助手数据加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshPage();
  }, []);

  async function handleRefreshRuntime() {
    setRuntimeLoading(true);
    try {
      const [health, runtime] = await Promise.all([
        checkLocalAgentHealth().catch(() => null),
        fetchLocalAgentRuntimeStatus().catch(() => null),
      ]);
      setLocalOnline(Boolean(health?.success));
      setRuntimeStatus(runtime);
      if (!health?.success) {
        toast.warning("未检测到本机 Local Agent");
      }
    } finally {
      setRuntimeLoading(false);
    }
  }

  async function handleEnablePolling() {
    setRuntimeLoading(true);
    try {
      const runtime = await enableLocalAgentTaskPolling();
      setRuntimeStatus(runtime);
      setLocalOnline(true);
      toast.success("本机 Agent 已开始接收任务");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "开始接收任务失败");
    } finally {
      setRuntimeLoading(false);
    }
  }

  async function handleDisablePolling() {
    setRuntimeLoading(true);
    try {
      const runtime = await disableLocalAgentTaskPolling();
      setRuntimeStatus(runtime);
      setLocalOnline(true);
      toast.success("本机 Agent 已暂停接收任务");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "暂停接收任务失败");
    } finally {
      setRuntimeLoading(false);
    }
  }

  async function handleCopyCommand(command: string) {
    try {
      await navigator.clipboard.writeText(command);
      toast.success("启动命令已复制");
    } catch {
      toast.error("复制失败，请手动选择命令文本");
    }
  }

  function resetStaffForm() {
    setStaffForm({
      name: "",
      wechat_nickname: "",
      wechat_id: "",
      phone: "",
      status: "active",
    });
  }

  function closeEditStaffDialog() {
    setEditingStaffId(null);
    setEditStaffForm({
      name: "",
      wechat_nickname: "",
      wechat_id: "",
      phone: "",
      status: "active",
    });
  }

  function handleEditStaff(staff: Staff) {
    setEditingStaffId(staff.id);
    setEditStaffForm({
      name: staff.name || "",
      wechat_nickname: staff.wechat_nickname || "",
      wechat_id: staff.wechat_id || "",
      phone: staff.phone || "",
      status: staff.status === "disabled" || staff.status === "inactive" ? "disabled" : "active",
    });
  }

  async function handleSaveStaff() {
    const name = staffForm.name.trim();
    const wechatNickname = staffForm.wechat_nickname.trim();
    if (!name || !wechatNickname) {
      toast.warning("请填写销售姓名和微信昵称");
      return;
    }
    setSavingStaff(true);
    try {
      const payload = {
        name,
        wechat_nickname: wechatNickname,
        wechat_id: staffForm.wechat_id.trim() || undefined,
        phone: staffForm.phone.trim() || undefined,
      };
      await createStaff(payload);
      resetStaffForm();
      toast.success("销售微信已保存");
      await loadStaffList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存销售微信失败");
    } finally {
      setSavingStaff(false);
    }
  }

  async function handleSaveEditStaff() {
    if (!editingStaffId) return;
    const name = editStaffForm.name.trim();
    const wechatNickname = editStaffForm.wechat_nickname.trim();
    if (!name || !wechatNickname) {
      toast.warning("请填写销售姓名和微信昵称");
      return;
    }
    setSavingStaff(true);
    try {
      await updateStaff(editingStaffId, {
        name,
        wechat_nickname: wechatNickname,
        wechat_id: editStaffForm.wechat_id.trim() || undefined,
        phone: editStaffForm.phone.trim() || undefined,
        status: editStaffForm.status as "active" | "disabled",
      });
      closeEditStaffDialog();
      toast.success("销售微信已更新");
      await loadStaffList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存销售微信失败");
    } finally {
      setSavingStaff(false);
    }
  }

  async function handleStaffStatusAction(staff: Staff, action: "enable" | "disable" | "delete") {
    if (action === "delete") {
      const confirmed = window.confirm("删除后该销售将不再显示，也不会参与后续线索分配，历史任务和线索记录会保留。确认删除？");
      if (!confirmed) return;
    }
    setStaffActionId(staff.id);
    try {
      if (action === "enable") {
        await enableStaff(staff.id);
        toast.success("销售已启用");
      } else if (action === "disable") {
        await disableStaff(staff.id);
        toast.success("销售已停用");
      } else {
        await deleteStaff(staff.id);
        toast.success("销售已删除");
      }
      await loadStaffList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "销售状态更新失败");
    } finally {
      setStaffActionId(null);
    }
  }

  async function handleRunTest() {
    const nickname = testNickname.trim() || DEFAULT_TEST_NICKNAME;
    const message = testMessage.trim();
    if (!message) {
      toast.warning("请填写测试内容");
      return;
    }

    setTesting(true);
    setTestResult(null);
    try {
      const health = await checkLocalAgentHealth().catch(() => null);
      const agentReady = Boolean(health?.success);
      if (!agentReady) {
        setTestResult({
          localAgentOnline: false,
          executed: false,
          message: "未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手",
        });
        return;
      }

      const task = await createWechatTask({
        task_type: "notify_sales",
        target_nickname: nickname,
        message,
        mode: "paste_only",
      });
      const result = await pollAndExecuteWechatTask(task.id);
      setTestResult({
        createdTaskId: task.id,
        localAgentOnline: true,
        executed: Boolean(result.success),
        pollResult: result,
        message: result.success
          ? "测试任务已由本机 Agent 执行。当前安全门禁保持 sent=false。"
          : result.failure_stage || result.message || "测试任务执行失败",
      });
      await refreshPage();
    } catch (err) {
      setTestResult({
        localAgentOnline: true,
        executed: false,
        message: err instanceof Error ? err.message : "测试失败",
      });
    } finally {
      setTesting(false);
    }
  }

  async function handleOpenTaskDetail(task: { id: number }) {
    setTaskDetailLoading(true);
    setSelectedTask(null);
    try {
      const detail = await fetchWechatTask(task.id);
      setSelectedTask(detail);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "任务详情加载失败");
    } finally {
      setTaskDetailLoading(false);
    }
  }

  const onlineText = agentOnlineText(agentStatus, localOnline);
  const pageMeta = TAB_META[activeTab];
  const todayTaskCount = pendingTasks.filter((task) => {
    const created = task.created_at ? new Date(task.created_at) : null;
    if (!created || Number.isNaN(created.getTime())) return false;
    const now = new Date();
    return created.toDateString() === now.toDateString();
  }).length;

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="grid h-10 w-10 place-items-center rounded-lg bg-emerald-50 text-emerald-600">
              <MessageCircleIcon size={23} />
            </div>
            <div>
              <h1 className="text-[15px] font-bold text-[#1a1f2e]">小高AI微信助手</h1>
              <p className="mt-1 text-xs text-[#8b95a6]">
                {pageMeta.description}
              </p>
            </div>
          </div>
          <button
            onClick={() => void refreshPage()}
            disabled={loading}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-[#dfe5ee] bg-white px-3 text-xs font-semibold text-[#374151] disabled:opacity-60"
          >
            <RefreshCwIcon size={14} className={loading ? "animate-spin" : ""} />
            刷新
          </button>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-auto p-5">
        <div className="mb-4 rounded-lg border border-[#dfe5ee] bg-white px-4 py-3">
          <div className="text-sm font-bold text-[#1a1f2e]">{pageMeta.title}</div>
          <div className="mt-1 text-xs leading-5 text-[#64748b]">{pageMeta.description}</div>
        </div>

        <div className="grid gap-4 xl:grid-cols-4">
          <div className="rounded-lg border border-[#dfe5ee] bg-white p-4">
            <div className="text-xs font-semibold text-[#64748b]">Local Agent</div>
            <div className={onlineText === "在线" ? "mt-2 text-2xl font-bold text-emerald-600" : "mt-2 text-2xl font-bold text-rose-600"}>
              {onlineText}
            </div>
            <div className="mt-2 text-[11px] text-[#8b95a6]">必须在本地 Windows 电脑运行</div>
          </div>
          <div className="rounded-lg border border-[#dfe5ee] bg-white p-4">
            <div className="text-xs font-semibold text-[#64748b]">最近心跳</div>
            <div className="mt-2 text-sm font-bold text-[#1a1f2e]">{formatTime(agentStatus?.last_heartbeat_at)}</div>
            <div className="mt-2 text-[11px] text-[#8b95a6]">服务器不能运行 19000</div>
          </div>
          <div className="rounded-lg border border-[#dfe5ee] bg-white p-4">
            <div className="text-xs font-semibold text-[#64748b]">销售微信</div>
            <div className="mt-2 text-2xl font-bold text-[#1a1f2e]">{activeStaff.length}</div>
            <div className="mt-2 text-[11px] text-[#8b95a6]">已启用销售微信数量</div>
          </div>
          <div className="rounded-lg border border-[#dfe5ee] bg-white p-4">
            <div className="text-xs font-semibold text-[#64748b]">任务记录</div>
            <div className="mt-2 text-2xl font-bold text-[#1a1f2e]">{todayTaskCount} / {pendingTasks.length}</div>
            <div className="mt-2 text-[11px] text-[#8b95a6]">今日创建 / 待处理</div>
          </div>
        </div>

        {activeTab === "status" ? (
        <section className="mt-4 rounded-lg border border-[#dfe5ee] bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#edf1f6] px-4 py-3">
            <div className="flex items-center gap-2">
              <PowerIcon size={16} className={localOnline ? "text-emerald-600" : "text-rose-600"} />
              <h2 className="text-sm font-bold text-[#1a1f2e]">本机 Local Agent</h2>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => void handleRefreshRuntime()}
                disabled={runtimeLoading}
                className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
              >
                <RefreshCwIcon size={14} className={runtimeLoading ? "animate-spin" : ""} />
                检测连接
              </button>
              <button
                onClick={() => void handleEnablePolling()}
                disabled={!localOnline || runtimeLoading || runtimeStatus?.task_polling_enabled === true}
                className="inline-flex h-9 items-center gap-2 rounded-md bg-emerald-600 px-3 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
              >
                <PlayIcon size={14} />
                开始接收任务
              </button>
              <button
                onClick={() => void handleDisablePolling()}
                disabled={!localOnline || runtimeLoading || runtimeStatus?.task_polling_enabled !== true}
                className="inline-flex h-9 items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 text-xs font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-60"
              >
                <PauseIcon size={14} />
                暂停接收任务
              </button>
            </div>
          </div>
          <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.85fr)]">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-md border border-slate-200 px-3 py-3">
                <div className="text-[11px] font-semibold text-slate-500">本机地址</div>
                <div className="mt-1 break-all font-mono text-xs text-slate-800">{LOCAL_AGENT_BASE_URL}</div>
              </div>
              <div className="rounded-md border border-slate-200 px-3 py-3">
                <div className="text-[11px] font-semibold text-slate-500">接收任务</div>
                <div className={runtimeStatus?.task_polling_enabled ? "mt-1 text-sm font-bold text-emerald-600" : "mt-1 text-sm font-bold text-amber-700"}>
                  {runtimeStatus?.task_polling_enabled ? "正在接收 9000 任务" : localOnline ? "已连接，未接收任务" : "Local Agent 未启动"}
                </div>
              </div>
              <div className="rounded-md border border-slate-200 px-3 py-3">
                <div className="text-[11px] font-semibold text-slate-500">上游服务地址</div>
                <div className="mt-1 break-all text-xs text-slate-800">{runtimeStatus?.server_url || "未配置"}</div>
              </div>
              <div className="rounded-md border border-slate-200 px-3 py-3">
                <div className="text-[11px] font-semibold text-slate-500">版本 / 模式</div>
                <div className="mt-1 text-xs text-slate-800">{runtimeStatus ? `${runtimeStatus.version} / ${runtimeStatus.mode}` : "-"}</div>
              </div>
              <div className="rounded-md border border-slate-200 px-3 py-3">
                <div className="text-[11px] font-semibold text-slate-500">最近轮询</div>
                <div className="mt-1 text-xs text-slate-800">{formatTime(runtimeStatus?.last_poll_at)}</div>
              </div>
              <div className="rounded-md border border-slate-200 px-3 py-3">
                <div className="text-[11px] font-semibold text-slate-500">最近错误</div>
                <div className="mt-1 break-all text-xs text-slate-800">{runtimeStatus?.last_error || "-"}</div>
              </div>
            </div>

            <div className={localOnline ? "rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs leading-6 text-emerald-800" : "rounded-md border border-rose-200 bg-rose-50 p-3 text-xs leading-6 text-rose-800"}>
              <div className="font-bold">{localOnline ? "Local Agent 在线" : "Local Agent 未启动"}</div>
              <div>浏览器只能检测当前电脑的 127.0.0.1:19000，不能直接保证启动 exe。启动后点击“检测连接”刷新状态。</div>
              <div className="mt-3 rounded bg-white/70 p-2">
                <div className="font-semibold">本机实时检测</div>
                <div>{localOnline ? "来自 127.0.0.1:19000，当前浏览器所在电脑已连通。" : "来自 127.0.0.1:19000，当前浏览器所在电脑未连通。"}</div>
              </div>
              <div className="mt-2 rounded bg-white/70 p-2">
                <div className="font-semibold">服务端心跳记录</div>
                <div>来自 9000 /agent/status：{agentStatus?.agent_online ? "服务端记录最近在线" : "服务端未记录在线心跳"}，最近心跳 {formatTime(agentStatus?.last_heartbeat_at)}。</div>
              </div>
              <div className="mt-2 rounded bg-white/70 p-2">
                最近任务结果：{runtimeStatus?.last_task_result ? shortText(JSON.stringify(runtimeStatus.last_task_result), 120) : "-"}
              </div>
            </div>
          </div>
        </section>
        ) : null}

        {activeTab === "download-test" ? (
          <>
            <section className="mt-4 rounded-lg border border-[#dfe5ee] bg-white">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#edf1f6] px-4 py-3">
                <div>
                  <div className="text-sm font-bold text-[#1a1f2e]">启动说明</div>
                  <div className="mt-1 text-xs text-slate-500">浏览器不能直接启动本机 exe。请手动启动 Local Agent，启动后重新检测连接。</div>
                </div>
                <button
                  onClick={() => void handleRefreshRuntime()}
                  disabled={runtimeLoading}
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                >
                  <RefreshCwIcon size={14} className={runtimeLoading ? "animate-spin" : ""} />
                  重新检测连接
                </button>
              </div>
              <div className="space-y-3 p-4 text-xs leading-6 text-slate-700">
                <div className={localOnline ? "rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 font-semibold text-emerald-700" : "rounded-md border border-amber-200 bg-amber-50 px-3 py-2 font-semibold text-amber-800"}>
                  {localOnline ? "已检测到本机 Local Agent 在线。" : "Local Agent 未启动。请先启动本机助手，然后点击重新检测连接。"}
                </div>
                <div>网页按钮会调用当前电脑的 127.0.0.1:19000；宝塔服务器不能运行 19000。</div>
                <div className="grid gap-3 lg:grid-cols-2">
                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                    <div className="mb-1 font-semibold text-slate-900">源码启动命令</div>
                    <pre className="whitespace-pre-wrap break-all font-mono text-[11px] leading-5 text-slate-800">{SOURCE_START_COMMAND}</pre>
                  <button
                    onClick={() => void handleCopyCommand(SOURCE_START_COMMAND)}
                      className="mt-2 inline-flex h-8 items-center gap-2 rounded-md border border-slate-200 bg-white px-2 text-[11px] font-semibold text-slate-700"
                  >
                    <CopyIcon size={13} />
                      复制源码启动命令
                  </button>
                </div>
                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                    <div className="mb-1 font-semibold text-slate-900">exe 启动命令</div>
                    <pre className="whitespace-pre-wrap break-all font-mono text-[11px] leading-5 text-slate-800">{EXE_START_COMMAND}</pre>
                  <button
                    onClick={() => void handleCopyCommand(EXE_START_COMMAND)}
                      className="mt-2 inline-flex h-8 items-center gap-2 rounded-md border border-slate-200 bg-white px-2 text-[11px] font-semibold text-slate-700"
                  >
                    <CopyIcon size={13} />
                      复制 exe 启动命令
                  </button>
                  </div>
                </div>
              </div>
            </section>

            <section className="mt-4 rounded-lg border border-[#dfe5ee] bg-white">
              <div className="border-b border-[#edf1f6] px-4 py-3">
                <div className="text-sm font-bold text-[#1a1f2e]">安装包下载</div>
                <div className="mt-1 text-xs text-slate-500">当前没有真实下载接口，不提供假下载入口。</div>
              </div>
              <div className="p-4 text-xs leading-6 text-slate-700">
                <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3">
                  <div className="font-bold text-slate-900">安装包下载暂未开放</div>
                  <div className="mt-1">当前请使用本机已部署的 exe 或源码方式启动。</div>
                  <div className="mt-1">版本 / 模式：{runtimeStatus ? `${runtimeStatus.version} / ${runtimeStatus.mode}` : "未检测"}</div>
                </div>
              </div>
            </section>
          </>
        ) : null}

        {activeTab === "config" ? (
        <div className="mt-5 grid gap-5">
          <section className="rounded-lg border border-[#dfe5ee] bg-white">
            <div className="flex items-center gap-2 border-b border-[#edf1f6] px-4 py-3">
              <UserPlusIcon size={16} className="text-blue-600" />
              <div>
                <h2 className="text-sm font-bold text-[#1a1f2e]">新增销售</h2>
                <div className="mt-1 text-xs text-slate-500">配置销售微信昵称后，系统会按分配规则生成微信通知任务。</div>
              </div>
            </div>
            <div className="space-y-3 p-4">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                <input
                  value={staffForm.name}
                  onChange={(event) => setStaffForm((prev) => ({ ...prev, name: event.target.value }))}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="销售姓名"
                />
                <input
                  value={staffForm.wechat_nickname}
                  onChange={(event) => setStaffForm((prev) => ({ ...prev, wechat_nickname: event.target.value }))}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="微信昵称"
                />
                <input
                  value={staffForm.wechat_id}
                  onChange={(event) => setStaffForm((prev) => ({ ...prev, wechat_id: event.target.value }))}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="微信号"
                />
                <input
                  value={staffForm.phone}
                  onChange={(event) => setStaffForm((prev) => ({ ...prev, phone: event.target.value }))}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="手机号"
                />
                <button
                  onClick={() => void handleSaveStaff()}
                  disabled={savingStaff}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-blue-600 px-4 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {savingStaff ? <Loader2Icon size={14} className="animate-spin" /> : <CheckCircle2Icon size={14} />}
                  新增销售
                </button>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-[#dfe5ee] bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#edf1f6] px-4 py-3">
              <div className="min-w-[240px] flex-1">
                <h2 className="text-sm font-bold text-[#1a1f2e]">销售列表</h2>
                <div className="mt-1 text-xs text-slate-500">已配置的销售微信账号。启用状态的销售会参与线索分配，停用或删除后不再参与新线索分配。</div>
              </div>
              <div className="flex flex-1 flex-wrap items-center justify-end gap-2">
                <div className="relative w-full sm:w-64">
                  <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    value={staffKeyword}
                    onChange={(event) => setStaffKeyword(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void loadStaffList();
                    }}
                    className="h-9 w-full rounded-md border border-slate-200 pl-8 pr-3 text-xs outline-none focus:border-blue-300"
                    placeholder="姓名 / 昵称 / 微信号 / 手机"
                  />
                </div>
                <select
                  value={staffStatusFilter}
                  onChange={(event) => {
                    const nextStatus = event.target.value as "all" | "active" | "disabled";
                    setStaffStatusFilter(nextStatus);
                    void loadStaffList(nextStatus, staffKeyword);
                  }}
                  className="h-9 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700 outline-none focus:border-blue-300"
                >
                  <option value="all">全部</option>
                  <option value="active">启用</option>
                  <option value="disabled">停用</option>
                </select>
                <button
                  onClick={() => void loadStaffList()}
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                >
                  <RefreshCwIcon size={13} />
                  刷新
                </button>
                <div className="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                  当前 {staffList.length} 条
                </div>
              </div>
            </div>
            <div className="p-4">
              <div className="overflow-auto rounded-md border border-slate-200">
                <table className="w-full min-w-[760px] text-left text-xs">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="px-3 py-2 font-semibold">销售姓名</th>
                      <th className="px-3 py-2 font-semibold">微信昵称</th>
                      <th className="px-3 py-2 font-semibold">微信号</th>
                      <th className="px-3 py-2 font-semibold">手机号</th>
                      <th className="px-3 py-2 font-semibold">状态</th>
                      <th className="px-3 py-2 font-semibold">更新时间</th>
                      <th className="px-3 py-2 text-right font-semibold">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {staffList.length ? (
                      staffList.map((staff) => (
                        <tr key={staff.id} className="bg-white">
                          <td className="px-3 py-2 font-semibold text-slate-800">{staff.name}</td>
                          <td className="px-3 py-2 text-slate-600">{staff.wechat_nickname || "-"}</td>
                          <td className="px-3 py-2 text-slate-600">{staff.wechat_id || "-"}</td>
                          <td className="px-3 py-2 text-slate-600">{staff.phone || "-"}</td>
                          <td className="px-3 py-2">
                            <span className={`inline-flex rounded-md px-2 py-1 font-semibold ${staffStatusClass(staff.status)}`}>
                              {staffStatusText(staff.status)}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-slate-600">{formatTime(staff.updated_at || staff.created_at)}</td>
                          <td className="px-3 py-2">
                            <div className="flex justify-end gap-2">
                              <button
                                onClick={() => handleEditStaff(staff)}
                                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50"
                                title="编辑"
                              >
                                <PencilIcon size={13} />
                              </button>
                              {staff.status === "active" ? (
                                <button
                                  onClick={() => void handleStaffStatusAction(staff, "disable")}
                                  disabled={staffActionId === staff.id}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-amber-200 text-amber-700 hover:bg-amber-50 disabled:opacity-60"
                                  title="停用"
                                >
                                  <BanIcon size={13} />
                                </button>
                              ) : (
                                <button
                                  onClick={() => void handleStaffStatusAction(staff, "enable")}
                                  disabled={staffActionId === staff.id}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-emerald-200 text-emerald-700 hover:bg-emerald-50 disabled:opacity-60"
                                  title="启用"
                                >
                                  <PlayIcon size={13} />
                                </button>
                              )}
                              <button
                                onClick={() => void handleStaffStatusAction(staff, "delete")}
                                disabled={staffActionId === staff.id}
                                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-rose-200 text-rose-700 hover:bg-rose-50 disabled:opacity-60"
                                title="删除"
                              >
                                <Trash2Icon size={13} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={7} className="px-3 py-8 text-center text-slate-500">
                          暂无销售微信配置，请先新增销售微信。
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

        </div>
        ) : null}

        {activeTab === "download-test" ? (
          <section className="mt-4 rounded-lg border border-[#dfe5ee] bg-white">
            <div className="flex items-center gap-2 border-b border-[#edf1f6] px-4 py-3">
              <ShieldCheckIcon size={16} className="text-emerald-600" />
              <div>
                <h2 className="text-sm font-bold text-[#1a1f2e]">测试任务</h2>
                <div className="mt-1 text-xs text-slate-500">测试任务默认只粘贴不发送，用于验证联系人搜索、聊天窗口定位和输入框写入。不会自动回车发送。</div>
              </div>
            </div>
            <div className="space-y-3 p-4">
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                执行测试会操作本机微信窗口，请确保微信已登录且窗口可见。本次测试只粘贴消息，不会自动发送。
              </div>
              <div className="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)]">
                <input
                  value={testNickname}
                  onChange={(event) => setTestNickname(event.target.value)}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="测试销售微信昵称"
                />
                <input
                  value={testMessage}
                  onChange={(event) => setTestMessage(event.target.value)}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="测试消息，必填"
                />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-xs font-semibold text-slate-600">执行模式：paste_only，仅粘贴，不发送。</div>
                <button
                  onClick={() => void handleRunTest()}
                  disabled={testing || !testMessage.trim()}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-emerald-600 px-4 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
                >
                  {testing ? <Loader2Icon size={14} className="animate-spin" /> : <PlayIcon size={14} />}
                  执行粘贴测试
                </button>
              </div>
              {testResult ? (
                <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-700">
                  <div className="grid gap-2 sm:grid-cols-3">
                    <div>Local Agent：{testResult.localAgentOnline ? "在线" : "离线"}</div>
                    <div>任务：{testResult.createdTaskId ? `#${testResult.createdTaskId}` : "未创建"}</div>
                    <div>执行：{testResult.executed ? "已执行" : "未执行"}</div>
                    <div>粘贴：{testResult.pollResult?.action?.pasted ? "已粘贴" : "未粘贴"}</div>
                    <div>发送：{testResult.pollResult?.action?.sent ? "已发送" : "未发送"}</div>
                    <div>联系人验证：{testResult.pollResult?.raw_result?.contact_verified ? "通过" : "-"}</div>
                    <div className="sm:col-span-3">failure_stage：{testResult.pollResult?.failure_stage || "-"}</div>
                    <div className="sm:col-span-3">结果：{testResult.message}</div>
                  </div>
                  <details className="mt-3 rounded-md border border-slate-200 bg-white px-3 py-2">
                    <summary className="cursor-pointer font-semibold text-slate-700">查看 raw_result</summary>
                    <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-50 p-3 font-mono text-[11px] leading-5 text-slate-700">
                      {testResult.pollResult ? JSON.stringify(testResult.pollResult, null, 2) : "-"}
                    </pre>
                  </details>
                </div>
              ) : null}
            </div>
          </section>
        ) : null}

        {activeTab === "download-test" ? (
          <section className="mt-4 rounded-lg border border-[#dfe5ee] bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#edf1f6] px-4 py-3">
              <div>
                <div className="text-sm font-bold text-[#1a1f2e]">高级诊断</div>
                <div className="mt-1 text-xs text-slate-500">高级诊断用于排查微信窗口、OCR、搜索框、前台焦点等问题。普通使用无需操作。</div>
              </div>
              <button
                onClick={() => setAdvancedDiagnosticsOpen((value) => !value)}
                className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                <EyeIcon size={14} />
                {advancedDiagnosticsOpen ? "收起诊断工具" : "展开诊断工具"}
              </button>
            </div>
            {advancedDiagnosticsOpen ? (
              <div className="p-4">
                <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                  仅排查问题时使用。诊断操作可能切换微信窗口、读取 OCR 状态或执行搜索检查，不会绕过联系人验证和安全门禁。
                </div>
                <LocalWechatAgentTestPanel />
              </div>
            ) : (
              <div className="px-4 py-6 text-center text-xs text-slate-500">
                高级诊断默认折叠，排查问题时再展开。
              </div>
            )}
          </section>
        ) : null}

        {activeTab === "tasks" ? (
        <section className="mt-5 rounded-lg border border-[#dfe5ee] bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#edf1f6] px-4 py-3">
            <div className="flex items-center gap-2">
              <SendIcon size={16} className="text-blue-600" />
              <h2 className="text-sm font-bold text-[#1a1f2e]">任务记录</h2>
            </div>
            <span className="text-xs text-[#8b95a6]">待处理任务 {pendingTasks.length} 条</span>
          </div>
          <div className="grid gap-3 border-b border-[#edf1f6] bg-slate-50 px-4 py-3 lg:grid-cols-[130px_150px_150px_minmax(180px,1fr)_180px_auto]">
            <select
              value={taskTypeFilter}
              onChange={(event) => {
                setTaskTypeFilter(event.target.value);
                setTaskHistoryPage(1);
              }}
              className="h-9 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700 outline-none focus:border-blue-300"
            >
              <option value="all">全部类型</option>
              <option value="notify_sales">通知销售</option>
              <option value="detect_reply">检测回复</option>
            </select>
            <select
              value={taskStatusFilter}
              onChange={(event) => {
                setTaskStatusFilter(event.target.value);
                setTaskHistoryPage(1);
              }}
              className="h-9 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700 outline-none focus:border-blue-300"
            >
              <option value="all">全部状态</option>
              <option value="pending">待执行</option>
              <option value="pasted">已粘贴</option>
              <option value="sent">已发送</option>
              <option value="failed">失败</option>
              <option value="blocked">已阻断</option>
            </select>
            <select
              value={taskModeFilter}
              onChange={(event) => {
                setTaskModeFilter(event.target.value);
                setTaskHistoryPage(1);
              }}
              className="h-9 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700 outline-none focus:border-blue-300"
            >
              <option value="all">全部模式</option>
              <option value="paste_only">paste_only</option>
              <option value="single_send">single_send</option>
              <option value="read_only">read_only</option>
            </select>
            <div className="relative">
              <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={taskKeyword}
                onChange={(event) => {
                  setTaskKeyword(event.target.value);
                  setTaskHistoryPage(1);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void loadTaskHistory(1);
                }}
                className="h-9 w-full rounded-md border border-slate-200 pl-8 pr-3 text-xs outline-none focus:border-blue-300"
                placeholder="销售昵称 / 客户联系方式"
              />
            </div>
            <input
              value={taskFailureStage}
              onChange={(event) => {
                setTaskFailureStage(event.target.value);
                setTaskHistoryPage(1);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") void loadTaskHistory(1);
              }}
              className="h-9 rounded-md border border-slate-200 px-3 text-xs outline-none focus:border-blue-300"
              placeholder="failure_stage"
            />
            <button
              onClick={() => void loadTaskHistory(1)}
              disabled={taskHistoryLoading}
              className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            >
              <RefreshCwIcon size={13} className={taskHistoryLoading ? "animate-spin" : ""} />
              查询
            </button>
          </div>
          <div className="overflow-auto">
            <table className="w-full min-w-[980px] text-left text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-semibold">任务ID</th>
                  <th className="px-4 py-3 font-semibold">任务类型</th>
                  <th className="px-4 py-3 font-semibold">目标销售</th>
                  <th className="px-4 py-3 font-semibold">模式</th>
                  <th className="px-4 py-3 font-semibold">状态</th>
                  <th className="px-4 py-3 font-semibold">失败阶段</th>
                  <th className="px-4 py-3 font-semibold">发送时间</th>
                  <th className="px-4 py-3 font-semibold">更新时间</th>
                  <th className="px-4 py-3 font-semibold">摘要</th>
                  <th className="px-4 py-3 text-right font-semibold">详情</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {taskHistory.length ? (
                  taskHistory.map((task) => (
                    <tr key={task.id} className="bg-white">
                      <td className="px-4 py-3 font-semibold text-slate-800">#{task.id}</td>
                      <td className="px-4 py-3 text-slate-600">{taskTypeText(task.task_type)}</td>
                      <td className="px-4 py-3">
                        <div className="font-semibold text-slate-800">{task.staff_wechat_nickname || task.target_nickname || "-"}</div>
                        <div className="mt-0.5 text-[11px] text-slate-500">{task.staff_name || "-"}</div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{taskModeText(task.mode)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 rounded-md px-2 py-1 font-semibold ${taskStatusClass(task.status)}`}>
                          {task.status === "pending" ? <ClockIcon size={12} /> : null}
                          {taskStatusText(task.status)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{task.failure_stage || "-"}</td>
                      <td className="px-4 py-3 text-slate-600">{formatTime(task.sent_at)}</td>
                      <td className="px-4 py-3 text-slate-600">{formatTime(task.updated_at)}</td>
                      <td className="px-4 py-3 text-slate-600">{shortText(rawSummaryText(task.raw_result_summary), 80)}</td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end">
                          <button
                            onClick={() => void handleOpenTaskDetail(task)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 text-[11px] font-semibold text-slate-700 hover:bg-slate-50"
                          >
                            <EyeIcon size={13} />
                            查看
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={10} className="px-4 py-10 text-center text-slate-500">
                      {taskHistoryLoading ? "正在加载任务历史" : "暂无任务记录"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#edf1f6] px-4 py-3 text-xs text-slate-600">
            <div>
              共 {taskHistoryTotal} 条，当前第 {taskHistoryPage} 页，每页 {taskHistoryPageSize} 条
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => void loadTaskHistory(Math.max(1, taskHistoryPage - 1))}
                disabled={taskHistoryLoading || taskHistoryPage <= 1}
                className="h-8 rounded-md border border-slate-200 bg-white px-3 font-semibold text-slate-700 disabled:opacity-50"
              >
                上一页
              </button>
              <button
                onClick={() => void loadTaskHistory(taskHistoryPage + 1)}
                disabled={taskHistoryLoading || taskHistoryPage * taskHistoryPageSize >= taskHistoryTotal}
                className="h-8 rounded-md border border-slate-200 bg-white px-3 font-semibold text-slate-700 disabled:opacity-50"
              >
                下一页
              </button>
            </div>
          </div>
        </section>
        ) : null}

        {editingStaffId ? (
          <div className="fixed inset-0 z-40 grid place-items-center bg-slate-900/30 p-5">
            <div className="w-full max-w-xl overflow-hidden rounded-lg border border-[#dfe5ee] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
              <div className="flex items-center justify-between border-b border-[#edf1f6] px-4 py-3">
                <div>
                  <div className="text-sm font-bold text-[#1a1f2e]">编辑销售</div>
                  <div className="mt-1 text-xs text-[#8b95a6]">修改销售微信配置后会影响后续新线索分配。</div>
                </div>
                <button
                  onClick={closeEditStaffDialog}
                  className="grid h-8 w-8 place-items-center rounded-md text-slate-500 hover:bg-slate-100"
                >
                  <XIcon size={16} />
                </button>
              </div>
              <div className="space-y-3 p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="text-xs font-semibold text-slate-600">
                    销售姓名
                    <input
                      value={editStaffForm.name}
                      onChange={(event) => setEditStaffForm((prev) => ({ ...prev, name: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-md border border-slate-200 px-3 text-sm font-normal text-slate-800 outline-none focus:border-blue-300"
                      placeholder="销售姓名"
                    />
                  </label>
                  <label className="text-xs font-semibold text-slate-600">
                    微信昵称
                    <input
                      value={editStaffForm.wechat_nickname}
                      onChange={(event) => setEditStaffForm((prev) => ({ ...prev, wechat_nickname: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-md border border-slate-200 px-3 text-sm font-normal text-slate-800 outline-none focus:border-blue-300"
                      placeholder="微信昵称"
                    />
                  </label>
                  <label className="text-xs font-semibold text-slate-600">
                    微信号
                    <input
                      value={editStaffForm.wechat_id}
                      onChange={(event) => setEditStaffForm((prev) => ({ ...prev, wechat_id: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-md border border-slate-200 px-3 text-sm font-normal text-slate-800 outline-none focus:border-blue-300"
                      placeholder="微信号"
                    />
                  </label>
                  <label className="text-xs font-semibold text-slate-600">
                    手机号
                    <input
                      value={editStaffForm.phone}
                      onChange={(event) => setEditStaffForm((prev) => ({ ...prev, phone: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-md border border-slate-200 px-3 text-sm font-normal text-slate-800 outline-none focus:border-blue-300"
                      placeholder="手机号"
                    />
                  </label>
                  <label className="text-xs font-semibold text-slate-600 sm:col-span-2">
                    状态
                    <select
                      value={editStaffForm.status}
                      onChange={(event) => setEditStaffForm((prev) => ({ ...prev, status: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-normal text-slate-700 outline-none focus:border-blue-300"
                    >
                      <option value="active">启用</option>
                      <option value="disabled">停用</option>
                    </select>
                  </label>
                </div>
                <div className="flex flex-wrap justify-end gap-2 border-t border-[#edf1f6] pt-3">
                  <button
                    onClick={closeEditStaffDialog}
                    className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    取消
                  </button>
                  <button
                    onClick={() => void handleSaveEditStaff()}
                    disabled={savingStaff}
                    className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-4 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                  >
                    {savingStaff ? <Loader2Icon size={14} className="animate-spin" /> : <CheckCircle2Icon size={14} />}
                    保存修改
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {selectedTask ? (
          <div className="fixed inset-0 z-40 grid place-items-center bg-slate-900/30 p-5">
            <div className="flex max-h-[86vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-[#dfe5ee] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
              <div className="flex items-center justify-between border-b border-[#edf1f6] px-4 py-3">
                <div>
                  <div className="text-sm font-bold text-[#1a1f2e]">任务详情 #{selectedTask.id}</div>
                  <div className="mt-1 text-xs text-[#8b95a6]">
                    {taskTypeText(selectedTask.task_type)} / {taskModeText(selectedTask.mode)}
                  </div>
                </div>
                <button
                  onClick={() => setSelectedTask(null)}
                  className="grid h-8 w-8 place-items-center rounded-md text-slate-500 hover:bg-slate-100"
                >
                  <XIcon size={16} />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-auto p-4">
                {taskDetailLoading ? (
                  <div className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-3 text-xs text-slate-600">
                    <Loader2Icon size={14} className="animate-spin" />
                    正在加载任务详情
                  </div>
                ) : null}
                <div className="grid gap-3 text-xs sm:grid-cols-2">
                  <div className="rounded-md border border-slate-200 px-3 py-2">
                    <div className="text-[11px] font-semibold text-slate-500">target_nickname</div>
                    <div className="mt-1 text-slate-800">{selectedTask.target_nickname || "-"}</div>
                  </div>
                  <div className="rounded-md border border-slate-200 px-3 py-2">
                    <div className="text-[11px] font-semibold text-slate-500">status</div>
                    <div className="mt-1 text-slate-800">{taskStatusText(selectedTask.status)}</div>
                  </div>
                  <div className="rounded-md border border-slate-200 px-3 py-2">
                    <div className="text-[11px] font-semibold text-slate-500">failure_stage</div>
                    <div className="mt-1 text-slate-800">{selectedTask.failure_stage || "-"}</div>
                  </div>
                  <div className="rounded-md border border-slate-200 px-3 py-2">
                    <div className="text-[11px] font-semibold text-slate-500">created_at / updated_at</div>
                    <div className="mt-1 text-slate-800">{formatTime(selectedTask.created_at)} / {formatTime(selectedTask.updated_at)}</div>
                  </div>
                  <div className="rounded-md border border-slate-200 px-3 py-2">
                    <div className="text-[11px] font-semibold text-slate-500">lead_id / staff_id</div>
                    <div className="mt-1 text-slate-800">{selectedTask.lead_id || "-"} / {selectedTask.staff_id || "-"}</div>
                  </div>
                  <div className="rounded-md border border-slate-200 px-3 py-2">
                    <div className="text-[11px] font-semibold text-slate-500">agent</div>
                    <div className="mt-1 text-slate-800">{selectedTask.agent_hostname || "-"} / {selectedTask.agent_pid || "-"}</div>
                  </div>
                </div>
                <div className="mt-3 rounded-md border border-slate-200 px-3 py-2 text-xs">
                  <div className="text-[11px] font-semibold text-slate-500">消息内容</div>
                  <div className="mt-1 whitespace-pre-wrap text-slate-800">{selectedTask.message || "-"}</div>
                </div>
                <div className="mt-3 rounded-md border border-slate-200 px-3 py-2 text-xs">
                  <div className="text-[11px] font-semibold text-slate-500">raw_result</div>
                  <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-50 p-3 font-mono text-[11px] leading-5 text-slate-700">
                    {selectedTask.raw_result || "-"}
                  </pre>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </main>
    </section>
  );
}
