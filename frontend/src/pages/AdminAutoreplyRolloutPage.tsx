import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  AlertTriangleIcon,
  BanIcon,
  CheckCircle2Icon,
  PauseCircleIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
  Trash2Icon,
} from "lucide-react";
import {
  addAutoreplyWhitelist,
  deleteAutoreplyWhitelist,
  getAutoreplyRolloutSummary,
  listAutoreplyRolloutAccounts,
  listAutoreplyRuns,
  listAutoreplyWhitelist,
  updateAutoreplyRolloutAccount,
  updateAutoreplyRolloutGlobal,
  type AdminAutoreplyRun,
  type AdminRolloutAccount,
  type AdminRolloutSummary,
  type AdminWhitelistCreateRequest,
  type AdminWhitelistEntry,
} from "../api/adminAutoreplyRollout";
import { formatDateTimeLocal } from "../lib/datetime";

type WhitelistType = "account" | "customer" | "conversation";

const emptyWhitelistForm: AdminWhitelistCreateRequest = {
  entry_type: "account",
  merchant_id: "",
  account_open_id: "",
  value: "",
  reason: "",
};

const reasonText: Record<string, string> = {
  env_auto_reply_disabled: "系统级自动回复关闭",
  env_real_send_disabled: "系统级真实发送熔断中",
  env_account_whitelist_empty: "系统级企业号白名单为空",
  env_customer_or_conversation_whitelist_empty: "系统级客户或会话白名单为空",
  db_auto_reply_disabled: "DB 自动回复关闭",
  db_real_send_disabled: "DB 真实发送关闭",
};

const blockedReasonText: Record<string, string> = {
  global_auto_reply_disabled: "全局自动回复关闭",
  real_send_disabled: "真实发送关闭",
  rollout_whitelist_miss: "灰度白名单未命中",
  account_disabled: "企业号自动回复关闭",
  account_send_disabled: "企业号真实发送关闭",
  agent_not_bound: "未绑定智能体",
  post_llm_gate_blocked: "大模型后置门禁阻断",
  manual_takeover: "会话人工接管",
  send_context_unavailable: "发送上下文不可用",
  rag_miss: "知识库未命中",
};

function resolveErrorMessage(err: unknown): string {
  const data = (err as { response?: { status?: number; data?: { detail?: unknown; message?: string } } })?.response?.data;
  const detail = data?.detail;
  if (detail && typeof detail === "object") {
    return (detail as { message?: string }).message || "请求失败";
  }
  if (typeof detail === "string") return detail;
  return data?.message || (err instanceof Error ? err.message : "请求失败");
}

function isForbidden(err: unknown): boolean {
  return (err as { response?: { status?: number } })?.response?.status === 403;
}

function readableReason(value?: string | null): string {
  if (!value) return "-";
  return blockedReasonText[value] || reasonText[value] || value;
}

function boolText(value: boolean | null | undefined): string {
  if (value === true) return "是";
  if (value === false) return "否";
  return "-";
}

function StatusPill({
  active,
  activeText = "开启",
  inactiveText = "关闭",
}: {
  active: boolean;
  activeText?: string;
  inactiveText?: string;
}) {
  return (
    <span
      className={`inline-flex rounded-md px-2 py-0.5 text-[11px] font-semibold ${
        active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"
      }`}
    >
      {active ? activeText : inactiveText}
    </span>
  );
}

