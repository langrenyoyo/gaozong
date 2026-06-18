import {
  CheckCircle2Icon,
  ClockIcon,
  DownloadIcon,
  MessageCircleIcon,
  OctagonAlertIcon,
  PauseIcon,
  PlayIcon,
  RefreshCwIcon,
  TestTube2Icon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import LocalWechatAgentTestPanel from "../components/LocalWechatAgentTestPanel";
import WechatTaskPanel from "../components/WechatTaskPanel";

import { fetchChecks } from "../api/checks";
import { fetchStaffList } from "../api/staff";
import { fetchWechatDebug, activateWechatWindow } from "../api/wechat";
import { fetchWechatAutoDetectStatus } from "../api/wechatAutoDetect";
import {
  fetchAutomationStatus,
  emergencyStopAutomation,
  resumeAutomation,
} from "../api/automation";
import { syncDouyinLeads } from "../api/integrations";
import { formatDateTimeLocal } from "../lib/datetime";
import type { CheckRecord, Staff, WechatAutoDetectStatus, AutomationStatus, DouyinSyncResponse } from "../api/types";
import type { WechatDebugResult } from "../api/wechat";

// ========== 检测状态配置 ==========

const CHECK_STATUS_OPTIONS = ["pending", "replied", "timeout", "invalid"] as const;

const CHECK_STATUS_LABELS: Record<string, string> = {
  pending: "待检测",
  replied: "已回复",
  timeout: "已超时",
  invalid: "无效回复",
};

const CHECK_STATUS_TONES: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  replied: "bg-emerald-100 text-emerald-700",
  timeout: "bg-red-100 text-red-700",
  invalid: "bg-slate-100 text-slate-700",
};

function checkStatusLabel(status: string): string {
  return CHECK_STATUS_LABELS[status] || status;
}

function checkStatusTone(status: string): string {
  return CHECK_STATUS_TONES[status] || "bg-slate-100 text-slate-700";
}

function formatTime(value: string | null): string {
  return formatDateTimeLocal(value);
}

// ========== 主页面 ==========

