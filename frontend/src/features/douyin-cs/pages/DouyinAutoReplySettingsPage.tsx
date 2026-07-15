import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  LoaderIcon,
  RefreshCwIcon,
  SaveIcon,
  ShieldCheckIcon,
  SlidersHorizontalIcon,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import {
  getDouyinAutoReplySetting,
  getDouyinAutoReplySettings,
  updateDouyinAutoReplySetting,
} from "../api";
import type {
  DirectLlmPolicy,
  DouyinAutoReplySettingItem,
  DouyinAutoReplySettingUpdateRequest,
} from "../types";
import { userFacingError } from "../../../lib/userFacingError";

const DEFAULT_DIRECT_LLM_POLICY: DirectLlmPolicy = {
  direct_llm_auto_send_enabled: false,
  policy_level: "aggressive",
  allow_greeting_auto_send: false,
  allow_general_intro_auto_send: false,
  allow_need_clarification_auto_send: false,
  allow_brand_general_intro_auto_send: false,
  specific_model_strategy: "safe_clarify",
  contact_guidance_level: "soft_guidance",
  require_rag_for_specific_inventory: false,
  forbid_inventory_claim: false,
  forbid_price_claim: false,
  forbid_finance_claim: false,
  forbid_vehicle_condition_claim: false,
  min_confidence_for_direct_send: 0,
  content_gates_enabled: false,
};

const SIMPLE_ENABLED_DIRECT_LLM_POLICY: DirectLlmPolicy = {
  ...DEFAULT_DIRECT_LLM_POLICY,
  direct_llm_auto_send_enabled: true,
  allow_greeting_auto_send: true,
  allow_general_intro_auto_send: true,
  allow_need_clarification_auto_send: true,
  allow_brand_general_intro_auto_send: true,
};

function resolveErrorMessage(error: unknown): string {
  return userFacingError(error, "数据加载失败，请稍后重试");
}

function displayAccountName(item: DouyinAutoReplySettingItem | null): string {
  if (!item) return "-";
  return item.account_name || item.nickname || "未命名企业号";
}

function compactOpenId(value?: string | null): string {
  if (!value) return "-";
  return value.length > 18 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value;
}

function defaultForm(item?: DouyinAutoReplySettingItem | null): DouyinAutoReplySettingUpdateRequest {
  const directLlmPolicy = {
    ...DEFAULT_DIRECT_LLM_POLICY,
    ...(item?.direct_llm_policy || {}),
  };
  return {
    enabled: Boolean(item?.enabled),
    dry_run_enabled: Boolean(item?.dry_run_enabled),
    send_enabled: Boolean(item?.send_enabled),
    min_confidence: typeof item?.min_confidence === "number" ? item.min_confidence : 0.9,
    require_rag: item?.require_rag ?? true,
    require_rag_sources: item?.require_rag_sources ?? true,
    allowed_intents: Array.isArray(item?.allowed_intents) ? item.allowed_intents : [],
    blocked_risk_flags: Array.isArray(item?.blocked_risk_flags) ? item.blocked_risk_flags : [],
    max_replies_per_conversation_per_hour:
      typeof item?.max_replies_per_conversation_per_hour === "number"
        ? item.max_replies_per_conversation_per_hour
        : 1,
    max_replies_per_account_per_hour:
      typeof item?.max_replies_per_account_per_hour === "number"
        ? item.max_replies_per_account_per_hour
        : 3,
    customer_whitelist_open_ids: Array.isArray(item?.customer_whitelist_open_ids)
      ? item.customer_whitelist_open_ids
      : [],
    conversation_whitelist_ids: Array.isArray(item?.conversation_whitelist_ids)
      ? item.conversation_whitelist_ids
      : [],
    min_interval_seconds: typeof item?.min_interval_seconds === "number" ? item.min_interval_seconds : 60,
    max_auto_replies_per_conversation_per_day:
      typeof item?.max_auto_replies_per_conversation_per_day === "number"
        ? item.max_auto_replies_per_conversation_per_day
        : 20,
    direct_llm_policy: directLlmPolicy,
  };
}

function applyAiAutoReplyEnabled(
  current: DouyinAutoReplySettingUpdateRequest,
  enabled: boolean,
): DouyinAutoReplySettingUpdateRequest {
  if (!enabled) {
    return {
      ...current,
      enabled: false,
      dry_run_enabled: false,
      send_enabled: false,
      direct_llm_policy: DEFAULT_DIRECT_LLM_POLICY,
    };
  }
  return {
    ...current,
    enabled: true,
    dry_run_enabled: false,
    send_enabled: true,
    min_confidence: 0,
    require_rag: false,
    require_rag_sources: false,
    blocked_risk_flags: [],
    direct_llm_policy: SIMPLE_ENABLED_DIRECT_LLM_POLICY,
  };
}