function SectionTitle({ title, hint }: { title: string; hint?: string }) {
  return (
    <div>
      <h2 className="text-sm font-bold text-[#1a1f2e]">{title}</h2>
      {hint ? <p className="mt-1 text-[11px] text-[#8b95a6]">{hint}</p> : null}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-[#e4e8f0] bg-white px-3 py-3">
      <div className="text-[11px] font-semibold text-[#8b95a6]">{label}</div>
      <div className="mt-1 text-xl font-bold text-[#1a1f2e]">{value}</div>
    </div>
  );
}

function ToggleInput({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-lg border border-[#e4e8f0] bg-[#f8fafc] px-3 py-2 text-xs font-semibold text-[#475467]">
      {label}
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-[#cbd5e1] text-[#2563eb]"
      />
    </label>
  );
}

function compactReason(raw: string): string | null {
  const value = raw.trim();
  return value ? value : null;
}

export default function AdminAutoreplyRolloutPage() {
  const [summary, setSummary] = useState<AdminRolloutSummary | null>(null);
  const [accounts, setAccounts] = useState<AdminRolloutAccount[]>([]);
  const [whitelist, setWhitelist] = useState<AdminWhitelistEntry[]>([]);
  const [runs, setRuns] = useState<AdminAutoreplyRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [globalForm, setGlobalForm] = useState({
    auto_reply_enabled: false,
    real_send_enabled: false,
    allow_full_rollout: false,
    reason: "",
  });
  const [savingGlobal, setSavingGlobal] = useState(false);
  const [whitelistForm, setWhitelistForm] = useState<AdminWhitelistCreateRequest>(emptyWhitelistForm);
  const [runsFilter, setRunsFilter] = useState({ mode: "", status: "", blocked_reason: "", account_open_id: "" });

  const envRealSendDisabled = summary ? !summary.env_fuse.real_send_env_enabled : false;
  const realSendPossible = Boolean(summary?.safety.real_send_effectively_possible);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryResp, accountsResp, whitelistResp, runsResp] = await Promise.all([
        getAutoreplyRolloutSummary(),
        listAutoreplyRolloutAccounts(),
        listAutoreplyWhitelist(),
        listAutoreplyRuns({ page: 1, page_size: 20 }),
      ]);
      setSummary(summaryResp.data);
      setGlobalForm({
        auto_reply_enabled: summaryResp.data.db_config.auto_reply_enabled,
        real_send_enabled: summaryResp.data.db_config.real_send_enabled,
        allow_full_rollout: summaryResp.data.db_config.allow_full_rollout,
        reason: "",
      });
      setAccounts(accountsResp.data.items || []);
      setWhitelist(whitelistResp.data.items || []);
      setRuns(runsResp.data.items || []);
      setForbidden(false);
    } catch (err) {
      if (isForbidden(err)) {
        setForbidden(true);
      } else {
        setError(resolveErrorMessage(err));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const reloadSummaryAndAccounts = async () => {
    const [summaryResp, accountsResp] = await Promise.all([
      getAutoreplyRolloutSummary(),
      listAutoreplyRolloutAccounts(),
    ]);
    setSummary(summaryResp.data);
    setAccounts(accountsResp.data.items || []);
    setGlobalForm((current) => ({
      ...current,
      auto_reply_enabled: summaryResp.data.db_config.auto_reply_enabled,
      real_send_enabled: summaryResp.data.db_config.real_send_enabled,
      allow_full_rollout: summaryResp.data.db_config.allow_full_rollout,
      reason: "",
    }));
  };

  const handleSaveGlobal = async () => {
    const reason = compactReason(globalForm.reason);
    if (!reason) {
      toast.error("请填写操作原因");
      return;
    }
    if (globalForm.allow_full_rollout && !window.confirm("确认开启全量自动回复")) {
      return;
    }
    setSavingGlobal(true);
    try {
      const response = await updateAutoreplyRolloutGlobal({ ...globalForm, reason });
      setSummary(response.data);
      setGlobalForm((current) => ({ ...current, reason: "" }));
      toast.success(envRealSendDisabled ? "DB 配置已保存，当前仍受系统熔断限制，不会真实发送。" : "全局配置已保存");
    } catch (err) {
      toast.error(resolveErrorMessage(err));
    } finally {
      setSavingGlobal(false);
    }
  };

  const handleEmergencyPause = async (field: "real_send_enabled" | "auto_reply_enabled") => {
    const reason = window.prompt(field === "real_send_enabled" ? "请输入暂停真实发送原因" : "请输入暂停自动回复原因");
    const reasonValue = compactReason(reason || "");
    if (!reasonValue || !summary) {
      toast.error("操作原因不能为空");
      return;
    }
    try {
      await updateAutoreplyRolloutGlobal({
        auto_reply_enabled: field === "auto_reply_enabled" ? false : summary.db_config.auto_reply_enabled,
        real_send_enabled: field === "real_send_enabled" ? false : summary.db_config.real_send_enabled,
        allow_full_rollout: summary.db_config.allow_full_rollout,
        reason: reasonValue,
      });
      await reloadSummaryAndAccounts();
      toast.success(field === "real_send_enabled" ? "DB 真实发送已暂停" : "DB 自动回复已暂停");
    } catch (err) {
      toast.error(resolveErrorMessage(err));
    }
  };

  const handleToggleAccount = async (
    account: AdminRolloutAccount,
    field: "enabled" | "send_enabled",
    value: boolean,
  ) => {
    if (!account.account_open_id) {
      toast.error("后端未返回企业号操作键，无法修改");
      return;
    }
    const reason = window.prompt(value ? "请输入开启原因" : "请输入关闭原因");
    const reasonValue = compactReason(reason || "");
    if (!reasonValue) {
      toast.error("操作原因不能为空");
      return;
    }
    try {
      await updateAutoreplyRolloutAccount(account.account_open_id, { [field]: value, reason: reasonValue });
      await reloadSummaryAndAccounts();
      toast.success("企业号配置已更新");
    } catch (err) {
      toast.error(resolveErrorMessage(err));
    }
  };

  const handleAddWhitelist = async () => {
    const payload = {
      ...whitelistForm,
      merchant_id: whitelistForm.merchant_id.trim(),
      account_open_id: whitelistForm.account_open_id?.trim() || undefined,
      value: whitelistForm.value.trim(),
      reason: whitelistForm.reason.trim(),
    };
    if (!payload.merchant_id || !payload.value || !payload.reason) {
      toast.error("merchant_id、value 和 reason 必填");
      return;
    }
    try {
      await addAutoreplyWhitelist(payload);
      const response = await listAutoreplyWhitelist();
      setWhitelist(response.data.items || []);
      setWhitelistForm(emptyWhitelistForm);
      toast.success("白名单已保存");
    } catch (err) {
      toast.error(resolveErrorMessage(err));
    }
  };

  const handleDeleteWhitelist = async (entry: AdminWhitelistEntry) => {
    if (!window.confirm("确认移除该白名单")) return;
    const reason = window.prompt("请输入移除原因");
    const reasonValue = compactReason(reason || "");
    if (!reasonValue) {
      toast.error("移除原因不能为空");
      return;
    }
    try {
      await deleteAutoreplyWhitelist(entry.id, reasonValue);
      const [summaryResp, whitelistResp] = await Promise.all([
        getAutoreplyRolloutSummary(),
        listAutoreplyWhitelist(),
      ]);
      setSummary(summaryResp.data);
      setWhitelist(whitelistResp.data.items || []);
      toast.success("白名单已软禁用");
    } catch (err) {
      toast.error(resolveErrorMessage(err));
    }
  };

  const loadRuns = async () => {
    try {
      const response = await listAutoreplyRuns({
        page: 1,
        page_size: 20,
        mode: runsFilter.mode || undefined,
        status: runsFilter.status || undefined,
        blocked_reason: runsFilter.blocked_reason || undefined,
        account_open_id: runsFilter.account_open_id || undefined,
      });
      setRuns(response.data.items || []);
    } catch (err) {
      toast.error(resolveErrorMessage(err));
    }
  };

  const stats = useMemo(() => {
    if (!summary) return [];
    return [
      { label: "企业号白名单", value: summary.counts.account_whitelist_count },
      { label: "客户白名单", value: summary.counts.customer_whitelist_count },
      { label: "会话白名单", value: summary.counts.conversation_whitelist_count },
      { label: "enabled 企业号", value: summary.counts.enabled_account_count },
      { label: "send_enabled 企业号", value: summary.counts.send_enabled_account_count },
      { label: "dry-run", value: summary.recent_stats.dry_run_count },
      { label: "发送候选", value: summary.recent_stats.real_send_candidate_count },
      { label: "已发送", value: summary.recent_stats.sent_count },
      { label: "已阻断", value: summary.recent_stats.blocked_count },
    ];
  }, [summary]);

  if (forbidden) {
    return (
      <section className="grid h-full place-items-center bg-[#f3f6fa] p-6">
        <div className="rounded-xl border border-red-200 bg-white px-8 py-7 text-center shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <BanIcon className="mx-auto text-red-500" size={30} />
          <h1 className="mt-3 text-base font-bold text-[#1a1f2e]">无权限访问</h1>
          <p className="mt-2 text-xs text-[#8b95a6]">该页面仅允许超级管理员查看和配置。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#fff7ed] text-[#c2410c]">
            <ShieldAlertIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">自动回复灰度与发送控制</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">只配置 DB 管理层意图，最终发送仍由后端 gate 裁决</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void loadAll()}
          disabled={loading}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#dbe3ef] bg-white px-4 text-xs font-semibold text-[#475467] disabled:opacity-60"
        >
          <RefreshCwIcon size={14} className={loading ? "animate-spin" : ""} />
          刷新
        </button>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-5">
        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs font-semibold text-red-700">
            加载失败：{error}
          </div>
        ) : null}
        {envRealSendDisabled ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs leading-6 text-red-700">
            <b>系统级真实发送熔断中，前端配置不会触发真实发送。</b>
            <span className="ml-2">允许保存 DB 配置用于演练，但真实发送仍不可用。</span>
          </div>
        ) : null}
        {summary ? (
          <>
            <section className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <SectionTitle title="总览状态" hint="env 仅显示布尔状态，不展示原始环境变量值" />
                <div
                  className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-bold ${
                    realSendPossible ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"
                  }`}
                >
                  {realSendPossible ? <CheckCircle2Icon size={14} /> : <AlertTriangleIcon size={14} />}
                  {realSendPossible ? "真实发送可进入候选" : readableReason(summary.safety.reason_if_not_possible)}
                </div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-xs md:grid-cols-3 xl:grid-cols-6">
                <div>env 自动回复：<StatusPill active={summary.env_fuse.auto_reply_env_enabled} /></div>
                <div>env 真实发送：<StatusPill active={summary.env_fuse.real_send_env_enabled} activeText="未熔断" inactiveText="熔断中" /></div>
                <div>env full rollout：<StatusPill active={summary.env_fuse.allow_full_rollout_env} /></div>
                <div>DB 自动回复：<StatusPill active={summary.db_config.auto_reply_enabled} /></div>
                <div>DB 真实发送：<StatusPill active={summary.db_config.real_send_enabled} /></div>
                <div>DB full rollout：<StatusPill active={summary.db_config.allow_full_rollout} /></div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-9">
                {stats.map((item) => (
                  <StatCard key={item.label} label={item.label} value={item.value} />
                ))}
              </div>
            </section>

            <section className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(360px,0.75fr)_minmax(0,1.25fr)]">
              <div className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
                <SectionTitle title="全局控制" hint="修改后端 DB 管理层开关，不修改 env 熔断" />
                <div className="mt-4 space-y-3">
                  <ToggleInput
                    label="DB 自动回复启用"
                    checked={globalForm.auto_reply_enabled}
                    onChange={(checked) => setGlobalForm((current) => ({ ...current, auto_reply_enabled: checked }))}
                  />
                  <ToggleInput
                    label="DB 真实发送启用"
                    checked={globalForm.real_send_enabled}
                    onChange={(checked) => setGlobalForm((current) => ({ ...current, real_send_enabled: checked }))}
                  />
                  <ToggleInput
                    label="DB full rollout 启用"
                    checked={globalForm.allow_full_rollout}
                    onChange={(checked) => setGlobalForm((current) => ({ ...current, allow_full_rollout: checked }))}
                  />
                  <textarea
                    aria-label="修改原因"
                    value={globalForm.reason}
                    onChange={(event) => setGlobalForm((current) => ({ ...current, reason: event.target.value }))}
                    className="min-h-[70px] w-full resize-none rounded-xl border border-[#dbe3ef] px-3 py-2 text-xs outline-none focus:border-[#2563eb]"
                    placeholder="填写本次修改原因"
                  />
                  <div className="flex flex-wrap justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => void handleEmergencyPause("real_send_enabled")}
                      className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-red-50 px-3 text-xs font-semibold text-red-700"
                    >
                      <PauseCircleIcon size={14} />
                      一键暂停真实发送
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleSaveGlobal()}
                      disabled={savingGlobal}
                      className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white disabled:opacity-60"
                    >
                      {savingGlobal ? <RefreshCwIcon size={14} className="animate-spin" /> : <ShieldCheckIcon size={14} />}
                      保存全局配置
                    </button>
                  </div>
                  {envRealSendDisabled ? (
                    <p className="text-[11px] font-semibold text-red-600">当前仍受系统熔断限制，不会真实发送。</p>
                  ) : null}
                </div>
              </div>

              <div className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
                <SectionTitle title="企业号控制" hint="send_enabled 开启不代表一定会真实发送，仍需所有后端 gate 通过" />
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full min-w-[980px] text-left text-xs">
                    <thead className="bg-[#f8fafc] text-[#64748b]">
                      <tr>
                        <th className="px-3 py-2 font-semibold">企业号</th>
                        <th className="px-3 py-2 font-semibold">merchant_id</th>
                        <th className="px-3 py-2 font-semibold">enabled</th>
                        <th className="px-3 py-2 font-semibold">send_enabled</th>
                        <th className="px-3 py-2 font-semibold">Agent</th>
                        <th className="px-3 py-2 font-semibold">今日统计</th>
                        <th className="px-3 py-2 font-semibold">最后阻断</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#eef2f6]">
                      {accounts.map((account) => (
                        <tr key={`${account.merchant_id}-${account.account_open_id_masked || account.account_name}`}>
                          <td className="px-3 py-3">
                            <div className="font-bold text-[#1a1f2e]">{account.account_name || "未命名企业号"}</div>
                            <div className="mt-1 text-[11px] text-[#8b95a6]">{account.account_open_id_masked || "-"}</div>
                            {account.db_account_whitelist_hit ? (
                              <span className="mt-1 inline-flex rounded bg-[#eff6ff] px-1.5 py-0.5 text-[10px] font-semibold text-[#2563eb]">
                                账号白名单
                              </span>
                            ) : null}
                          </td>
                          <td className="px-3 py-3 text-[#475467]">{account.merchant_id}</td>
                          <td className="px-3 py-3">
                            <button
                              onClick={() => void handleToggleAccount(account, "enabled", !account.enabled)}
                              className={`h-8 rounded-lg px-2.5 text-[11px] font-semibold ${
                                account.enabled ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"
                              }`}
                            >
                              {account.enabled ? "开启" : "关闭"}
                            </button>
                          </td>
                          <td className="px-3 py-3">
                            <button
                              onClick={() => void handleToggleAccount(account, "send_enabled", !account.send_enabled)}
                              className={`h-8 rounded-lg px-2.5 text-[11px] font-semibold ${
                                account.send_enabled ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-600"
                              }`}
                            >
                              {account.send_enabled ? "开启" : "关闭"}
                            </button>
                          </td>
                          <td className="px-3 py-3 text-[#475467]">{account.bound_agent_name || account.bound_agent_id || "-"}</td>
                          <td className="px-3 py-3 text-[#475467]">
                            dry-run {account.today_dry_run_count} / sent {account.today_sent_count} / blocked {account.today_blocked_count}
                          </td>
                          <td className="px-3 py-3 text-[#64748b]">{readableReason(account.last_blocked_reason)}</td>
                        </tr>
                      ))}
                      {!accounts.length ? (
                        <tr>
                          <td colSpan={7} className="px-3 py-8 text-center text-[#98a2b3]">暂无企业号配置</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <section className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(360px,0.7fr)_minmax(0,1.3fr)]">
              <div className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
                <SectionTitle title="测试范围 / 白名单控制" hint="value 展示只使用后端脱敏字段" />
                <div className="mt-4 grid gap-3">
                  <select
                    aria-label="白名单类型"
                    value={whitelistForm.entry_type}
                    onChange={(event) => setWhitelistForm((current) => ({ ...current, entry_type: event.target.value as WhitelistType }))}
                    className="h-10 rounded-xl border border-[#dbe3ef] bg-white px-3 text-xs"
                  >
                    <option value="account">企业号</option>
                    <option value="customer">客户</option>
                    <option value="conversation">会话</option>
                  </select>
                  <input
                    aria-label="merchant_id"
                    value={whitelistForm.merchant_id}
                    onChange={(event) => setWhitelistForm((current) => ({ ...current, merchant_id: event.target.value }))}
                    className="h-10 rounded-xl border border-[#dbe3ef] px-3 text-xs"
                    placeholder="merchant_id"
                  />
                  <input
                    aria-label="account_open_id"
                    value={whitelistForm.account_open_id || ""}
                    onChange={(event) => setWhitelistForm((current) => ({ ...current, account_open_id: event.target.value }))}
                    className="h-10 rounded-xl border border-[#dbe3ef] px-3 text-xs"
                    placeholder="account_open_id（客户/会话可选）"
                  />
                  <input
                    aria-label="白名单值"
                    value={whitelistForm.value}
                    onChange={(event) => setWhitelistForm((current) => ({ ...current, value: event.target.value }))}
                    className="h-10 rounded-xl border border-[#dbe3ef] px-3 text-xs"
                    placeholder="白名单值"
                  />
                  <textarea
                    aria-label="新增原因"
                    value={whitelistForm.reason}
                    onChange={(event) => setWhitelistForm((current) => ({ ...current, reason: event.target.value }))}
                    className="min-h-[64px] resize-none rounded-xl border border-[#dbe3ef] px-3 py-2 text-xs"
                    placeholder="新增原因"
                  />
                  <button
                    type="button"
                    onClick={() => void handleAddWhitelist()}
                    className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white"
                  >
                    添加白名单
                  </button>
                </div>
              </div>

              <div className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
                <SectionTitle title="白名单列表" />
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full min-w-[860px] text-left text-xs">
                    <thead className="bg-[#f8fafc] text-[#64748b]">
                      <tr>
                        <th className="px-3 py-2 font-semibold">类型</th>
                        <th className="px-3 py-2 font-semibold">merchant_id</th>
                        <th className="px-3 py-2 font-semibold">企业号</th>
                        <th className="px-3 py-2 font-semibold">value</th>
                        <th className="px-3 py-2 font-semibold">状态</th>
                        <th className="px-3 py-2 font-semibold">原因 / 操作人</th>
                        <th className="px-3 py-2 font-semibold">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#eef2f6]">
                      {whitelist.map((entry) => (
                        <tr key={entry.id}>
                          <td className="px-3 py-3">{entry.entry_type}</td>
                          <td className="px-3 py-3">{entry.merchant_id}</td>
                          <td className="px-3 py-3">{entry.account_open_id_masked || "-"}</td>
                          <td className="px-3 py-3">{entry.value_masked || "-"}</td>
                          <td className="px-3 py-3"><StatusPill active={entry.enabled} activeText="启用" inactiveText="禁用" /></td>
                          <td className="px-3 py-3 text-[#64748b]">
                            <div>{entry.reason || "-"}</div>
                            <div className="mt-1 text-[11px]">
                              {entry.created_by || "-"} · {formatDateTimeLocal(entry.created_at)}
                            </div>
                            {entry.disabled_by ? (
                              <div className="mt-1 text-[11px] text-red-500">
                                禁用：{entry.disabled_by} · {formatDateTimeLocal(entry.disabled_at)}
                              </div>
                            ) : null}
                          </td>
                          <td className="px-3 py-3">
                            <button
                              type="button"
                              disabled={!entry.enabled}
                              onClick={() => void handleDeleteWhitelist(entry)}
                              className="inline-flex h-8 items-center gap-1 rounded-lg bg-red-50 px-2.5 text-[11px] font-semibold text-red-600 disabled:opacity-40"
                            >
                              <Trash2Icon size={13} />
                              移除
                            </button>
                          </td>
                        </tr>
                      ))}
                      {!whitelist.length ? (
                        <tr>
                          <td colSpan={7} className="px-3 py-8 text-center text-[#98a2b3]">暂无白名单</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <section className="mt-5 rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <SectionTitle title="审计与回滚" hint="只展示 run 摘要，不展示完整客户消息、完整提示词或原始响应" />
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void handleEmergencyPause("real_send_enabled")}
                    className="inline-flex h-8 items-center gap-1 rounded-lg bg-red-50 px-3 text-xs font-semibold text-red-700"
                  >
                    <RotateCcwIcon size={13} />
                    关闭 DB 真实发送
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleEmergencyPause("auto_reply_enabled")}
                    className="inline-flex h-8 items-center gap-1 rounded-lg bg-slate-100 px-3 text-xs font-semibold text-slate-700"
                  >
                    关闭 DB 自动回复
                  </button>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <input
                  aria-label="筛选 mode"
                  value={runsFilter.mode}
                  onChange={(event) => setRunsFilter((current) => ({ ...current, mode: event.target.value }))}
                  className="h-9 w-[160px] rounded-xl border border-[#dbe3ef] px-3 text-xs"
                  placeholder="mode"
                />
                <input
                  aria-label="筛选 status"
                  value={runsFilter.status}
                  onChange={(event) => setRunsFilter((current) => ({ ...current, status: event.target.value }))}
                  className="h-9 w-[140px] rounded-xl border border-[#dbe3ef] px-3 text-xs"
                  placeholder="status"
                />
                <input
                  aria-label="筛选 blocked_reason"
                  value={runsFilter.blocked_reason}
                  onChange={(event) => setRunsFilter((current) => ({ ...current, blocked_reason: event.target.value }))}
                  className="h-9 w-[190px] rounded-xl border border-[#dbe3ef] px-3 text-xs"
                  placeholder="blocked_reason"
                />
                <input
                  aria-label="筛选 account_open_id"
                  value={runsFilter.account_open_id}
                  onChange={(event) => setRunsFilter((current) => ({ ...current, account_open_id: event.target.value }))}
                  className="h-9 w-[200px] rounded-xl border border-[#dbe3ef] px-3 text-xs"
                  placeholder="account_open_id"
                />
                <button
                  type="button"
                  onClick={() => void loadRuns()}
                  className="h-9 rounded-xl border border-[#dbe3ef] bg-white px-4 text-xs font-semibold text-[#475467]"
                >
                  筛选
                </button>
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[1160px] text-left text-xs">
                  <thead className="bg-[#f8fafc] text-[#64748b]">
                    <tr>
                      <th className="px-3 py-2 font-semibold">run</th>
                      <th className="px-3 py-2 font-semibold">mode / status</th>
                      <th className="px-3 py-2 font-semibold">发送门禁</th>
                      <th className="px-3 py-2 font-semibold">阻断 / fallback</th>
                      <th className="px-3 py-2 font-semibold">RAG</th>
                      <th className="px-3 py-2 font-semibold">rollout 快照</th>
                      <th className="px-3 py-2 font-semibold">时间</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#eef2f6]">
                    {runs.map((run) => (
                      <tr key={run.run_id}>
                        <td className="px-3 py-3">
                          <div className="font-bold text-[#1a1f2e]">#{run.run_id}</div>
                          <div className="mt-1 text-[11px] text-[#8b95a6]">{run.account_open_id_masked || "-"}</div>
                        </td>
                        <td className="px-3 py-3 text-[#475467]">{run.mode || "-"} / {run.status || "-"}</td>
                        <td className="px-3 py-3 text-[#475467]">
                          final_auto_send={boolText(run.final_auto_send)}
                          <br />
                          send_gate_passed={boolText(run.send_gate_passed)}
                        </td>
                        <td className="px-3 py-3 text-[#64748b]">
                          {readableReason(run.blocked_reason)}
                          <br />
                          fallback：{readableReason(run.fallback_reason)}
                        </td>
                        <td className="px-3 py-3 text-[#475467]">
                          {run.rag_used ? "已使用" : "未使用"} · sources {run.rag_sources_count}
                        </td>
                        <td className="px-3 py-3">
                          <pre className="max-h-20 overflow-auto rounded-lg bg-[#f8fafc] p-2 text-[10px] leading-4 text-[#64748b]">
                            {JSON.stringify({ db: run.db_rollout || {}, env: run.env_rollout || {} }, null, 2)}
                          </pre>
                        </td>
                        <td className="px-3 py-3 text-[#64748b]">{formatDateTimeLocal(run.created_at)}</td>
                      </tr>
                    ))}
                    {!runs.length ? (
                      <tr>
                        <td colSpan={7} className="px-3 py-8 text-center text-[#98a2b3]">暂无 run 记录</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : loading ? (
          <div className="grid h-[320px] place-items-center text-xs font-semibold text-[#64748b]">正在加载...</div>
        ) : null}
      </main>
    </section>
  );
}