export default function WechatAgent() {
  const [wechatDebug, setWechatDebug] = useState<WechatDebugResult | null>(null);
  const [wechatDebugLoading, setWechatDebugLoading] = useState(false);
  const [activateLoading, setActivateLoading] = useState(false);

  // 检测记录 API 状态
  const [checks, setChecks] = useState<CheckRecord[]>([]);
  const [staffList, setStaffList] = useState<Staff[]>([]);
  const [checksLoading, setChecksLoading] = useState(true);
  const [checksError, setChecksError] = useState<string | null>(null);
  const [checkStatusFilter, setCheckStatusFilter] = useState<string>("all");

  // 自动检测状态
  const [autoDetectStatus, setAutoDetectStatus] = useState<WechatAutoDetectStatus | null>(null);
  const prevLastResultRef = useRef<string | null>(null);

  // 自动化控制状态
  const [automationStatus, setAutomationStatus] = useState<AutomationStatus | null>(null);
  const [automationLoading, setAutomationLoading] = useState(false);

  // 自动同步派单状态（P8-3）
  const [autoSyncEnabled, setAutoSyncEnabled] = useState(false);
  const [autoSyncLoading, setAutoSyncLoading] = useState(false);
  const [lastSyncResult, setLastSyncResult] = useState<DouyinSyncResponse | null>(null);
  const [lastSyncTime, setLastSyncTime] = useState<string | null>(null);
  const autoSyncTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 微信状态：从真实 API 检测
  const wechatStatus = wechatDebug
    ? wechatDebug.success && wechatDebug.wechat_found
      ? { label: "已检测到微信", className: "bg-emerald-50 text-emerald-700", detail: wechatDebug.title || "未知窗口" }
      : { label: "未检测到微信", className: "bg-red-50 text-red-700", detail: wechatDebug.error || "请确认本机已启动微信" }
    : { label: "未检测", className: "bg-slate-100 text-slate-700", detail: "点击刷新检测" };

  /** 调用 auto_wechat 调试接口检测本机微信状态 */
  const refreshWechatStatus = async () => {
    setWechatDebugLoading(true);
    try {
      const result = await fetchWechatDebug();
      setWechatDebug(result);
      if (result.success && result.wechat_found) {
        toast.success(`微信已检测到${result.title ? "：" + result.title : ""}`);
      } else {
        toast.warning("未检测到微信，请确认微信已在本机启动");
      }
    } catch {
      setWechatDebug({ success: false, wechat_found: false, title: null, message_list_found: false, input_box_found: false, error: "接口请求失败" });
      toast.error("微信状态检测失败");
    } finally {
      setWechatDebugLoading(false);
    }
  };

  /** 激活微信窗口并移动到右上角，然后刷新状态 */
  const handleActivateWechat = async () => {
    setActivateLoading(true);
    try {
      const result = await activateWechatWindow();
      if (result.success) {
        toast.success(result.message);
        // 激活成功后刷新微信状态
        await refreshWechatStatus();
      } else {
        toast.error(result.message || "激活微信窗口失败");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "激活微信窗口请求失败");
    } finally {
      setActivateLoading(false);
    }
  };

  /** 紧急停止所有自动化 */
  const handleEmergencyStop = async () => {
    if (!window.confirm("确认紧急停止所有微信自动化操作？\n\n停止后：搜索联系人、发送消息、自动检测等操作将被拒绝，直到恢复。")) return;
    setAutomationLoading(true);
    try {
      const result = await emergencyStopAutomation("前端手动停止");
      if (result.success) {
        toast.error("⚠️ 自动化已紧急停止");
        // 立即刷新状态
        const status = await fetchAutomationStatus();
        setAutomationStatus(status);
      } else {
        toast.error(result.message || "停止失败");
      }
    } catch {
      toast.error("紧急停止请求失败");
    } finally {
      setAutomationLoading(false);
    }
  };

  /** 恢复自动化 */
  const handleResumeAutomation = async () => {
    setAutomationLoading(true);
    try {
      const result = await resumeAutomation();
      if (result.success) {
        toast.success("✅ 自动化已恢复");
        const status = await fetchAutomationStatus();
        setAutomationStatus(status);
      } else {
        toast.error(result.message || "恢复失败");
      }
    } catch {
      toast.error("恢复自动化请求失败");
    } finally {
      setAutomationLoading(false);
    }
  };

  // staffId → staffName 映射
  const staffMap = new Map<number, string>();
  for (const s of staffList) {
    staffMap.set(s.id, s.name);
  }
  const getStaffName = (staffId: number) => staffMap.get(staffId) || `销售#${staffId}`;

  /** P8-3：执行一次同步派单 */
  const doAutoSync = async () => {
    // 每次同步前检查自动化状态
    try {
      const autoStatus = await fetchAutomationStatus();
      setAutomationStatus(autoStatus);
      if (autoStatus.emergency_stopped) {
        toast.warning("⚠️ 自动化已停止，自动同步已暂停");
        stopAutoSync();
        return;
      }
    } catch {
      // 状态查询失败不阻止同步
    }

    setAutoSyncLoading(true);
    try {
      const result = await syncDouyinLeads({
        dryRun: false,
        autoAssign: true,
        autoNotify: true,
      });
      setLastSyncResult(result);
      setLastSyncTime(new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));

      if (result.success && result.created > 0) {
        toast.success(`同步：新建${result.created}条，分配${result.assigned}条${result.notified > 0 ? `，通知${result.notified}条` : ""}`);
      }

      // 同步后刷新检测记录
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "自动同步失败");
    } finally {
      setAutoSyncLoading(false);
    }
  };

  /** 启动自动同步定时器 */
  const startAutoSync = () => {
    if (autoSyncTimerRef.current) return;
    setAutoSyncEnabled(true);
    // 立即执行一次
    doAutoSync();
    // 每 30 秒执行一次
    autoSyncTimerRef.current = setInterval(doAutoSync, 30000);
    toast.info("自动同步已启动，每 30 秒拉取新线索并自动派单通知");
  };

  /** 停止自动同步定时器 */
  const stopAutoSync = () => {
    if (autoSyncTimerRef.current) {
      clearInterval(autoSyncTimerRef.current);
      autoSyncTimerRef.current = null;
    }
    setAutoSyncEnabled(false);
    toast.info("自动同步已停止");
  };

  // 加载检测记录 + 销售列表（供多处调用）
  const loadData = async () => {
    setChecksLoading(true);
    setChecksError(null);
    try {
      const [checksData, staffData] = await Promise.all([
        fetchChecks(),
        fetchStaffList("active"),
      ]);
      setChecks(checksData);
      setStaffList(staffData);
    } catch (err) {
      setChecksError(err instanceof Error ? err.message : "检测记录加载失败");
    } finally {
      setChecksLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // 前端状态筛选
  const filteredChecks = checkStatusFilter === "all"
    ? checks
    : checks.filter((c) => c.check_status === checkStatusFilter);

  // 统计卡片（从检测记录计算）
  const checksStats = [
    { label: "检测总数", value: checks.length },
    { label: "待检测", value: checks.filter((c) => c.check_status === "pending").length },
    { label: "已回复", value: checks.filter((c) => c.check_status === "replied").length },
    { label: "已超时", value: checks.filter((c) => c.check_status === "timeout").length },
  ];

  // 自动检测轮询：每 10 秒刷新状态 + checks + 自动化状态
  useEffect(() => {
    const poll = async () => {
      try {
        const [statusRes, checksRes, autoStatusRes] = await Promise.all([
          fetchWechatAutoDetectStatus(),
          fetchChecks(),
          fetchAutomationStatus().catch(() => null),
        ]);
        setAutoDetectStatus(statusRes);
        setChecks(checksRes);
        if (autoStatusRes) setAutomationStatus(autoStatusRes);

        // 自动同步联动：紧急停止时自动停定时器
        if (autoStatusRes?.emergency_stopped && autoSyncTimerRef.current) {
          if (autoSyncTimerRef.current) {
            clearInterval(autoSyncTimerRef.current);
            autoSyncTimerRef.current = null;
          }
          setAutoSyncEnabled(false);
        }

        // 检测命中通知（避免重复 toast）
        if (
          statusRes.last_result?.startsWith("replied:") &&
          prevLastResultRef.current !== statusRes.last_result
        ) {
          toast.success("自动检测到有效回复，线索已跟进");
        }
        prevLastResultRef.current = statusRes.last_result ?? null;
      } catch {
        // 轮询失败不报错
      }
    };

    poll();
    const timer = setInterval(poll, 10000);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#dcfce7] text-[#16a34a]">
              <MessageCircleIcon size={24} />
            </div>
            <div>
              <h1 className="text-[15px] font-bold text-[#1a1f2e]">小高AI微信助手</h1>
              <p className="mt-1 text-xs text-[#8b95a6]">下载并启动微信客户端，配置自动执行规则</p>
              <span className="mt-2 inline-flex rounded-lg bg-[#f8fafc] px-2.5 py-1 text-[11px] font-semibold text-[#64748b]">
                建议安装路径：C:\Program Files\Tencent\WeChat
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center overflow-hidden rounded-xl border border-[#e4e8f0] bg-white">
              <span className={`px-3 py-2 text-xs font-semibold ${wechatStatus.className}`}>
                微信状态：{wechatStatus.label}
              </span>
              {wechatDebug?.success && wechatDebug.wechat_found ? (
                <span className="border-l border-[#e4e8f0] px-3 py-2 text-[10px] text-[#64748b]">
                  {wechatStatus.detail}
                  {wechatDebug.input_box_found ? " · 可写入" : ""}
                  {wechatDebug.message_list_found ? " · 可读取" : ""}
                </span>
              ) : null}
              <button
                onClick={refreshWechatStatus}
                disabled={wechatDebugLoading}
                className="flex h-9 items-center gap-1.5 border-l border-[#e4e8f0] px-3 text-xs font-semibold text-[#374151] transition-smooth hover:bg-[#f8fafc] disabled:opacity-60"
              >
                {wechatDebugLoading ? (
                  <RefreshCwIcon size={14} className="animate-spin" />
                ) : (
                  <RefreshCwIcon size={14} />
                )}
                刷新
              </button>
            </div>

            {/* 紧急停止 / 恢复自动化按钮 */}
            {automationStatus?.emergency_stopped ? (
              <button
                onClick={handleResumeAutomation}
                disabled={automationLoading}
                className="flex h-9 items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 text-xs font-semibold text-emerald-700 transition-colors hover:bg-emerald-100 disabled:opacity-50"
                title="恢复自动化：允许搜索联系人、发送消息、自动检测"
              >
                <PlayIcon size={14} />
                恢复自动化
              </button>
            ) : (
              <button
                onClick={handleEmergencyStop}
                disabled={automationLoading}
                className="flex h-9 items-center gap-1.5 rounded-xl border border-red-200 bg-red-50 px-3 text-xs font-semibold text-red-700 transition-colors hover:bg-red-100 disabled:opacity-50"
                title="紧急停止：拒绝所有微信自动化操作"
              >
                <OctagonAlertIcon size={14} />
                紧急停止自动化
              </button>
            )}

            <button className="flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-3 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
              <DownloadIcon size={14} />
              立即下载
            </button>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        <section className="min-h-0 overflow-y-auto bg-[#f3f6fa] p-5">
          <LocalWechatAgentTestPanel />

          {/* P0-5A-3：微信任务队列面板 */}
          <WechatTaskPanel />

          {/* 统计卡片 */}
          <div className="rounded-xl border border-[#e4e8f0] bg-white p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
                  <MessageCircleIcon size={22} />
                </div>
                <div>
                  <h2 className="text-[15px] font-bold text-[#1a1f2e]">回复检测记录</h2>
                  <p className="mt-2 text-xs text-[#64748b]">
                    微信助手规则配置暂未接入真实接口；当前仅展示真实检测记录、任务队列和本机微信助手联调能力。
                  </p>
                </div>
              </div>
              <div className="shrink-0">
                <button
                  onClick={handleActivateWechat}
                  disabled={activateLoading}
                  title="将主机微信窗口置顶并移动到右上角，用于人工确认和调试。"
                  className="flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] transition-smooth enabled:hover:bg-white disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {activateLoading ? (
                    <RefreshCwIcon size={14} className="animate-spin" />
                  ) : (
                    <TestTube2Icon size={14} />
                  )}
                  启动微信测试
                </button>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-4 gap-0 overflow-hidden rounded-xl border border-[#e4e8f0] bg-white">
              {checksStats.map((stat) => (
                <div key={stat.label} className="border-r border-[#f0f2f7] bg-white p-4 text-center last:border-r-0">
                  <div className="text-2xl font-bold text-[#1a1f2e]">{stat.value}</div>
                  <div className="mt-1 text-xs text-[#64748b]">{stat.label}</div>
                </div>
              ))}
            </div>

            {/* 检测结果详情 */}
            {wechatDebug ? (
              <div className="mt-4 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-4 py-3 text-xs">
                <p className="font-semibold text-[#1a1f2e]">检测结果</p>
                <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">微信窗口</span>
                    <span className={wechatDebug.wechat_found ? "font-semibold text-emerald-700" : "font-semibold text-red-600"}>
                      {wechatDebug.wechat_found ? "已检测" : "未检测"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">当前标题</span>
                    <span className="font-semibold text-[#374151]">{wechatDebug.title || "未识别"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">输入框</span>
                    <span className={wechatDebug.input_box_found ? "font-semibold text-emerald-700" : "font-semibold text-red-600"}>
                      {wechatDebug.input_box_found ? "可写入" : "不可写入"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">消息列表</span>
                    <span className={wechatDebug.message_list_found ? "font-semibold text-emerald-700" : "font-semibold text-red-600"}>
                      {wechatDebug.message_list_found ? "可读取" : "不可读取"}
                    </span>
                  </div>
                </div>
                {wechatDebug.error ? (
                  <div className="mt-2 rounded-lg border border-red-200 bg-red-50 px-2 py-1.5 text-[10px] text-red-600">
                    {wechatDebug.error}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          {/* 自动同步派单面板（P8-3） */}
          <div className="mt-5 rounded-xl border border-[#e4e8f0] bg-white p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="grid h-8 w-8 place-items-center rounded-lg bg-violet-50 text-violet-600">
                  <RefreshCwIcon size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-[#1a1f2e]">自动同步派单</h3>
                  <p className="text-[11px] text-[#8b95a6]">每 30 秒从 douyinAPI 拉取新线索，自动分配并通知销售</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {autoSyncEnabled ? (
                  <button
                    onClick={stopAutoSync}
                    className="flex h-9 items-center gap-1.5 rounded-xl border border-red-200 bg-red-50 px-3 text-xs font-semibold text-red-700 transition-colors hover:bg-red-100"
                  >
                    <PauseIcon size={14} />
                    停止自动同步
                  </button>
                ) : (
                  <button
                    onClick={startAutoSync}
                    disabled={automationStatus?.emergency_stopped === true}
                    className="flex h-9 items-center gap-1.5 rounded-xl bg-violet-600 px-3 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(139,92,246,0.22)] transition-colors hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {autoSyncLoading ? (
                      <RefreshCwIcon size={14} className="animate-spin" />
                    ) : (
                      <PlayIcon size={14} />
                    )}
                    启动自动同步
                  </button>
                )}
                {automationStatus?.emergency_stopped && (
                  <span className="text-[11px] text-red-600">⚠ 自动化已停止，无法启动</span>
                )}
              </div>
            </div>

            {/* 同步状态信息 */}
            {lastSyncResult ? (
              <div className="mt-3 grid grid-cols-5 gap-2">
                <div className="rounded-lg bg-[#f8fafc] px-3 py-2 text-center">
                  <div className="text-lg font-bold text-[#1a1f2e]">{lastSyncResult.created}</div>
                  <div className="text-[10px] text-[#8b95a6]">新建</div>
                </div>
                <div className="rounded-lg bg-[#f8fafc] px-3 py-2 text-center">
                  <div className="text-lg font-bold text-[#1a1f2e]">{lastSyncResult.updated}</div>
                  <div className="text-[10px] text-[#8b95a6]">更新</div>
                </div>
                <div className="rounded-lg bg-[#f8fafc] px-3 py-2 text-center">
                  <div className="text-lg font-bold text-[#1a1f2e]">{lastSyncResult.skipped}</div>
                  <div className="text-[10px] text-[#8b95a6]">跳过</div>
                </div>
                <div className="rounded-lg bg-blue-50 px-3 py-2 text-center">
                  <div className="text-lg font-bold text-blue-700">{lastSyncResult.assigned}</div>
                  <div className="text-[10px] text-blue-600">已分配</div>
                </div>
                <div className="rounded-lg bg-emerald-50 px-3 py-2 text-center">
                  <div className="text-lg font-bold text-emerald-700">{lastSyncResult.notified}</div>
                  <div className="text-[10px] text-emerald-600">已通知</div>
                </div>
              </div>
            ) : null}

            <div className="mt-2 flex items-center justify-between text-[11px] text-[#8b95a6]">
              <span>
                {autoSyncEnabled ? (
                  <span className="flex items-center gap-1 font-semibold text-emerald-600">
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
                    运行中 — 每 30 秒同步
                  </span>
                ) : (
                  "未启动"
                )}
              </span>
              {lastSyncTime && (
                <span>上次同步：{lastSyncTime}</span>
              )}
            </div>
          </div>

          {/* 自动检测状态面板 */}
          <div className="mt-5 rounded-xl border border-[#e4e8f0] bg-white p-4">
            <div className="flex items-center gap-2">
              <div className="grid h-8 w-8 place-items-center rounded-lg bg-blue-50 text-blue-600">
                <MessageCircleIcon size={16} />
              </div>
              <h3 className="text-sm font-bold text-[#1a1f2e]">自动检测</h3>
            </div>
            {/* 紧急停止警告 */}
            {automationStatus?.emergency_stopped ? (
              <div className="mt-3 rounded-lg border-2 border-red-300 bg-red-50 px-4 py-3">
                <div className="flex items-center gap-2 text-xs font-bold text-red-700">
                  <OctagonAlertIcon size={16} />
                  自动化已紧急停止
                </div>
                <p className="mt-1 text-[11px] text-red-600">
                  所有自动化操作已被拒绝。原因：{automationStatus.stop_reason ?? "手动停止"}
                  {automationStatus.stopped_at ? ` · 停止于 ${formatDateTimeLocal(automationStatus.stopped_at, {
                    month: "2-digit",
                    day: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}` : ""}
                </p>
                <button
                  onClick={handleResumeAutomation}
                  disabled={automationLoading}
                  className="mt-2 flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  <PlayIcon size={12} />
                  恢复自动化
                </button>
              </div>
            ) : null}
            {autoDetectStatus?.active_check_id ? (
              <div className="mt-3 grid gap-2 text-xs">
                <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">当前目标</span>
                    <span className="font-semibold text-[#374151]">
                      线索 #{autoDetectStatus.lead_id ?? "-"} · {autoDetectStatus.customer_name ?? "-"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">销售</span>
                    <span className="font-semibold text-[#374151]">{autoDetectStatus.staff_name ?? "-"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">状态</span>
                    <span className={`font-semibold ${autoDetectStatus.check_status === "pending" ? "text-amber-600" : "text-emerald-600"}`}>
                      {autoDetectStatus.check_status === "pending" ? "监听中" : autoDetectStatus.check_status === "replied" ? "已跟进" : autoDetectStatus.check_status ?? "-"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">间隔</span>
                    <span className="font-semibold text-[#374151]">每 {autoDetectStatus.interval_seconds} 秒</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">上次检测</span>
                    <span className="font-semibold text-[#374151]">{formatDateTimeLocal(autoDetectStatus.last_detect_at, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#8b95a6]">上次结果</span>
                    <span className="font-semibold text-[#374151]">{autoDetectStatus.last_result ?? "-"}</span>
                  </div>
                </div>
                {autoDetectStatus.warning ? (
                  <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-700">
                    ⚠ {autoDetectStatus.warning}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="mt-3 text-xs text-[#8b95a6]">
                <p>未设置自动检测目标</p>
                <p className="mt-1 text-[11px]">请在线索管理页选择一条 assigned 线索，点击「设为自动检测目标」即可开始自动检测。</p>
              </div>
            )}
          </div>

          {/* 检测记录列表 */}
          <div className="mt-5">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-bold text-[#1a1f2e]">检测记录</h3>
              <div className="flex items-center gap-2">
                <select
                  value={checkStatusFilter}
                  onChange={(event) => setCheckStatusFilter(event.target.value)}
                  className="h-8 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs font-semibold text-[#374151] outline-none"
                >
                  <option value="all">全部状态</option>
                  {CHECK_STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>{checkStatusLabel(s)}</option>
                  ))}
                </select>
                <span className="text-xs text-[#8b95a6]">
                  共 {filteredChecks.length} 条
                </span>
              </div>
            </div>

            {/* 加载状态 */}
            {checksLoading ? (
              <div className="rounded-xl border border-[#e4e8f0] bg-white px-4 py-8 text-center text-xs text-[#8b95a6]">
                加载中...
              </div>
            ) : checksError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-center text-xs text-red-600">
                {checksError}
              </div>
            ) : filteredChecks.length === 0 ? (
              <div className="rounded-xl border border-dashed border-[#d9e0ea] bg-white/60 px-4 py-6 text-center text-xs text-[#8b95a6]">
                暂无检测记录
              </div>
            ) : (
              <div className="space-y-2">
                {filteredChecks.map((check) => (
                  <div key={check.id} className="flex items-start justify-between gap-4 rounded-xl border border-[#e4e8f0] bg-white px-4 py-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-xs font-bold text-[#1a1f2e]">
                        <span>检测 #{check.id}</span>
                        <span className="text-[10px] font-normal text-[#8b95a6]">
                          线索 #{check.lead_id} · {getStaffName(check.staff_id)}
                        </span>
                      </div>
                      <div className="mt-1 text-xs text-[#64748b]">
                        {check.reply_content
                          ? check.reply_content.length > 60
                            ? check.reply_content.slice(0, 60) + "..."
                            : check.reply_content
                          : "暂无回复内容"}
                      </div>
                      {check.effectiveness_reason ? (
                        <div className="mt-1 text-[10px] text-[#8b95a6]">
                          判定：{check.effectiveness_reason}
                        </div>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1.5">
                      <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ${checkStatusTone(check.check_status)}`}>
                        <CheckCircle2Icon size={12} />
                        {checkStatusLabel(check.check_status)}
                      </span>
                      <div className="flex items-center gap-1 text-[10px] text-[#8b95a6]">
                        <ClockIcon size={10} />
                        {formatTime(check.checked_at || check.created_at)}
                      </div>
                      <div className="text-[10px] text-[#9ca3af]">
                        截止：{formatTime(check.reply_deadline)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </section>
  );
}
