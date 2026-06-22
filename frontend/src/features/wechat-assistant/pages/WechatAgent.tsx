import {
  CheckCircle2Icon,
  ClockIcon,
  Loader2Icon,
  MessageCircleIcon,
  PlayIcon,
  RefreshCwIcon,
  SendIcon,
  ShieldCheckIcon,
  UserPlusIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { fetchAgentStatus } from "../../../api/agent";
import type { AgentStatusData } from "../../../api/types";
import { formatDateTimeLocal } from "../../../lib/datetime";
import {
  checkLocalAgentHealth,
  createStaff,
  createWechatTask,
  fetchPendingWechatTasks,
  fetchStaffList,
  pollAndExecuteWechatTask,
} from "../api";
import type { PollAndExecuteResponse, Staff, WechatTask } from "../types";

const DEFAULT_TEST_NICKNAME = "Aw3";

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

export default function WechatAgent() {
  const [agentStatus, setAgentStatus] = useState<AgentStatusData | null>(null);
  const [localOnline, setLocalOnline] = useState<boolean | null>(null);
  const [staffList, setStaffList] = useState<Staff[]>([]);
  const [pendingTasks, setPendingTasks] = useState<WechatTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [creatingStaff, setCreatingStaff] = useState(false);
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
  const [newStaffName, setNewStaffName] = useState("");
  const [newWechatNickname, setNewWechatNickname] = useState("");
  const [newStaffRemark, setNewStaffRemark] = useState("");

  const activeStaff = useMemo(
    () => staffList.filter((staff) => staff.status === "active"),
    [staffList],
  );

  async function refreshPage() {
    setLoading(true);
    try {
      const [statusResponse, health, staffs, tasks] = await Promise.all([
        fetchAgentStatus().catch(() => null),
        checkLocalAgentHealth().catch(() => null),
        fetchStaffList("active"),
        fetchPendingWechatTasks({ limit: 20 }),
      ]);
      setAgentStatus(statusResponse?.data || null);
      setLocalOnline(Boolean(health?.success));
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

  async function handleCreateStaff() {
    const name = newStaffName.trim();
    const wechatNickname = newWechatNickname.trim();
    if (!name || !wechatNickname) {
      toast.warning("请填写销售名称和微信昵称");
      return;
    }
    setCreatingStaff(true);
    try {
      await createStaff({
        name,
        wechat_nickname: wechatNickname,
      });
      setNewStaffName("");
      setNewWechatNickname("");
      setNewStaffRemark("");
      toast.success("销售微信已保存");
      await refreshPage();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存销售微信失败");
    } finally {
      setCreatingStaff(false);
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
            <div className="flex items-center gap-2 border-b border-[#edf1f6] px-4 py-3">
              <UserPlusIcon size={16} className="text-blue-600" />
              <h2 className="text-sm font-bold text-[#1a1f2e]">配置销售微信</h2>
            </div>
            <div className="space-y-3 p-4">
              <div className="grid gap-3 md:grid-cols-3">
                <input
                  value={newStaffName}
                  onChange={(event) => setNewStaffName(event.target.value)}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="销售名称"
                />
                <input
                  value={newWechatNickname}
                  onChange={(event) => setNewWechatNickname(event.target.value)}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="微信昵称"
                />
                <input
                  value={newStaffRemark}
                  onChange={(event) => setNewStaffRemark(event.target.value)}
                  className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-300"
                  placeholder="备注（仅页面记录）"
                />
              </div>
              <div className="flex justify-end">
                <button
                  onClick={() => void handleCreateStaff()}
                  disabled={creatingStaff}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-4 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {creatingStaff ? <Loader2Icon size={14} className="animate-spin" /> : <CheckCircle2Icon size={14} />}
                  保存销售微信
                </button>
              </div>
              <div className="overflow-hidden rounded-md border border-slate-200">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="px-3 py-2 font-semibold">销售名称</th>
                      <th className="px-3 py-2 font-semibold">微信昵称</th>
                      <th className="px-3 py-2 font-semibold">状态</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {activeStaff.length ? (
                      activeStaff.map((staff) => (
                        <tr key={staff.id} className="bg-white">
                          <td className="px-3 py-2 font-semibold text-slate-800">{staff.name}</td>
                          <td className="px-3 py-2 text-slate-600">{staff.wechat_nickname || "-"}</td>
                          <td className="px-3 py-2 text-emerald-600">启用</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={3} className="px-3 py-8 text-center text-slate-500">暂无销售微信配置</td>
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
