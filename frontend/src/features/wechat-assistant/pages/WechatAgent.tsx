import {
  CheckCircle2Icon,
  ClockIcon,
  CopyIcon,
  BanIcon,
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
  fetchPendingWechatTasks,
  fetchLocalAgentRuntimeStatus,
  fetchStaffList,
  pollAndExecuteWechatTask,
  updateStaff,
} from "../api";
import type { LocalAgentRuntimeStatus, PollAndExecuteResponse, Staff, WechatTask } from "../types";

const DEFAULT_TEST_NICKNAME = "Aw3";
const SOURCE_START_COMMAND = "cd E:\\work\\project\\auto_wechat\npython app\\local_agent_main.py --host 127.0.0.1 --port 19000 --server-url http://127.0.0.1:9000";
const EXE_START_COMMAND = 'Start-Process ".\\dist\\local-agent\\小高AI微信助手.exe"';

function formatTime(value?: string | null): string {
  return formatDateTimeLocal(value || null);
}

function taskStatusText(status?: string | null): string {
  if (status === "pending") return "待处理";
  if (status === "running") return "执行中";
  if (status === "pasted") return "已完成";
  if (status === "blocked") return "已阻断";
  if (status === "failed") return "失败";
  if (status === "completed") return "已完成";
  return status || "-";
}

function taskTypeText(taskType?: string | null): string {
  if (taskType === "notify_sales") return "通知销售";
  if (taskType === "detect_reply") return "回复检测";
  return taskType || "-";
}

