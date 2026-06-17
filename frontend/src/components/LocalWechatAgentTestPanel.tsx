import {
  CheckCircle2Icon,
  Loader2Icon,
  MonitorCogIcon,
  PlayIcon,
  PlugZapIcon,
  SearchIcon,
  XCircleIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  checkLocalAgentHealth,
  checkLocalWechatOcrStatus,
  diagnoseLocalWechatForeground,
  diagnoseLocalWechatSearch,
  diagnoseLocalWechatSearchResult,
  diagnoseLocalWechatWindows,
  fetchLocalAgentVersion,
  getAgentServerUrl,
  LOCAL_AGENT_BASE_URL,
  startLocalWechatSearchCalibration,
  startLocalWechatTest,
  warmupLocalWechatOcr,
  type LocalAgentHealth,
  type LocalAgentVersion,
  type LocalWechatForegroundDebugResult,
  type LocalWechatOcrStatus,
  type LocalWechatSearchCalibrationResult,
  type LocalWechatSearchDebugResult,
  type LocalWechatSearchResultDebugResult,
  type LocalWechatTestResult,
  type LocalWechatWindowsDiagnostic,
} from "../api/localWechatAgent";
import type { AgentServerUrlResponse } from "../api/types";

const DEFAULT_PAYLOAD = {
  nickname: "Aw3",
  message: "[AUTO_WECHAT_TEST] P0-4A local agent paste only",
  mode: "paste_only" as const,
  engine: "easyocr",
  position: "right" as const,
  confirm_before_send: false,
};