function normalizeSimpleForm(current: DouyinAutoReplySettingUpdateRequest): DouyinAutoReplySettingUpdateRequest {
  const enabled = current.enabled && current.send_enabled && current.direct_llm_policy.direct_llm_auto_send_enabled;
  if (!enabled) {
    return applyAiAutoReplyEnabled(current, false);
  }
  return {
    ...current,
    enabled: true,
    dry_run_enabled: false,
    send_enabled: true,
    min_confidence: 0,
    require_rag: false,
    require_rag_sources: false,
    blocked_risk_flags: [],
    direct_llm_policy: SIMPLE_ENABLED_DIRECT_LLM_POLICY,
  };
}

export default function DouyinAutoReplySettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryAccountOpenId = searchParams.get("account_open_id")?.trim() || "";
  const [items, setItems] = useState<DouyinAutoReplySettingItem[]>([]);
  const [selectedAccountOpenId, setSelectedAccountOpenId] = useState<string>("");
  const [form, setForm] = useState<DouyinAutoReplySettingUpdateRequest>(defaultForm());
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedItem = useMemo(
    () => items.find((item) => item.account_open_id === selectedAccountOpenId) || null,
    [items, selectedAccountOpenId],
  );
  const aiAutoReplyEnabled =
    form.enabled && form.send_enabled && form.direct_llm_policy.direct_llm_auto_send_enabled;

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextItems = await getDouyinAutoReplySettings();
      setItems(nextItems);
      setSelectedAccountOpenId((current) => {
        if (queryAccountOpenId) return queryAccountOpenId;
        return current || nextItems[0]?.account_open_id || "";
      });
    } catch (err) {
      setItems([]);
      setError(resolveErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [queryAccountOpenId]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  useEffect(() => {
    if (!selectedAccountOpenId) {
      setForm(defaultForm());
      return;
    }
    setDetailLoading(true);
    setError(null);
    getDouyinAutoReplySetting(selectedAccountOpenId)
      .then((detail) => {
        setItems((current) => {
          const exists = current.some((item) => item.account_open_id === detail.account_open_id);
          if (!exists) return [detail, ...current];
          return current.map((item) => (item.account_open_id === detail.account_open_id ? detail : item));
        });
        setForm(defaultForm(detail));
      })
      .catch((err) => setError(resolveErrorMessage(err)))
      .finally(() => setDetailLoading(false));
  }, [selectedAccountOpenId]);

  function handleAiAutoReplyEnabledChange(checked: boolean) {
    setForm((current) => applyAiAutoReplyEnabled(current, checked));
  }

  async function saveSettings(payload: DouyinAutoReplySettingUpdateRequest) {
    if (!selectedAccountOpenId) return;
    setSaving(true);
    setNotice(null);
    try {
      const updated = await updateDouyinAutoReplySetting(selectedAccountOpenId, payload);
      setItems((current) =>
        current.map((item) => (item.account_open_id === updated.account_open_id ? updated : item)),
      );
      setForm(defaultForm(updated));
      setNotice("AI 自动回复设置已保存，后续新客户消息将按当前设置处理。");
      toast.success("AI 自动回复设置已保存，后续新客户消息将按当前设置处理。");
    } catch (err) {
      const message = resolveErrorMessage(err);
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  function handleSave() {
    if (!selectedAccountOpenId || saving) return;
    void saveSettings(normalizeSimpleForm(form));
  }

  function handleSelectAccount(accountOpenId: string) {
    setSelectedAccountOpenId(accountOpenId);
    setSearchParams({ account_open_id: accountOpenId });
  }

  const accountCards = items.map((item) => {
    const active = item.account_open_id === selectedAccountOpenId;
    return (
      <button
        key={item.account_open_id}
        type="button"
        onClick={() => handleSelectAccount(item.account_open_id)}
        className={`w-full rounded-md border px-3 py-3 text-left transition-colors ${
          active ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"
        }`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-xs font-bold text-slate-800">{displayAccountName(item)}</div>
            <div className="mt-1 font-mono text-[10px] text-slate-500">{compactOpenId(item.account_open_id)}</div>
          </div>
          <span
            className={`rounded-md px-2 py-0.5 text-[10px] font-bold ${
              item.send_enabled ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"
            }`}
          >
            {item.send_enabled ? "真实回复" : item.dry_run_enabled ? "演练" : "关闭"}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-1 text-[10px] font-semibold">
          <span className={item.enabled ? "text-emerald-600" : "text-slate-400"}>总开关</span>
          <span className={item.dry_run_enabled ? "text-blue-600" : "text-slate-400"}>决策记录</span>
          <span className={item.send_enabled ? "text-amber-600" : "text-slate-400"}>真实回复</span>
        </div>
      </button>
    );
  });

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <SlidersHorizontalIcon size={21} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">AI自动回复配置</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">
              按抖音企业号开启或关闭 AI 自动回复
            </p>
          </div>
        </div>
        <button
          onClick={() => void loadSettings()}
          disabled={loading}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#475467] disabled:opacity-60"
        >
          <RefreshCwIcon size={14} className={loading ? "animate-spin" : ""} />
          刷新
        </button>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)] overflow-hidden">
        <aside className="min-h-0 overflow-y-auto border-r border-[#e4e8f0] bg-white p-4">
          <div className="mb-3 text-xs font-bold text-slate-700">企业号配置</div>
          {loading && items.length === 0 ? (
            <div className="flex min-h-[180px] items-center justify-center gap-2 text-xs text-slate-500">
              <LoaderIcon size={16} className="animate-spin" />
              加载中...
            </div>
          ) : items.length === 0 ? (
            <div className="rounded-md border border-dashed border-slate-200 px-4 py-8 text-center text-xs leading-6 text-slate-500">
              暂无可配置的抖音企业号，请先在抖音客服工作台绑定企业号后再配置
            </div>
          ) : (
            <div className="space-y-2">{accountCards}</div>
          )}
        </aside>

        <main className="min-h-0 overflow-y-auto p-5">
          <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 px-4 py-3">
            <div className="flex items-start gap-3">
              <ShieldCheckIcon size={17} className="mt-0.5 shrink-0 text-blue-600" />
              <div className="text-xs leading-6 text-blue-800">
                <div className="font-bold">开启后，客户发送私信时，AI 会自动生成回复并发送。</div>
                <div>当前为简化模式：暂不启用价格、库存、金融、车况、联系方式等拦截规则。</div>
                <div>后续如需增加拦截规则，可在确认规则后再配置。</div>
              </div>
            </div>
          </div>

          {error ? (
            <div className="mb-4 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-xs leading-5 text-red-700">
              <AlertTriangleIcon size={15} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          ) : null}

          {notice ? (
            <div className="mb-4 flex items-start gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs leading-5 text-emerald-700">
              <CheckCircle2Icon size={15} className="mt-0.5 shrink-0" />
              <span>{notice}</span>
            </div>
          ) : null}

          {!selectedItem ? (
            <div className="grid min-h-[420px] place-items-center rounded-md border border-dashed border-slate-200 bg-white text-xs text-slate-500">
              请选择一个抖音企业号
            </div>
          ) : (
            <div className="space-y-4">
              <section className="rounded-md border border-slate-200 bg-white">
                <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
                  <div>
                    <h2 className="text-sm font-bold text-slate-900">{displayAccountName(selectedItem)}</h2>
                    <p className="mt-1 font-mono text-[11px] text-slate-500">{selectedItem.account_open_id}</p>
                  </div>
                  {detailLoading ? (
                    <span className="inline-flex items-center gap-2 text-xs text-slate-500">
                      <LoaderIcon size={14} className="animate-spin" />
                      加载中
                    </span>
                  ) : null}
                </div>

                <div className="space-y-5 p-4">
                  <section className="rounded-md border border-blue-200 bg-blue-50 px-4 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="max-w-[640px]">
                        <div className="text-sm font-bold text-slate-900">AI 自动回复</div>
                        <div className="mt-2 text-xs leading-6 text-slate-600">
                          <div>开启后，客户发送私信时，AI 会自动生成回复并发送。</div>
                          <div>当前为简化模式：暂不启用价格、库存、金融、车况、联系方式等拦截规则。</div>
                          <div>后续如需增加拦截规则，可在确认规则后再配置。</div>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        <span className="text-xs font-bold text-slate-800">
                          {aiAutoReplyEnabled ? "开" : "关"}
                        </span>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={aiAutoReplyEnabled}
                          onClick={() => handleAiAutoReplyEnabledChange(!aiAutoReplyEnabled)}
                          className={`relative h-7 w-14 rounded-full transition-colors ${
                            aiAutoReplyEnabled ? "bg-emerald-500" : "bg-slate-300"
                          }`}
                        >
                          <span
                            className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                              aiAutoReplyEnabled ? "translate-x-8" : "translate-x-1"
                            }`}
                          />
                        </button>
                      </div>
                    </div>
                  </section>

                  <div className="flex justify-end border-t border-slate-200 pt-4">
                    <button
                      type="button"
                      onClick={handleSave}
                      disabled={saving || detailLoading}
                      className="inline-flex h-10 items-center gap-2 rounded-md bg-blue-600 px-4 text-xs font-bold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {saving ? <LoaderIcon size={14} className="animate-spin" /> : <SaveIcon size={14} />}
                      保存设置
                    </button>
                  </div>
                </div>
              </section>
            </div>
          )}
        </main>
      </div>
    </section>
  );
}