function shortText(value?: string | null, max = 42): string {
  const text = (value || "").trim();
  if (!text) return "-";
  return text.length > max ? `${text.slice(0, max)}...` : text;
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

export default function WechatAgent() {
  const [agentStatus, setAgentStatus] = useState<AgentStatusData | null>(null);
  const [localOnline, setLocalOnline] = useState<boolean | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<LocalAgentRuntimeStatus | null>(null);
  const [staffList, setStaffList] = useState<Staff[]>([]);
  const [pendingTasks, setPendingTasks] = useState<WechatTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [savingStaff, setSavingStaff] = useState(false);
  const [staffActionId, setStaffActionId] = useState<number | null>(null);
  const [testing, setTesting] = useState(false);
  const [testNickname, setTestNickname] = useState(DEFAULT_TEST_NICKNAME);
  const [testMessage, setTestMessage] = useState("小高AI微信助手测试消息");
  const [realSendRequested, setRealSendRequested] = useState(false);
  const [testResult, setTestResult] = useState<{
    createdTaskId?: number;
    localAgentOnline?: boolean;
    executed?: boolean;
    pollResult?: PollAndExecuteResponse | null;
    message: string;
  } | null>(null);
  const [staffKeyword, setStaffKeyword] = useState("");
  const [staffStatusFilter, setStaffStatusFilter] = useState<"all" | "active" | "disabled">("all");
  const [editingStaffId, setEditingStaffId] = useState<number | null>(null);
  const [staffForm, setStaffForm] = useState({
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

  async function refreshPage() {
    setLoading(true);
    try {
      const [statusResponse, health, runtime, staffs, tasks] = await Promise.all([
        fetchAgentStatus().catch(() => null),
        checkLocalAgentHealth().catch(() => null),
        fetchLocalAgentRuntimeStatus().catch(() => null),
        fetchStaffList({
          status: staffStatusFilter,
          keyword: staffKeyword.trim() || undefined,
        }),
        fetchPendingWechatTasks({ limit: 20 }),
      ]);
      setAgentStatus(statusResponse?.data || null);
      setLocalOnline(Boolean(health?.success));
      setRuntimeStatus(runtime);
      setStaffList(staffs);
      setPendingTasks(tasks);
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
    setEditingStaffId(null);
    setStaffForm({
      name: "",
      wechat_nickname: "",
      wechat_id: "",
      phone: "",
      status: "active",
    });
  }

  function handleEditStaff(staff: Staff) {
    setEditingStaffId(staff.id);
    setStaffForm({
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
      if (editingStaffId) {
        await updateStaff(editingStaffId, {
          ...payload,
          status: staffForm.status as "active" | "disabled",
        });
      } else {
        await createStaff(payload);
      }
      resetStaffForm();
      toast.success(editingStaffId ? "销售微信已更新" : "销售微信已保存");
      await loadStaffList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存销售微信失败");
    } finally {
      setSavingStaff(false);
    }
  }

  async function handleStaffStatusAction(staff: Staff, action: "enable" | "disable" | "delete") {
    if (action === "delete") {
      const confirmed = window.confirm("删除后不再参与分配，历史记录保留。确认删除？");
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

    if (realSendRequested) {
      const confirmed = window.confirm(
        "当前版本仍受安全门禁保护：只会执行 paste_only 演练并保持 sent=false，不会自动按 Enter 真实发送微信消息。确认继续？",
      );
      if (!confirmed) return;
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

  const onlineText = agentOnlineText(agentStatus, localOnline);
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
                配置销售微信、查看本机 Agent 状态、执行测试和查看任务记录。
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
              {!localOnline ? (
                <div className="mt-3 space-y-2">
                  <div className="rounded bg-white/70 p-2">
                    <div className="mb-1 font-semibold">源码启动</div>
                    <pre className="whitespace-pre-wrap break-all font-mono text-[11px] leading-5">{SOURCE_START_COMMAND}</pre>
                    <button
                      onClick={() => void handleCopyCommand(SOURCE_START_COMMAND)}
                      className="mt-2 inline-flex h-8 items-center gap-2 rounded-md border border-rose-200 bg-white px-2 text-[11px] font-semibold text-rose-800"
                    >
                      <CopyIcon size={13} />
                      复制源码命令
                    </button>
                  </div>
                  <div className="rounded bg-white/70 p-2">
                    <div className="mb-1 font-semibold">exe 启动</div>
                    <pre className="whitespace-pre-wrap break-all font-mono text-[11px] leading-5">{EXE_START_COMMAND}</pre>
                    <button
                      onClick={() => void handleCopyCommand(EXE_START_COMMAND)}
                      className="mt-2 inline-flex h-8 items-center gap-2 rounded-md border border-rose-200 bg-white px-2 text-[11px] font-semibold text-rose-800"
                    >
                      <CopyIcon size={13} />
                      复制 exe 命令
                    </button>
                  </div>
                </div>
              ) : (
                <div className="mt-3 rounded bg-white/70 p-2 text-emerald-900">
                  最近任务结果：{runtimeStatus?.last_task_result ? shortText(JSON.stringify(runtimeStatus.last_task_result), 120) : "-"}
                </div>
              )}
            </div>
          </div>
        </section>

        <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-xs leading-6 text-blue-800">
          <div className="font-bold">启动说明</div>
          <div>请在当前使用微信的 Windows 电脑启动 小高AI微信助手。网页按钮会调用当前电脑的 127.0.0.1:19000。</div>
          <div>宝塔服务器不能运行 19000；微信助手依赖本机微信窗口，任务执行前需要 Local Agent 在线。</div>
        </div>

        <div className="mt-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-xs leading-6 text-slate-700">
          <div className="font-bold text-slate-900">构建与分发说明</div>
          <div>当前页面不提供在线下载；一期验收请使用构建产物或人工分发的完整目录。</div>
          <div>
            产物路径：
            <span className="mx-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-800">
              dist/local-agent/小高AI微信助手.exe
            </span>
          </div>
          <div>
            局域网构建需指定主系统地址：
            <span className="mx-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-800">
              -ServerUrl http://192.168.110.113:9000
            </span>
          </div>
          <div className="font-semibold text-amber-700">安全边界：notify_sales 只允许 paste_only，detect_reply 只读检测，结果必须保持 sent=false。</div>
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <section className="rounded-lg border border-[#dfe5ee] bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#edf1f6] px-4 py-3">
              <div className="flex items-center gap-2">
                <UserPlusIcon size={16} className="text-blue-600" />
                <h2 className="text-sm font-bold text-[#1a1f2e]">销售微信配置</h2>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    value={staffKeyword}
                    onChange={(event) => setStaffKeyword(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void loadStaffList();
                    }}
                    className="h-9 w-48 rounded-md border border-slate-200 pl-8 pr-3 text-xs outline-none focus:border-blue-300"
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
                <select
                  value={staffForm.status}
                  onChange={(event) => setStaffForm((prev) => ({ ...prev, status: event.target.value }))}
                  className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-300"
                >
                  <option value="active">启用</option>
                  <option value="disabled">停用</option>
                </select>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                {editingStaffId ? (
                  <button
                    onClick={resetStaffForm}
                    className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <XIcon size={14} />
                    取消编辑
                  </button>
                ) : null}
                <button
                  onClick={() => void handleSaveStaff()}
                  disabled={savingStaff}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-4 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {savingStaff ? <Loader2Icon size={14} className="animate-spin" /> : <CheckCircle2Icon size={14} />}
                  {editingStaffId ? "保存修改" : "新增销售"}
                </button>
              </div>
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

          <section className="rounded-lg border border-[#dfe5ee] bg-white">
            <div className="flex items-center gap-2 border-b border-[#edf1f6] px-4 py-3">
              <ShieldCheckIcon size={16} className="text-emerald-600" />
              <h2 className="text-sm font-bold text-[#1a1f2e]">测试</h2>
            </div>
            <div className="space-y-3 p-4">
              <div className="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)]">
                <input
                  value={testNickname}
                  onChange={(event) => setTestNickname(event.target.value)}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="微信昵称，可选"
                />
                <input
                  value={testMessage}
                  onChange={(event) => setTestMessage(event.target.value)}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="测试内容，必填"
                />
              </div>
              <label className="flex items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-800">
                <span>
                  <span className="block font-bold">是否真实发送</span>
                  <span className="mt-1 block">当前安全门禁不开放自动真实发送；开启后仍只执行 paste_only 演练。</span>
                </span>
                <input
                  type="checkbox"
                  checked={realSendRequested}
                  onChange={(event) => setRealSendRequested(event.target.checked)}
                  className="h-4 w-4"
                />
              </label>
              <div className="flex justify-end">
                <button
                  onClick={() => void handleRunTest()}
                  disabled={testing || !testMessage.trim()}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-emerald-600 px-4 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
                >
                  {testing ? <Loader2Icon size={14} className="animate-spin" /> : <PlayIcon size={14} />}
                  开始测试
                </button>
              </div>
              {testResult ? (
                <div className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-700 sm:grid-cols-2">
                  <div>Local Agent：{testResult.localAgentOnline ? "在线" : "离线"}</div>
                  <div>任务：{testResult.createdTaskId ? `#${testResult.createdTaskId}` : "未创建"}</div>
                  <div>执行：{testResult.executed ? "已执行" : "未执行"}</div>
                  <div>发送：{testResult.pollResult?.action?.sent ? "已发送" : "未发送"}</div>
                  <div className="sm:col-span-2">结果：{testResult.message}</div>
                </div>
              ) : null}
            </div>
          </section>
        </div>

        <section className="mt-5 rounded-lg border border-[#dfe5ee] bg-white">
          <div className="flex items-center justify-between border-b border-[#edf1f6] px-4 py-3">
            <div className="flex items-center gap-2">
              <SendIcon size={16} className="text-blue-600" />
              <h2 className="text-sm font-bold text-[#1a1f2e]">任务记录</h2>
            </div>
            <span className="text-xs text-[#8b95a6]">待处理任务 {pendingTasks.length} 条</span>
          </div>
          <div className="overflow-auto">
            <table className="w-full min-w-[860px] text-left text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-semibold">创建时间</th>
                  <th className="px-4 py-3 font-semibold">微信昵称</th>
                  <th className="px-4 py-3 font-semibold">任务类型</th>
                  <th className="px-4 py-3 font-semibold">内容摘要</th>
                  <th className="px-4 py-3 font-semibold">状态</th>
                  <th className="px-4 py-3 font-semibold">执行时间</th>
                  <th className="px-4 py-3 font-semibold">失败原因</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {pendingTasks.length ? (
                  pendingTasks.map((task) => (
                    <tr key={task.id} className="bg-white">
                      <td className="px-4 py-3 text-slate-600">{formatTime(task.created_at)}</td>
                      <td className="px-4 py-3 font-semibold text-slate-800">{task.target_nickname || "-"}</td>
                      <td className="px-4 py-3 text-slate-600">{taskTypeText(task.task_type)}</td>
                      <td className="px-4 py-3 text-slate-600">{shortText(task.message)}</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-1 font-semibold text-amber-700">
                          <ClockIcon size={12} />
                          {taskStatusText(task.status)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{formatTime(task.pasted_at || task.sent_at)}</td>
                      <td className="px-4 py-3 text-slate-600">{task.failure_stage || "-"}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-slate-500">暂无待处理任务</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </section>
  );
}
