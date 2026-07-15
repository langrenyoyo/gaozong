import {
  AlertTriangleIcon,
  ExternalLinkIcon,
  LoaderIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { API_BASE_URL } from "../../../api/client";
import {
  fetchDouyinLiveCheckAuthUrl,
  fetchDouyinLiveCheckStatus,
} from "../api";
import { fetchWebhookEvents } from "../api";
import { formatDateTimeLocal } from "../../../lib/datetime";
import type {
  DouyinLiveCheckAuthUrlData,
  DouyinLiveCheckStatusData,
  WebhookEvent,
} from "../types";

const LIVE_CHECK_DISABLED_MESSAGE =
  "抖音授权联调未开启，请在后端配置 DY_LIVE_CHECK_ENABLED=true 后重启服务。";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function getApiErrorInfo(err: unknown): { status?: number; detail?: string } {
  if (!isRecord(err)) return {};
  const response = isRecord(err.response) ? err.response : null;
  const data = response && isRecord(response.data) ? response.data : null;
  const rawDetail = data?.detail;
  const detail =
    typeof rawDetail === "string"
      ? rawDetail
      : isRecord(rawDetail)
        ? JSON.stringify(rawDetail)
        : undefined;
  const status = typeof response?.status === "number" ? response.status : undefined;
  return { status, detail };
}

function liveCheckErrorMessage(err: unknown): string {
  const { status, detail } = getApiErrorInfo(err);
  let parsedDetail: Record<string, unknown> | null = null;
  if (detail?.startsWith("{")) {
    try {
      const parsed = JSON.parse(detail);
      parsedDetail = isRecord(parsed) ? parsed : null;
    } catch {
      parsedDetail = null;
    }
  }

  if (status === 403 && (detail || "").toLowerCase().includes("disabled")) {
    return LIVE_CHECK_DISABLED_MESSAGE;
  }
  if (status === 502 && parsedDetail) {
    const safeMessage =
      typeof parsedDetail.safe_message === "string"
        ? parsedDetail.safe_message
        : "授权链接获取失败，请检查抖音上游接口配置。";
    const upstreamStatus = parsedDetail.upstream_status ? `上游 HTTP ${parsedDetail.upstream_status}` : "";
    const upstreamMsg = parsedDetail.upstream_msg ? `：${parsedDetail.upstream_msg}` : "";
    return `${safeMessage}${upstreamStatus ? `（${upstreamStatus}${upstreamMsg}）` : ""}`;
  }
  if (status === 400 && detail) {
    return `抖音授权联调配置不完整：${detail}`;
  }
  if (status) {
    return `抖音授权联调接口请求失败，HTTP ${status}`;
  }
  return "无法获取抖音现场联调状态，请确认后端服务已启动。";
}

function formatTime(value?: string | null): string {
  return formatDateTimeLocal(value, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function boolText(value: boolean): string {
  return value ? "是" : "否";
}

type OpenIdMatchState = "matched" | "mismatched" | "unknown";

function getOpenIdMatchState(
  openId: string | null | undefined,
  values: Array<string | null | undefined>,
): OpenIdMatchState {
  if (!openId) return "unknown";
  const comparableValues = values.filter((value): value is string => Boolean(value));
  if (comparableValues.length < values.length) return "unknown";
  return comparableValues.some((value) => value === openId) ? "matched" : "mismatched";
}

function MatchBadge({ state }: { state: OpenIdMatchState }) {
  const styles = {
    matched: "border-emerald-200 bg-emerald-50 text-emerald-700",
    mismatched: "border-amber-200 bg-amber-50 text-amber-700",
    unknown: "border-slate-200 bg-slate-50 text-slate-500",
  }[state];
  const text = {
    matched: "是",
    mismatched: "否",
    unknown: "无法判断",
  }[state];

  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${styles}`}>
      {text}
    </span>
  );
}

function AuthStatusBadge({ authorized }: { authorized: boolean }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
        authorized
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-slate-200 bg-slate-50 text-slate-500"
      }`}
    >
      {authorized ? "已授权" : "未检测到扫码授权"}
    </span>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[#eef2f7] py-2 last:border-b-0">
      <span className="shrink-0 text-[#8b95a6]">{label}</span>
      <strong className="min-w-0 text-right font-semibold text-[#374151]">{value}</strong>
    </div>
  );
}

export default function DouyinLiveCheckPage() {
  const [status, setStatus] = useState<DouyinLiveCheckStatusData | null>(null);
  const [authUrlInfo, setAuthUrlInfo] = useState<DouyinLiveCheckAuthUrlData | null>(null);
  const [recentWebhookEvent, setRecentWebhookEvent] = useState<WebhookEvent | null>(null);
  const [recentWebhookTotal, setRecentWebhookTotal] = useState(0);
  const [recentWebhookError, setRecentWebhookError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [authLoading, setAuthLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const unavailable = Boolean(error);
  const canOpenAuthUrl = !authLoading && !unavailable;
  const currentAuthCallback = status?.last_oauth_callback || null;
  const currentAuthOpenId = status?.last_oauth_callback?.open_id || null;
  const isAuthorized = Boolean(currentAuthOpenId);
  const observedWebhook = status?.last_webhook_observe || null;
  const observedWebhookOpenIdValues = [
    observedWebhook?.from_user_id,
    observedWebhook?.to_user_id,
    observedWebhook?.body_open_id,
    observedWebhook?.body_account_open_id,
    observedWebhook?.content_open_id,
    observedWebhook?.content_account_open_id,
  ];
  const observedWebhookMatchState = getOpenIdMatchState(currentAuthOpenId, observedWebhookOpenIdValues);

  const loadStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchDouyinLiveCheckStatus();
      setStatus(result.data);
      const currentOpenId = result.data.last_oauth_callback?.open_id;
      if (currentOpenId) {
        try {
          const webhookResult = await fetchWebhookEvents({
            page: 1,
            page_size: 1,
            open_id: currentOpenId,
          });
          setRecentWebhookEvent(webhookResult.data.items[0] || null);
          setRecentWebhookTotal(webhookResult.data.total);
          setRecentWebhookError(null);
        } catch (webhookErr) {
          setRecentWebhookEvent(null);
          setRecentWebhookTotal(0);
          setRecentWebhookError(liveCheckErrorMessage(webhookErr));
        }
      } else {
        setRecentWebhookEvent(null);
        setRecentWebhookTotal(0);
        setRecentWebhookError(null);
      }
    } catch (err) {
      setError(liveCheckErrorMessage(err));
      setStatus(null);
      setAuthUrlInfo(null);
      setRecentWebhookEvent(null);
      setRecentWebhookTotal(0);
      setRecentWebhookError(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleOpenAuthUrl = async () => {
    if (!canOpenAuthUrl) return;
    setAuthLoading(true);
    try {
      const result = await fetchDouyinLiveCheckAuthUrl();
      setAuthUrlInfo(result.data);
      if (result.data.auth_url) {
        window.open(result.data.auth_url, "_blank", "noopener,noreferrer");
      }
    } catch (err) {
      toast.error(liveCheckErrorMessage(err));
    } finally {
      setAuthLoading(false);
    }
  };

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">抖音授权联调</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">
              现场扫码授权与真实回调观测工具，不是生产授权管理。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadStatus}
              disabled={loading}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151] disabled:opacity-60"
            >
              <RefreshCwIcon size={14} className={loading ? "animate-spin" : ""} />
              刷新状态
            </button>
            <button
              onClick={handleOpenAuthUrl}
              disabled={!canOpenAuthUrl}
              title={unavailable ? error || LIVE_CHECK_DISABLED_MESSAGE : "生成并打开抖音授权链接"}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-3 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:cursor-not-allowed disabled:opacity-45"
            >
              {authLoading ? <LoaderIcon size={14} className="animate-spin" /> : <ExternalLinkIcon size={14} />}
              生成/打开授权链接
            </button>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-5">
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-800">
          <div className="flex items-start gap-2">
            <AlertTriangleIcon size={16} className="mt-0.5 shrink-0" />
            <p>
              本页面只用于现场观测：生成授权 URL、查看 OAuth callback 摘要、查看 webhook 请求头/body 关键字段。
              不展示 token，不提供主动拉取历史私信，不触发微信自动化。
            </p>
          </div>
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center gap-2 text-xs text-[#8b95a6]">
            <LoaderIcon size={16} className="animate-spin" />
            加载中...
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-800">
            <span>{error}</span>
            <button onClick={loadStatus} className="ml-auto inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-amber-300 bg-white px-3 text-[11px] font-semibold text-amber-800 hover:bg-amber-50">
              <RefreshCwIcon size={12} />
              重试加载
            </button>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-lg border border-[#e4e8f0] bg-white p-4 text-xs">
              <div className="mb-3 flex items-center gap-2">
                <ShieldCheckIcon size={16} className="text-[#2563eb]" />
                <h2 className="font-bold text-[#1a1f2e]">配置状态</h2>
              </div>
              <Field label="联调开关" value={status?.enabled ? "已开启" : "未开启"} />
              <Field label="授权 URL 配置" value={status?.auth_url_configured ? "完整" : "不完整"} />
              <Field label="缺失配置" value={(status?.missing_config || []).join(", ") || "-"} />
              <Field label="OAuth 回跳地址" value={status?.auth_redirect_url || "-"} />
              <Field label="Webhook 观测地址" value={status?.webhook_observe_url || "-"} />
              {authUrlInfo?.auth_url ? (
                <div className="mt-3 break-all rounded-lg bg-[#f8fafc] p-3 text-[11px] leading-5 text-[#64748b]">
                  {authUrlInfo.auth_url}
                </div>
              ) : null}
            </section>

            <section className="rounded-lg border border-[#e4e8f0] bg-white p-4 text-xs">
              <h2 className="mb-3 font-bold text-[#1a1f2e]">当前授权账号</h2>
              {currentAuthCallback ? (
                <>
                  <div className="mb-3 flex items-center gap-3 rounded-lg bg-[#f8fafc] p-3">
                    {currentAuthCallback.avatar ? (
                      <img
                        src={currentAuthCallback.avatar}
                        alt="抖音头像"
                        className="h-10 w-10 shrink-0 rounded-full border border-[#e4e8f0] object-cover"
                      />
                    ) : (
                      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-[#e4e8f0] bg-white text-[11px] text-[#8b95a6]">
                        头像
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <strong className="text-sm text-[#1a1f2e]">{currentAuthCallback.nick_name || "未返回昵称"}</strong>
                        <AuthStatusBadge authorized={isAuthorized} />
                      </div>
                      <p className="mt-1 break-all font-mono text-[11px] text-[#64748b]">
                        {currentAuthCallback.open_id || "未返回 open_id"}
                      </p>
                    </div>
                  </div>
                  <Field label="授权状态" value={<AuthStatusBadge authorized={isAuthorized} />} />
                  <Field label="抖音昵称" value={currentAuthCallback.nick_name || "-"} />
                  <Field label="open_id" value={currentAuthCallback.open_id || "-"} />
                  <Field label="头像" value={currentAuthCallback.avatar ? "已返回" : "-"} />
                  <Field label="授权接收时间" value={formatTime(currentAuthCallback.received_at)} />
                  <Field label="是否收到 code" value={boolText(currentAuthCallback.has_code)} />
                  <Field label="code 摘要" value={currentAuthCallback.code_preview || "-"} />
                  <Field label="state" value={currentAuthCallback.state || "-"} />
                  <Field label="error" value={currentAuthCallback.error || "-"} />
                  <Field label="query keys" value={currentAuthCallback.query_keys.join(", ") || "-"} />
                  <p className="mt-3 rounded-lg border border-sky-100 bg-sky-50 px-3 py-2 text-[11px] leading-5 text-sky-800">
                    说明：该私信能力授权回调返回 open_id / nick_name / avatar，不一定返回 code。open_id 存在表示授权回调已到达。
                  </p>
                </>
              ) : (
                <>
                  <Field label="授权状态" value={<AuthStatusBadge authorized={false} />} />
                  <p className="mt-3 rounded-lg border border-sky-100 bg-sky-50 px-3 py-2 text-[11px] leading-5 text-sky-800">
                    说明：该私信能力授权回调返回 open_id / nick_name / avatar，不一定返回 code。open_id 存在表示授权回调已到达。
                  </p>
                </>
              )}
            </section>

            <section className="rounded-lg border border-[#e4e8f0] bg-white p-4 text-xs lg:col-span-2">
              <h2 className="mb-3 font-bold text-[#1a1f2e]">最近真实 webhook 事件（按本次授权 open_id 过滤）</h2>
              {recentWebhookError ? (
                <p className="text-amber-700">{recentWebhookError}</p>
              ) : currentAuthOpenId ? (
                recentWebhookEvent ? (
                  <div className="grid gap-x-8 lg:grid-cols-2">
                    <Field label="本次授权 open_id" value={currentAuthOpenId} />
                    <Field label="匹配事件数" value={recentWebhookTotal} />
                    <Field label="event" value={recentWebhookEvent.event || "-"} />
                    <Field label="from_user_id" value={recentWebhookEvent.from_user_id || "-"} />
                    <Field label="to_user_id" value={recentWebhookEvent.to_user_id || "-"} />
                    <Field label="body open_id" value={recentWebhookEvent.body_open_id || "-"} />
                    <Field label="body account_open_id" value={recentWebhookEvent.body_account_open_id || "-"} />
                    <Field label="content open_id" value={recentWebhookEvent.content_open_id || "-"} />
                    <Field label="content account_open_id" value={recentWebhookEvent.content_account_open_id || "-"} />
                    <Field label="server_message_id" value={recentWebhookEvent.server_message_id || "-"} />
                    <Field label="created_at" value={formatTime(recentWebhookEvent.created_at)} />
                    <Field
                      label="是否命中本次授权 open_id"
                      value={
                        <MatchBadge
                          state={getOpenIdMatchState(currentAuthOpenId, [
                            recentWebhookEvent.from_user_id,
                            recentWebhookEvent.to_user_id,
                            recentWebhookEvent.body_open_id,
                            recentWebhookEvent.body_account_open_id,
                            recentWebhookEvent.content_open_id,
                            recentWebhookEvent.content_account_open_id,
                          ])}
                        />
                      }
                    />
                  </div>
                ) : (
                  <p className="text-[#8b95a6]">本次授权 open_id 暂无匹配的真实 webhook 事件</p>
                )
              ) : (
                <p className="text-[#8b95a6]">暂无本次授权 open_id</p>
              )}
            </section>

            <section className="rounded-lg border border-[#e4e8f0] bg-white p-4 text-xs lg:col-span-2">
              <h2 className="mb-3 font-bold text-[#1a1f2e]">最近 webhook 账号</h2>
              {status?.last_webhook_observe ? (
                <div className="grid gap-x-8 lg:grid-cols-2">
                  <Field label="接收时间" value={formatTime(status.last_webhook_observe.received_at)} />
                  <Field label="event" value={status.last_webhook_observe.event || "-"} />
                  <Field label="from_user_id" value={status.last_webhook_observe.from_user_id || "-"} />
                  <Field label="to_user_id" value={status.last_webhook_observe.to_user_id || "-"} />
                  <Field label="body open_id" value={status.last_webhook_observe.body_open_id || "-"} />
                  <Field label="body account_open_id" value={status.last_webhook_observe.body_account_open_id || "-"} />
                  <Field label="content open_id" value={status.last_webhook_observe.content_open_id || "-"} />
                  <Field label="content account_open_id" value={status.last_webhook_observe.content_account_open_id || "-"} />
                  <Field
                    label="是否匹配当前授权 open_id"
                    value={<MatchBadge state={observedWebhookMatchState} />}
                  />
                  <Field label="有 Authorization" value={boolText(status.last_webhook_observe.has_authorization)} />
                  <Field label="有 X-Auth-Timestamp" value={boolText(status.last_webhook_observe.has_x_auth_timestamp)} />
                  <Field label="有 content" value={boolText(status.last_webhook_observe.body_has_content)} />
                  <Field label="有 open_id" value={boolText(status.last_webhook_observe.body_has_open_id)} />
                  <Field label="有 account_open_id" value={boolText(status.last_webhook_observe.body_has_account_open_id)} />
                  <Field label="有 conversation_short_id" value={boolText(status.last_webhook_observe.body_has_conversation_short_id)} />
                  <Field label="有 server_message_id" value={boolText(status.last_webhook_observe.body_has_server_message_id)} />
                  <Field label="content parse success" value={boolText(status.last_webhook_observe.content_parse_success)} />
                  <Field label="content parse error" value={status.last_webhook_observe.content_parse_error || "-"} />
                  <Field label="content has conversation_short_id" value={boolText(status.last_webhook_observe.content_has_conversation_short_id)} />
                  <Field label="content has server_message_id" value={boolText(status.last_webhook_observe.content_has_server_message_id)} />
                  <Field label="content has message_type" value={boolText(status.last_webhook_observe.content_has_message_type)} />
                  <Field label="content message_type" value={status.last_webhook_observe.content_message_type || "-"} />
                  <Field label="body keys" value={status.last_webhook_observe.body_keys.join(", ") || "-"} />
                  <Field label="content keys" value={status.last_webhook_observe.content_keys.join(", ") || "-"} />
                </div>
              ) : (
                <p className="text-[#8b95a6]">暂无 webhook 观测记录</p>
              )}
            </section>
          </div>
        )}
      </div>
      <footer className="shrink-0 border-t border-[#e4e8f0] bg-white px-5 py-2 text-[11px] text-[#8b95a6]">
        当前后端：{API_BASE_URL}
      </footer>
    </section>
  );
}