function BooleanPill({ value, label }: { value?: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-semibold ${
        value ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"
      }`}
    >
      {value ? <CheckCircle2Icon size={12} /> : <XCircleIcon size={12} />}
      {label}: {value ? "true" : "false"}
    </span>
  );
}

export default function LocalWechatAgentTestPanel() {
  const [health, setHealth] = useState<LocalAgentHealth | null>(null);
  const [result, setResult] = useState<LocalWechatTestResult | null>(null);
  const [windowsDiagnostic, setWindowsDiagnostic] = useState<LocalWechatWindowsDiagnostic | null>(null);
  const [foregroundDiagnostic, setForegroundDiagnostic] = useState<LocalWechatForegroundDebugResult | null>(null);
  const [searchDiagnostic, setSearchDiagnostic] = useState<LocalWechatSearchDebugResult | null>(null);
  const [searchCalibration, setSearchCalibration] = useState<LocalWechatSearchCalibrationResult | null>(null);
  const [ocrStatus, setOcrStatus] = useState<LocalWechatOcrStatus | null>(null);
  const [offlineMessage, setOfflineMessage] = useState<string | null>(null);
  const [agentTestMessage, setAgentTestMessage] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [running, setRunning] = useState(false);
  const [warmingOcr, setWarmingOcr] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [foregroundChecking, setForegroundChecking] = useState(false);
  const [searchChecking, setSearchChecking] = useState(false);
  const [calibratingSearch, setCalibratingSearch] = useState(false);
  const [searchResultDiagnostic, setSearchResultDiagnostic] = useState<LocalWechatSearchResultDebugResult | null>(null);
  const [searchResultChecking, setSearchResultChecking] = useState(false);
  const [agentVersion, setAgentVersion] = useState<LocalAgentVersion | null>(null);
  const [serverUrlInfo, setServerUrlInfo] = useState<AgentServerUrlResponse | null>(null);

  const refreshHealth = async () => {
    setChecking(true);
    setOfflineMessage(null);
    try {
      const next = await checkLocalAgentHealth();
      setHealth(next);
      // Agent 在线时同时获取版本信息
      try {
        const ver = await fetchLocalAgentVersion();
        setAgentVersion(ver);
      } catch {
        setAgentVersion(null);
      }
      // P0-FE-MAIN-1: fetch server-url
      try {
        const urlInfo = await getAgentServerUrl();
        setServerUrlInfo(urlInfo);
      } catch {
        setServerUrlInfo(null);
      }
    } catch {
      setHealth(null);
      setAgentVersion(null);
      setServerUrlInfo(null);
      setOfflineMessage("未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手");
    } finally {
      setChecking(false);
    }
  };
  const refreshOcrStatus = async () => {
    try {
      const next = await checkLocalWechatOcrStatus();
      setOcrStatus(next);
      return next;
    } catch {
      return null;
    }
  };

  const handleRunTest = async () => {
    setRunning(true);
    setOfflineMessage(null);
    setAgentTestMessage("正在执行本机微信测试，请勿操作鼠标键盘...");
    const controller = new AbortController();
    const timers = [
      window.setTimeout(() => setAgentTestMessage("本机 Agent 仍在处理，请稍候..."), 10000),
      window.setTimeout(() => setAgentTestMessage("本机 Agent 仍在初始化 OCR。请确认已复制完整 dist\\小高AI微信助手 目录，不要只复制 exe。"), 60000),
      window.setTimeout(() => {
        controller.abort();
        setAgentTestMessage("本机微信测试超时，可能卡在 OCR 初始化或微信自动化步骤，请重启小高AI微信助手后重试。");
      }, 180000),
    ];
    try {
      const next = await startLocalWechatTest(DEFAULT_PAYLOAD, controller.signal);
      setResult(next);
      if (next.success) {
        toast.success("本机微信 Agent paste-only 测试完成");
      } else if (next.failure_stage === "ocr_model_missing") {
        const message = "小高AI微信助手缺少 OCR 模型文件，请重新复制完整 dist\\小高AI微信助手 目录，不要只复制 exe。";
        setAgentTestMessage(message);
        toast.error(message);
      } else if (next.failure_stage === "ocr_not_ready" || next.failure_stage === "ocr_initializing") {
        setAgentTestMessage("OCR 模型尚未就绪，请先点击 OCR 预热。");
        toast.warning("OCR 模型尚未就绪，请先点击 OCR 预热。");
      } else {
        toast.warning(next.message || "本机微信 Agent 测试未通过");
      }
    } catch (error) {
      if ((error as Error)?.name === "AbortError") {
        toast.error("本机微信测试超时");
      } else {
        setOfflineMessage("未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手");
        toast.error("本机微信 Agent 未启动");
      }
    } finally {
      timers.forEach((timer) => window.clearTimeout(timer));
      setRunning(false);
      refreshHealth();
      refreshOcrStatus();
    }
  };

  const handleWarmupOcr = async () => {
    setWarmingOcr(true);
    setOfflineMessage(null);
    try {
      const next = await warmupLocalWechatOcr();
      setOcrStatus(next);
      if (next.failure_stage === "ocr_model_missing") {
        toast.error(next.message || "小高AI微信助手缺少 OCR 模型文件，请重新复制完整 dist\\小高AI微信助手 目录，不要只复制 exe。");
      } else {
        toast.info(next.message || "OCR 模型正在初始化，请稍候");
      }
    } catch {
      setOfflineMessage("未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手");
      toast.error("OCR 预热请求失败");
    } finally {
      setWarmingOcr(false);
    }
  };

  const handleDiagnoseWindows = async () => {
    setDiagnosing(true);
    setOfflineMessage(null);
    try {
      const next = await diagnoseLocalWechatWindows();
      setWindowsDiagnostic(next);
      if (next.wechat_detected) {
        toast.success("已检测到本机微信窗口");
      } else {
        toast.warning("本机 Agent 已启动，但未找到微信窗口");
      }
    } catch {
      setOfflineMessage("未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手");
      toast.error("本机微信 Agent 未启动");
    } finally {
      setDiagnosing(false);
      refreshHealth();
    }
  };

  const handleDiagnoseForeground = async () => {
    setForegroundChecking(true);
    setOfflineMessage(null);
    try {
      const next = await diagnoseLocalWechatForeground({ position: "right" });
      setForegroundDiagnostic(next);
      if (next.foreground_success) {
        toast.success("微信前台焦点交接成功");
      } else {
        toast.warning(next.message || "微信前台焦点交接失败");
      }
    } catch {
      setOfflineMessage("未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手");
      toast.error("本机微信 Agent 未启动");
    } finally {
      setForegroundChecking(false);
      refreshHealth();
    }
  };

  const handleDiagnoseSearch = async () => {
    setSearchChecking(true);
    setOfflineMessage(null);
    try {
      const next = await diagnoseLocalWechatSearch({ nickname: "Aw3", position: "right" });
      setSearchDiagnostic(next);
      if (next.success && next.verified) {
        toast.success("搜索框诊断完成");
      } else {
        toast.warning(next.message || "搜索框诊断未通过");
      }
    } catch {
      setOfflineMessage("未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手");
      toast.error("本机微信 Agent 未启动");
    } finally {
      setSearchChecking(false);
      refreshHealth();
    }
  };

  const handleCalibrateSearch = async () => {
    setCalibratingSearch(true);
    setOfflineMessage(null);
    toast.info("请在 5 秒内把鼠标移动到微信搜索框中心，不要点击。");
    try {
      const next = await startLocalWechatSearchCalibration();
      setSearchCalibration(next);
      if (next.success) {
        toast.success(next.message || "搜索框坐标已保存");
      } else {
        toast.warning(next.message || "搜索框标定失败");
      }
    } catch {
      setOfflineMessage("未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手");
      toast.error("本机微信 Agent 未启动");
    } finally {
      setCalibratingSearch(false);
      refreshHealth();
    }
  };

  const handleDiagnoseSearchResult = async () => {
    setSearchResultChecking(true);
    setOfflineMessage(null);
    try {
      const next = await diagnoseLocalWechatSearchResult({ nickname: "Aw3", position: "right" });
      setSearchResultDiagnostic(next);
      if (next.success && next.search_result_detected) {
        toast.success("已定位到 Aw3 搜索结果行，可以继续启动微信测试。");
      } else if (next.search_text_verified && !next.search_result_detected) {
        toast.warning("未在搜索结果中识别到 Aw3，已阻止点击结果。");
      } else {
        toast.warning(next.message || "搜索结果诊断未通过");
      }
    } catch {
      setOfflineMessage("未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手");
      toast.error("本机微信 Agent 未启动");
    } finally {
      setSearchResultChecking(false);
      refreshHealth();
    }
  };

  useEffect(() => {
    refreshHealth();
    refreshOcrStatus();
  }, []);

  useEffect(() => {
    if (!ocrStatus?.initializing) {
      return;
    }
    const timer = window.setInterval(() => {
      refreshOcrStatus();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [ocrStatus?.initializing]);

  const foregroundDebug = foregroundDiagnostic?.foreground_debug || result?.foreground_debug || null;
  const searchFocus = searchDiagnostic?.search_focus || result?.open_chat?.search_focus || null;
  const openChatFailed = result?.failure_stage === "open_chat_failed";
  const verifyFailedAfterOpen = Boolean(
    result?.open_chat?.success &&
      !result?.success &&
      !result?.action?.pasted &&
      result?.failure_stage !== "open_chat_failed" &&
      (result?.verify?.manual_review_required || !result?.verify?.verified),
  );

  return (
    <div className="mb-5 rounded-xl border border-[#d8e1ec] bg-white p-4 shadow-[0_10px_30px_rgba(15,23,42,0.04)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eef6ff] text-[#2563eb]">
            <MonitorCogIcon size={21} />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[15px] font-bold text-[#1a1f2e]">本机 WeChat Agent</h2>
              <span className="rounded-md bg-[#f1f5f9] px-2 py-1 text-[11px] font-semibold text-[#475569]">
                {LOCAL_AGENT_BASE_URL}
              </span>
            </div>
            <p className="mt-1 text-xs text-[#64748b]">
              浏览器直连当前电脑的 127.0.0.1:19000，只验证 Aw3 paste-only，不调用主系统后端。            </p>
          </div>
        </div>

        <div className="flex gap-2">
          <button
            onClick={refreshHealth}
            disabled={checking}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs font-semibold text-[#374151] disabled:opacity-50"
          >
            {checking ? <Loader2Icon size={14} className="animate-spin" /> : <PlugZapIcon size={14} />}
            检查 Agent
          </button>
          <button
            onClick={handleDiagnoseWindows}
            disabled={diagnosing}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-[#dbe7f5] bg-white px-3 text-xs font-semibold text-[#1f4b7a] disabled:opacity-50"
          >
            {diagnosing ? <Loader2Icon size={14} className="animate-spin" /> : <SearchIcon size={14} />}
            诊断微信窗口
          </button>
          <button
            onClick={handleDiagnoseForeground}
            disabled={foregroundChecking}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-[#dbe7f5] bg-white px-3 text-xs font-semibold text-[#1f4b7a] disabled:opacity-50"
          >
            {foregroundChecking ? <Loader2Icon size={14} className="animate-spin" /> : <PlugZapIcon size={14} />}
            前台焦点诊断
          </button>
          <button
            onClick={handleDiagnoseSearch}
            disabled={searchChecking}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-[#dbe7f5] bg-white px-3 text-xs font-semibold text-[#1f4b7a] disabled:opacity-50"
          >
            {searchChecking ? <Loader2Icon size={14} className="animate-spin" /> : <SearchIcon size={14} />}
            搜索框诊断          </button>
          <button
            onClick={handleCalibrateSearch}
            disabled={calibratingSearch}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-3 text-xs font-semibold text-amber-700 disabled:opacity-50"
          >
            {calibratingSearch ? <Loader2Icon size={14} className="animate-spin" /> : <SearchIcon size={14} />}
            手动标定搜索框          </button>
          <button
            onClick={handleDiagnoseSearchResult}
            disabled={searchResultChecking}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-teal-200 bg-teal-50 px-3 text-xs font-semibold text-teal-700 disabled:opacity-50"
          >
            {searchResultChecking ? <Loader2Icon size={14} className="animate-spin" /> : <SearchIcon size={14} />}
            搜索结果诊断
          </button>
          <button
            onClick={handleWarmupOcr}
            disabled={warmingOcr || ocrStatus?.initializing}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-sky-200 bg-sky-50 px-3 text-xs font-semibold text-sky-700 disabled:opacity-50"
          >
            {warmingOcr || ocrStatus?.initializing ? <Loader2Icon size={14} className="animate-spin" /> : <PlugZapIcon size={14} />}
            OCR 预热
          </button>
          <button
            onClick={handleRunTest}
            disabled={running}
            className="flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-3 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:opacity-50"
          >
            {running ? <Loader2Icon size={14} className="animate-spin" /> : <PlayIcon size={14} />}
            启动微信测试
          </button>
        </div>
      </div>

      {offlineMessage ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
          {offlineMessage}
        </div>
      ) : null}

      {agentTestMessage ? (
        <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-semibold text-sky-700">
          {agentTestMessage}
        </div>
      ) : null}

      {ocrStatus?.failure_stage === "ocr_model_missing" ? (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700">
          小高AI微信助手缺少 OCR 模型文件，请重新复制完整 dist\小高AI微信助手 目录，不要只复制 exe。
        </div>
      ) : null}

      {ocrStatus?.model_source === "bundled" && ocrStatus?.model_ready ? (
        <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700">
          OCR 模型已内置，可以开始微信测试。OCR 不会在测试机联网下载模型。
        </div>
      ) : null}
      <div className="mt-4 grid gap-3 lg:grid-cols-4">

        <div className="rounded-lg border border-[#edf1f6] bg-[#f8fafc] p-3">
          <div className="text-[11px] font-semibold uppercase text-[#94a3b8]">Agent 状态</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <BooleanPill value={health?.success} label="online" />
            <BooleanPill value={health?.wechat_agent} label="wechat_agent" />
          </div>
          <div className="mt-2 text-[11px] text-[#64748b]">
            hostname: <span className="font-semibold text-[#334155]">{health?.agent_machine?.hostname || "-"}</span>
          </div>
          {/* P0-FE-MAIN-1: server_url 展示 */}
          <div className="mt-1 text-[11px] text-[#64748b]">
            {serverUrlInfo?.configured ? (
              <span className="font-semibold text-emerald-700">server_url: {serverUrlInfo.server_url}</span>
            ) : (
              <span className="font-semibold text-amber-600">server_url: 未配置（任务拉取不可用）</span>
            )}
          </div>
          {/* 版本信息 */}
          {agentVersion ? (
            <div className="mt-2 text-[11px] text-[#64748b]">
              <div>
                版本: <span className="font-semibold text-[#334155]">{agentVersion.build_version}</span>
                {agentVersion.exe_mode && (
                  <span className="ml-1 rounded bg-blue-50 px-1 text-blue-600">exe</span>
                )}
              </div>
              <div>
                构建: <span className="text-[#334155]">{agentVersion.build_time}</span>
                {" | "}
                commit: <span className="font-mono text-[#334155]">{agentVersion.git_commit}</span>
              </div>
              <div>
                路由数: <span className="font-semibold text-[#334155]">{agentVersion.routes?.length ?? "-"}</span>
              </div>
            </div>
          ) : null}
          {/* search-result-debug 路由缺失警告 */}
          {agentVersion && !agentVersion.routes?.includes("/agent/wechat/search-result-debug") && (
            <div className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] font-semibold text-red-700">
              ⚠ 当前运行的小高AI微信助手不包含搜索结果诊断接口（/agent/wechat/search-result-debug）。
              请确认已关闭旧进程，并复制完整 dist/小高AI微信助手 目录后重新启动。
            </div>
          )}
        </div>

        <div className="rounded-lg border border-[#edf1f6] bg-[#f8fafc] p-3">
          <div className="text-[11px] font-semibold uppercase text-[#94a3b8]">OCR 状态</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <BooleanPill value={ocrStatus?.ocr_available} label="available" />
            <BooleanPill value={ocrStatus?.ocr_initialized} label="ocr_initialized" />
            <BooleanPill value={ocrStatus?.model_ready} label="model_ready" />
            <BooleanPill value={ocrStatus?.initializing} label="initializing" />
          </div>
          <div className="mt-2 text-[11px] text-[#64748b]">
            last_error: <span className="font-semibold text-[#334155]">{ocrStatus?.last_error || "-"}</span>
          </div>
          <div className="mt-1 text-[11px] text-[#64748b]">
            cache_dir: <span className="font-mono text-[#334155]">{ocrStatus?.cache_dir || "-"}</span>
          </div>
          <div className="mt-1 text-[11px] text-[#64748b]">
            model_source: <span className="font-semibold text-[#334155]">{ocrStatus?.model_source || "-"}</span>
          </div>
          <div className="mt-1 text-[11px] text-[#64748b]">
            model_dir: <span className="font-mono text-[#334155]">{ocrStatus?.model_dir || "-"}</span>
          </div>
          <div className="mt-1 text-[11px] text-[#64748b]">
            download_enabled: <span className="font-semibold text-[#334155]">{String(ocrStatus?.download_enabled ?? "-")}</span>
          </div>
          <div className="mt-1 text-[11px] text-[#64748b]">
            model_files:{" "}
            <span className="font-semibold text-[#334155]">
              {ocrStatus?.model_files_count ?? "-"} / {ocrStatus?.model_total_size_mb ?? "-"} MB
            </span>
          </div>
          {ocrStatus?.download_enabled === false ? (
            <div className="mt-2 text-[11px] font-semibold text-emerald-700">
              OCR 不会在测试机联网下载模型。
            </div>
          ) : null}
        </div>

        <div className="rounded-lg border border-[#edf1f6] bg-[#f8fafc] p-3">
          <div className="text-[11px] font-semibold uppercase text-[#94a3b8]">open_chat</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <BooleanPill value={result?.open_chat?.success} label="success" />
            <BooleanPill value={result?.open_chat?.chat_verified} label="chat_verified" />
          </div>
          <div className="mt-2 text-[11px] text-[#64748b]">
            open_chat 不是最终联系人确认
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <BooleanPill value={result?.open_chat?.search_action_completed} label="search_action_completed" />
            <BooleanPill value={result?.open_chat?.search_keyword_pasted} label="search_keyword_pasted" />
            <BooleanPill value={result?.open_chat?.maybe_chat_opened} label="maybe_chat_opened" />
          </div>
          <div className="mt-2 text-[11px] text-[#64748b]">
            confidence:{" "}
            <span className="font-semibold text-[#334155]">{result?.open_chat?.confidence ?? "-"}</span>
            <span className="mx-2 text-[#cbd5e1]">|</span>
            stage: <span className="font-semibold text-[#334155]">{result?.open_chat?.failure_stage || "-"}</span>
          </div>
          {/* open_chat search_text_debug 诊断（P0-4A-6B-3） */}
          {(() => {
            const openChatDebug = result?.open_chat?.search_focus?.search_text_debug;
            if (!openChatDebug) return null;
            return (
              <div className="mt-2 rounded-lg border border-[#e2e8f0] bg-white p-2 text-[11px]">
                <div className="mb-1 font-semibold text-[#334155]">
                  search_text_debug（P0-4A-6B-3）
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[#64748b]">
                  <div>
                    method: <span className="font-medium text-[#334155]">{openChatDebug.method || "-"}</span>
                  </div>
                  <div>
                    verified: <BooleanPill value={openChatDebug.verified} label="" />
                  </div>
                  <div>
                    expected: <span className="font-mono text-[#334155]">{openChatDebug.expected || "-"}</span>
                  </div>
                  <div>
                    click_in_box: <BooleanPill value={openChatDebug.click_point_inside_search_box} label="" />
                  </div>
                  <div className="col-span-2">
                    搜索框 OCR: <span className="font-mono text-[#334155]">{openChatDebug.ocr_text || "(无)"}</span>
                  </div>
                  <div className="col-span-2">
                    归一化 OCR: <span className="font-mono text-[#334155]">{openChatDebug.normalized_ocr_text || "(无)"}</span>
                  </div>
                  <div className="col-span-2">
                    结果区 OCR: <span className="font-mono text-[#334155]">{openChatDebug.result_area_ocr_text ?? "(未采集)"}</span>
                  </div>
                  <div>
                    结果区包含: <BooleanPill value={openChatDebug.result_area_contains_expected ?? false} label="Aw3" />
                  </div>
                  <div>
                    泄漏检测: <BooleanPill value={!openChatDebug.text_leaked_to_chat_input} label="no_leak" />
                  </div>
                  {openChatDebug.reason ? (
                    <div className="col-span-2 text-amber-600">
                      原因: {openChatDebug.reason}
                    </div>
                  ) : null}
                  {openChatDebug.search_box_crop_path ? (
                    <div className="col-span-2">
                      搜索框裁剪: <span className="font-mono text-[#475569]">{openChatDebug.search_box_crop_path}</span>
                    </div>
                  ) : null}
                  {openChatDebug.result_area_crop_path ? (
                    <div className="col-span-2">
                      结果区裁剪: <span className="font-mono text-[#475569]">{openChatDebug.result_area_crop_path}</span>
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })()}
          {/* 复制 open_chat debug JSON */}
          {result?.open_chat && (
            <button
              type="button"
              className="mt-2 rounded border border-[#cbd5e1] bg-white px-2 py-1 text-[11px] text-[#475569] hover:bg-[#f1f5f9]"
              onClick={() => {
                try {
                  navigator.clipboard.writeText(JSON.stringify(result.open_chat, null, 2));
                  toast.success("已复制 open_chat debug JSON 到剪贴板");
                } catch {
                  toast.error("复制失败");
                }
              }}
            >
              复制 open_chat debug JSON
            </button>
          )}
          {/* search_text_not_verified 专用提示 */}
          {result?.open_chat?.failure_stage === "search_text_not_verified" && (
            <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] font-semibold text-amber-700">
              Aw3 已粘贴，但搜索文本验证失败。请查看 search_text_debug 的 OCR 文本、结果区证据和泄漏检测。
            </div>
          )}
          {/* 组合证据通过提示 */}
          {result?.open_chat?.search_focus?.search_text_debug?.method === "focused_search_box_with_result_aw3" && result?.open_chat?.success && (
            <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] font-semibold text-emerald-700">
              已通过搜索框定位 + 搜索结果 Aw3 + 未泄漏到聊天输入框确认搜索文本有效。
            </div>
          )}
        </div>

        <div className="rounded-lg border border-[#edf1f6] bg-[#f8fafc] p-3">
          <div className="text-[11px] font-semibold uppercase text-[#94a3b8]">验证结果</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <BooleanPill value={result?.verify?.verified} label="verified" />
            <BooleanPill value={result?.verify?.partial_match} label="partial" />
            <BooleanPill value={result?.verify?.manual_review_required} label="manual" />
          </div>
          <div className="mt-2 text-[11px] text-[#64748b]">
            strategy: <span className="font-semibold text-[#334155]">{result?.verify?.strategy || "-"}</span>
            <span className="mx-2 text-[#cbd5e1]">|</span>
            OCR: <span className="font-semibold text-[#334155]">{result?.verify?.ocr_text || "-"}</span>
          </div>
        </div>

        <div className="rounded-lg border border-[#edf1f6] bg-[#f8fafc] p-3">
          <div className="text-[11px] font-semibold uppercase text-[#94a3b8]">动作结果</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <BooleanPill value={result?.action?.pasted} label="pasted" />
            <BooleanPill value={result?.action?.sent} label="sent" />
          </div>
          <div className="mt-2 text-[11px] text-[#64748b]">
            failure_stage: <span className="font-semibold text-[#334155]">{result?.failure_stage || "-"}</span>
          </div>
        </div>
      </div>
      {openChatFailed ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
          微信已聚焦，但自动搜索/打开 Aw3 失败。
        </div>
      ) : null}

      {verifyFailedAfterOpen ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
          自动打开 Aw3 后，OCR 未确认顶部标题为 Aw3，已阻止粘贴。
        </div>
      ) : null}

      {windowsDiagnostic && !windowsDiagnostic.wechat_detected ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
          本机 Agent 已启动，但未找到微信窗口。请确认微信已打开、未最小化、未托盘隐藏，且 小高AI微信助手 与微信使用相同权限启动。        </div>
      ) : null}

      {windowsDiagnostic ? (
        <div className="mt-3 rounded-lg border border-[#edf1f6] bg-white p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <BooleanPill value={windowsDiagnostic.wechat_detected} label="wechat_detected" />
            <span className="font-semibold text-[#334155]">
              候选窗口：{windowsDiagnostic.wechat_candidates?.length || 0}
            </span>
            <span className="text-[#64748b]">
              agent: {windowsDiagnostic.agent_machine?.hostname || "-"}
            </span>
          </div>
          {windowsDiagnostic.wechat_candidates?.length ? (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-[11px]">
                <thead className="text-[#64748b]">
                  <tr className="border-b border-[#edf1f6]">
                    <th className="py-2 pr-2 font-semibold">hwnd</th>
                    <th className="py-2 pr-2 font-semibold">title</th>
                    <th className="py-2 pr-2 font-semibold">class_name</th>
                    <th className="py-2 pr-2 font-semibold">process</th>
                    <th className="py-2 pr-2 font-semibold">visible</th>
                    <th className="py-2 pr-2 font-semibold">iconic</th>
                  </tr>
                </thead>
                <tbody>
                  {windowsDiagnostic.wechat_candidates.map((item) => (
                    <tr key={item.hwnd} className="border-b border-[#f1f5f9] text-[#334155]">
                      <td className="py-2 pr-2 font-mono">{item.hwnd}</td>
                      <td className="py-2 pr-2 font-semibold">{item.title || "-"}</td>
                      <td className="py-2 pr-2 font-mono">{item.class_name || "-"}</td>
                      <td className="py-2 pr-2">{item.process_name || "-"}</td>
                      <td className="py-2 pr-2">{String(item.visible)}</td>
                      <td className="py-2 pr-2">{String(item.iconic)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {windowsDiagnostic.notes?.length ? (
            <div className="mt-3 grid gap-1 text-[11px] text-[#64748b]">
              {windowsDiagnostic.notes.map((note) => (
                <div key={note}>note: {note}</div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {foregroundDebug && !foregroundDebug.is_wechat_foreground ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
          小高AI微信助手已找到微信，但 Windows 阻止后台程序切换前台。请确认微信与小高AI微信助手权限一致，并保持微信窗口可见。        </div>
      ) : null}

      {foregroundDebug ? (
        <div className="mt-3 rounded-lg border border-[#edf1f6] bg-white p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <BooleanPill value={foregroundDebug.is_wechat_foreground} label="foreground_success" />
            <span className="font-semibold text-[#334155]">
              failure_stage: {foregroundDiagnostic?.failure_stage || result?.failure_stage || "-"}
            </span>
          </div>
          <div className="mt-3 grid gap-2 text-[11px] text-[#64748b] md:grid-cols-2">
            <div>
              微信：hwnd={foregroundDebug.wechat_hwnd || "-"} / {foregroundDebug.wechat_title || "-"} /{" "}
              {foregroundDebug.wechat_process_name || "-"}
            </div>
            <div>
              前台之前：{foregroundDebug.foreground_before_title || "-"} /{" "}
              {foregroundDebug.foreground_before_process_name || "-"}
            </div>
            <div>
              前台之后：{foregroundDebug.foreground_after_title || "-"} /{" "}
              {foregroundDebug.foreground_after_process_name || "-"}
            </div>
            <div>reason: {foregroundDebug.reason || "-"}</div>
          </div>
          {foregroundDebug.attempts?.length ? (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[680px] text-left text-[11px]">
                <thead className="text-[#64748b]">
                  <tr className="border-b border-[#edf1f6]">
                    <th className="py-2 pr-2 font-semibold">method</th>
                    <th className="py-2 pr-2 font-semibold">success</th>
                    <th className="py-2 pr-2 font-semibold">after_title</th>
                    <th className="py-2 pr-2 font-semibold">after_process</th>
                    <th className="py-2 pr-2 font-semibold">error</th>
                  </tr>
                </thead>
                <tbody>
                  {foregroundDebug.attempts.map((attempt, index) => (
                    <tr key={`${attempt.method}-${index}`} className="border-b border-[#f1f5f9] text-[#334155]">
                      <td className="py-2 pr-2 font-mono">{attempt.method}</td>
                      <td className="py-2 pr-2">{String(attempt.success)}</td>
                      <td className="py-2 pr-2">{attempt.foreground_after_title || "-"}</td>
                      <td className="py-2 pr-2">{attempt.foreground_after_process_name || "-"}</td>
                      <td className="py-2 pr-2">{attempt.error || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}

      {searchDiagnostic ? (
        <div className="mt-3 rounded-lg border border-[#edf1f6] bg-white p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <BooleanPill value={searchDiagnostic.success} label="search_debug" />
            <BooleanPill value={searchDiagnostic.clicked} label="clicked" />
            <BooleanPill value={searchDiagnostic.focused} label="focused" />
            <BooleanPill value={searchDiagnostic.verified} label="verified" />
            <BooleanPill value={searchFocus?.search_text_verified} label="search_text_verified" />
            <BooleanPill value={searchDiagnostic.manual} label="manual" />
            <span className="font-semibold text-[#334155]">
              failure_stage: {searchDiagnostic.failure_stage || "-"}
            </span>
            <span className="text-[#64748b]">message: {searchDiagnostic.message || "-"}</span>
          </div>
          {searchDiagnostic.click_point?.success === false ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
              未定位到微信搜索框，已阻止搜索。            </div>
          ) : null}
          {searchDiagnostic.clicked && !searchDiagnostic.focused ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
              搜索框点击已执行，但未确认搜索框获得焦点，已阻止粘贴关键词。需要人工处理。            </div>
          ) : null}
          {searchFocus?.focused && !searchFocus.search_text_verified ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
              疑似点击到搜索框，但未确认 Aw3 出现在搜索框中，已阻止按 Enter。            </div>
          ) : null}
          {searchFocus?.text_leaked_to_chat_input || searchDiagnostic.text_leaked_to_chat_input ? (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
              检测到关键词可能进入聊天输入框，已阻止按 Enter，请人工清理输入框。            </div>
          ) : null}
          <div className="mt-3 grid gap-2 text-[11px] text-[#64748b] md:grid-cols-2">
            <div>
              click_point: x={searchDiagnostic.click_point?.x ?? "-"} / y={searchDiagnostic.click_point?.y ?? "-"}
            </div>
            <div>strategy: {searchDiagnostic.click_point?.strategy || "-"}</div>
            <div>confidence: {searchDiagnostic.click_point?.confidence ?? "-"}</div>
            <div>
              search_box_rect:{" "}
              {searchDiagnostic.click_point?.search_box_rect
                ? `${searchDiagnostic.click_point.search_box_rect.left},${searchDiagnostic.click_point.search_box_rect.top},${searchDiagnostic.click_point.search_box_rect.right},${searchDiagnostic.click_point.search_box_rect.bottom}`
                : "-"}
            </div>
            <div>search_text_verified: {String(Boolean(searchFocus?.search_text_verified))}</div>
            <div>text_pasted_into_search_box: {String(Boolean(searchDiagnostic.text_pasted_into_search_box))}</div>
            <div>text_leaked_to_chat_input: {String(Boolean(searchDiagnostic.text_leaked_to_chat_input))}</div>
            <div>focus_reason: {searchDiagnostic.search_focus?.reason || "-"}</div>
            <div>focus_control: {searchDiagnostic.search_focus?.focus_control?.name || "-"}</div>
            <div>overlay: {searchDiagnostic.screenshots?.overlay || "-"}</div>
            <div>after_paste: {searchDiagnostic.screenshots?.after_paste || "-"}</div>
          </div>
          {searchDiagnostic.screenshots?.overlay ? (
            <div className="mt-3 overflow-hidden rounded-lg border border-[#edf1f6] bg-[#f8fafc] p-2">
              <img
                src={`file:///${searchDiagnostic.screenshots.overlay.replaceAll("\\", "/")}`}
                alt="search box overlay"
                className="max-h-64 w-full object-contain"
              />
            </div>
          ) : null}
          {/* search_text_debug 搜索关键词验证诊断（P0-4A-6B-1） */}
          {searchFocus?.search_text_debug ? (
            <div className="mt-2 rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-2 text-[11px]">
              <div className="mb-1 font-semibold text-[#334155]">
                搜索关键词验证诊断
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[#64748b]">
                <div>
                  method: <span className="font-medium text-[#334155]">{searchFocus.search_text_debug.method || "-"}</span>
                </div>
                <div>
                  verified: <BooleanPill value={searchFocus.search_text_debug.verified} label="" />
                </div>
                <div>
                  expected: <span className="font-mono text-[#334155]">{searchFocus.search_text_debug.expected || "-"}</span>
                </div>
                <div>
                  normalized: <span className="font-mono text-[#334155]">{searchFocus.search_text_debug.normalized_expected || "-"}</span>
                </div>
                <div className="col-span-2">
                  OCR 结果: <span className="font-mono text-[#334155]">{searchFocus.search_text_debug.ocr_text || "(无)"}</span>
                </div>
                <div className="col-span-2">
                  归一化 OCR: <span className="font-mono text-[#334155]">{searchFocus.search_text_debug.normalized_ocr_text || "(无)"}</span>
                </div>
                {searchFocus.search_text_debug.ocr_items?.length ? (
                  <div className="col-span-2">
                    OCR 条目: {searchFocus.search_text_debug.ocr_items.map((item, i) => (
                      <span key={i} className="mr-2 inline-block rounded bg-[#eef2f7] px-1.5 py-0.5 font-mono">
                        {item.text}({(item.confidence ?? 0).toFixed(2)})
                      </span>
                    ))}
                  </div>
                ) : null}
                {searchFocus.search_text_debug.crop_rect ? (
                  <div className="col-span-2">
                    裁剪区域: ({searchFocus.search_text_debug.crop_rect.left},{" "}
                    {searchFocus.search_text_debug.crop_rect.top}) → ({" "}
                    {searchFocus.search_text_debug.crop_rect.right},{" "}
                    {searchFocus.search_text_debug.crop_rect.bottom})
                  </div>
                ) : null}
                {searchFocus.search_text_debug.reason ? (
                  <div className="col-span-2 text-amber-600">
                    原因: {searchFocus.search_text_debug.reason}
                  </div>
                ) : null}
                {searchFocus.search_text_debug.search_box_crop_path ? (
                  <div className="col-span-2">
                    裁剪截图: <span className="font-mono text-[#475569]">{searchFocus.search_text_debug.search_box_crop_path}</span>
                  </div>
                ) : null}
                {searchFocus.search_text_debug.search_box_overlay_path ? (
                  <div className="col-span-2 mt-1 overflow-hidden rounded-lg border border-[#edf1f6] bg-white p-1">
                    <img
                      src={`file:///${searchFocus.search_text_debug.search_box_overlay_path.replaceAll("\\", "/")}`}
                      alt="search text debug overlay"
                      className="max-h-64 w-full object-contain"
                    />
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
          {searchDiagnostic.notes?.length ? (
            <div className="mt-3 grid gap-1 text-[11px] text-[#64748b]">
              {searchDiagnostic.notes.map((note) => (
                <div key={note}>note: {note}</div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {searchCalibration ? (
        <div className="mt-3 rounded-lg border border-[#edf1f6] bg-white px-3 py-2 text-xs text-[#475569]">
          标定结果：{String(searchCalibration.success)} / relative=({searchCalibration.relative_x ?? "-"},{" "}
          {searchCalibration.relative_y ?? "-"}) / {searchCalibration.config_path || searchCalibration.message || "-"}
        </div>
      ) : null}

      {/* 搜索结果诊断展示 */}
      {searchResultDiagnostic ? (
        <div className="mt-3 rounded-lg border border-[#edf1f6] bg-white p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <BooleanPill value={searchResultDiagnostic.search_text_verified} label="search_text_verified" />
            <BooleanPill value={searchResultDiagnostic.search_result_detected} label="result_detected" />
            <span className="font-semibold text-[#334155]">
              method: {searchResultDiagnostic.search_result?.method || "-"}
            </span>
            <span className="text-[#64748b]">
              confidence: {searchResultDiagnostic.search_result?.confidence ?? "-"}
            </span>
            <span className="font-semibold text-[#334155]">
              failure_stage: {searchResultDiagnostic.failure_stage || "-"}
            </span>
          </div>
          {/* 搜索框未确认 Aw3 提示 */}
          {!searchResultDiagnostic.search_text_verified ? (
            <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] font-semibold text-amber-700">
              搜索框中未确认 Aw3，已阻止搜索结果选择。
            </div>
          ) : null}
          {/* 搜索结果未检测到提示 */}
          {searchResultDiagnostic.search_text_verified && !searchResultDiagnostic.search_result_detected ? (
            <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] font-semibold text-amber-700">
              未在搜索结果中识别到 Aw3，已阻止点击结果。
            </div>
          ) : null}
          {/* 搜索结果已检测到提示 */}
          {searchResultDiagnostic.search_result_detected ? (
            <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] font-semibold text-emerald-700">
              已定位到 Aw3 搜索结果行，可以继续启动微信测试。
            </div>
          ) : null}
          {/* 结果行矩形和点击点 */}
          {searchResultDiagnostic.search_result?.rect ? (
            <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-[#64748b]">
              <div>
                result_rect: ({searchResultDiagnostic.search_result.rect.left},{" "}
                {searchResultDiagnostic.search_result.rect.top}) → ({" "}
                {searchResultDiagnostic.search_result.rect.right},{" "}
                {searchResultDiagnostic.search_result.rect.bottom})
              </div>
              <div>
                click_point: ({searchResultDiagnostic.search_result.click_point?.x ?? "-"},{" "}
                {searchResultDiagnostic.search_result.click_point?.y ?? "-"})
              </div>
            </div>
          ) : null}
          {/* overlay 截图 */}
          {searchResultDiagnostic.screenshots?.overlay ? (
            <div className="mt-2 overflow-hidden rounded-lg border border-[#edf1f6] bg-[#f8fafc] p-2">
              <img
                src={`file:///${searchResultDiagnostic.screenshots.overlay.replaceAll("\\", "/")}`}
                alt="search result overlay"
                className="max-h-64 w-full object-contain"
              />
            </div>
          ) : null}
          {/* search_text_debug 诊断详情 */}
          {searchResultDiagnostic.search_text_debug ? (
            <div className="mt-2 rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-2 text-[11px]">
              <div className="mb-1 font-semibold text-[#334155]">
                搜索关键词验证诊断（P0-4A-6B-1）
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[#64748b]">
                <div>
                  method: <span className="font-medium text-[#334155]">{searchResultDiagnostic.search_text_debug.method || "-"}</span>
                </div>
                <div>
                  verified: <BooleanPill value={searchResultDiagnostic.search_text_debug.verified} label="" />
                </div>
                <div>
                  expected: <span className="font-mono text-[#334155]">{searchResultDiagnostic.search_text_debug.expected || "-"}</span>
                </div>
                <div>
                  normalized: <span className="font-mono text-[#334155]">{searchResultDiagnostic.search_text_debug.normalized_expected || "-"}</span>
                </div>
                <div className="col-span-2">
                  OCR 结果: <span className="font-mono text-[#334155]">{searchResultDiagnostic.search_text_debug.ocr_text || "(无)"}</span>
                </div>
                <div className="col-span-2">
                  归一化 OCR: <span className="font-mono text-[#334155]">{searchResultDiagnostic.search_text_debug.normalized_ocr_text || "(无)"}</span>
                </div>
                {searchResultDiagnostic.search_text_debug.ocr_items?.length ? (
                  <div className="col-span-2">
                    OCR 条目: {searchResultDiagnostic.search_text_debug.ocr_items.map((item, i) => (
                      <span key={i} className="mr-2 inline-block rounded bg-[#eef2f7] px-1.5 py-0.5 font-mono">
                        {item.text}({(item.confidence ?? 0).toFixed(2)})
                      </span>
                    ))}
                  </div>
                ) : null}
                {searchResultDiagnostic.search_text_debug.crop_rect ? (
                  <div className="col-span-2">
                    裁剪区域: ({searchResultDiagnostic.search_text_debug.crop_rect.left},{" "}
                    {searchResultDiagnostic.search_text_debug.crop_rect.top}) → ({" "}
                    {searchResultDiagnostic.search_text_debug.crop_rect.right},{" "}
                    {searchResultDiagnostic.search_text_debug.crop_rect.bottom})
                  </div>
                ) : null}
                {searchResultDiagnostic.search_text_debug.reason ? (
                  <div className="col-span-2 text-amber-600">
                    原因: {searchResultDiagnostic.search_text_debug.reason}
                  </div>
                ) : null}
                {searchResultDiagnostic.search_text_debug.search_box_crop_path ? (
                  <div className="col-span-2">
                    裁剪截图:{" "}
                    <span className="font-mono text-[#475569]">{searchResultDiagnostic.search_text_debug.search_box_crop_path}</span>
                  </div>
                ) : null}
                {searchResultDiagnostic.search_text_debug.search_box_overlay_path ? (
                  <div className="col-span-2 overflow-hidden rounded-lg border border-[#edf1f6] bg-white p-1">
                    <img
                      src={`file:///${searchResultDiagnostic.search_text_debug.search_box_overlay_path.replaceAll("\\", "/")}`}
                      alt="search text debug overlay"
                      className="max-h-64 w-full object-contain"
                    />
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {result?.message ? (
        <div className="mt-3 rounded-lg border border-[#edf1f6] bg-white px-3 py-2 text-xs text-[#475569]">
          {result.message}
        </div>
      ) : null}

      {result?.evidence ? (
        <div className="mt-3 grid gap-1.5 text-[11px] text-[#64748b]">
          <div>before: {result.evidence.before || "-"}</div>
          <div>after: {result.evidence.after || "-"}</div>
          <div>verify: {result.evidence.verify_json || "-"}</div>
        </div>
      ) : null}
    </div>
  );
}
