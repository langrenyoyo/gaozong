import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangleIcon,
  BotIcon,
  CheckCircle2Icon,
  LoaderIcon,
  RefreshCwIcon,
  SaveIcon,
  ShieldAlertIcon,
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
  AllowedIntentOption,
  BlockedRiskFlagOption,
  DirectLlmPolicy,
  DouyinAutoReplySettingItem,
  DouyinAutoReplySettingUpdateRequest,
} from "../types";
import { formatDateTimeLocal } from "../../../lib/datetime";

const SEND_ENABLE_CONFIRM_TEXT = "确认开启自动回复";
type SimpleReplyMode = "safe" | "recommended" | "active";

const DEFAULT_DIRECT_LLM_POLICY: DirectLlmPolicy = {
  direct_llm_auto_send_enabled: false,
  policy_level: "conservative",
  allow_greeting_auto_send: false,
  allow_general_intro_auto_send: false,
  allow_need_clarification_auto_send: false,
  allow_brand_general_intro_auto_send: false,
  specific_model_strategy: "manual_confirm",
  contact_guidance_level: "none",
  require_rag_for_specific_inventory: true,
  forbid_inventory_claim: true,
  forbid_price_claim: true,
  forbid_finance_claim: true,
  forbid_vehicle_condition_claim: true,
  min_confidence_for_direct_send: 0.85,
};

const SIMPLE_MODE_POLICIES: Record<SimpleReplyMode, DirectLlmPolicy> = {
  safe: {
    ...DEFAULT_DIRECT_LLM_POLICY,
    direct_llm_auto_send_enabled: true,
    policy_level: "conservative",
    allow_greeting_auto_send: true,
    allow_general_intro_auto_send: true,
    allow_need_clarification_auto_send: false,
    allow_brand_general_intro_auto_send: false,
    specific_model_strategy: "manual_confirm",
    contact_guidance_level: "none",
    min_confidence_for_direct_send: 0.85,
  },
  recommended: {
    ...DEFAULT_DIRECT_LLM_POLICY,
    direct_llm_auto_send_enabled: true,
    policy_level: "standard",
    allow_greeting_auto_send: true,
    allow_general_intro_auto_send: true,
    allow_need_clarification_auto_send: true,
    allow_brand_general_intro_auto_send: true,
    specific_model_strategy: "safe_clarify",
    contact_guidance_level: "none",
    min_confidence_for_direct_send: 0.85,
  },
  active: {
    ...DEFAULT_DIRECT_LLM_POLICY,
    direct_llm_auto_send_enabled: true,
    policy_level: "aggressive",
    allow_greeting_auto_send: true,
    allow_general_intro_auto_send: true,
    allow_need_clarification_auto_send: true,
    allow_brand_general_intro_auto_send: true,
    specific_model_strategy: "safe_clarify",
    contact_guidance_level: "soft_guidance",
    min_confidence_for_direct_send: 0.8,
  },
};

const SIMPLE_MODE_OPTIONS: Array<{ value: SimpleReplyMode; label: string; description: string }> = [
  {
    value: "safe",
    label: "稳妥模式",
    description: "AI 主要回复问候、主营介绍和简单需求澄清。涉及车型、价格、车况时转人工确认。",
  },
  {
    value: "recommended",
    label: "推荐模式",
    description: "适合大多数商户。AI 可自动回复问候、主营介绍、品牌咨询、车型安全澄清，不承诺库存、价格、车况、金融。",
  },
  {
    value: "active",
    label: "积极模式",
    description: "AI 会更主动引导客户补充预算、车型、用途和联系方式，但仍不自动承诺库存、价格、车况、金融。",
  },
];

const ALLOWED_INTENT_OPTIONS: AllowedIntentOption[] = [
  { value: "greeting", label: "问候" },
  { value: "basic_info", label: "基础咨询" },
  { value: "business_scope_intro", label: "业务范围介绍" },
  { value: "lead_capture_soft_guide", label: "温和留资引导" },
];

const BLOCKED_RISK_FLAG_OPTIONS: BlockedRiskFlagOption[] = [
  { value: "price_commitment", label: "价格承诺" },
  { value: "inventory_commitment", label: "库存承诺" },
  { value: "finance_commitment", label: "金融承诺" },
  { value: "insurance_commitment", label: "保险承诺" },
  { value: "trade_in_commitment", label: "置换承诺" },
  { value: "contact_exchange", label: "交换联系方式" },
  { value: "phone_or_wechat_detected", label: "手机号或微信号" },
  { value: "test_drive_or_visit", label: "试驾或到店" },
  { value: "complaint_or_refund", label: "投诉或退款" },
  { value: "prompt_injection", label: "提示词注入" },
  { value: "upstream_auto_send_requested", label: "上游请求发送" },
];

function resolveErrorMessage(error: unknown): string {
  if (error && typeof error === "object") {
    const anyError = error as {
      response?: { data?: { message?: string; detail?: string | { message?: string; safe_message?: string } } };
      message?: string;
    };
    const detail = anyError.response?.data?.detail;
    if (detail && typeof detail === "object") return detail.safe_message || detail.message || "请求失败";
    if (typeof detail === "string") return detail;
    return anyError.response?.data?.message || anyError.message || "请求失败";
  }
  return error instanceof Error ? error.message : "请求失败";
}

function displayAccountName(item: DouyinAutoReplySettingItem | null): string {
  if (!item) return "-";
  return item.account_name || item.nickname || "未命名企业号";
}

function compactOpenId(value?: string | null): string {
  if (!value) return "-";
  return value.length > 18 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value;
}

function bindStatusText(value?: number | string | null): string {
  if (value === 1 || value === "1" || value === "authorized") return "已授权";
  if (value === 0 || value === "0" || value === "unauthorized") return "未授权";
  return value ? String(value) : "未知";
}

function agentStatusText(value?: string | null): string {
  if (value === "active") return "已启用";
  if (value === "inactive") return "未启用";
  if (value === "deleted") return "已删除";
  return value || "未绑定";
}

function hasActiveAgent(item: DouyinAutoReplySettingItem | null): boolean {
  return Boolean(item?.bound_agent_id && item.bound_agent_status === "active");
}

function listToText(value: string[] | null | undefined): string {
  return Array.isArray(value) ? value.join("\n") : "";
}

function textToList(value: string): string[] {
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
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

function updateDirectLlmPolicy<K extends keyof DirectLlmPolicy>(
  current: DouyinAutoReplySettingUpdateRequest,
  key: K,
  value: DirectLlmPolicy[K],
): DouyinAutoReplySettingUpdateRequest {
  return {
    ...current,
    direct_llm_policy: {
      ...DEFAULT_DIRECT_LLM_POLICY,
      ...current.direct_llm_policy,
      [key]: value,
    },
  };
}

function inferSimpleReplyMode(policy: DirectLlmPolicy): SimpleReplyMode {
  if (policy.policy_level === "aggressive") return "active";
  if (policy.direct_llm_auto_send_enabled && policy.policy_level === "conservative") return "safe";
  return "recommended";
}

function applySimpleReplyMode(
  current: DouyinAutoReplySettingUpdateRequest,
  mode: SimpleReplyMode,
  enabled = current.direct_llm_policy.direct_llm_auto_send_enabled,
): DouyinAutoReplySettingUpdateRequest {
  return {
    ...current,
    direct_llm_policy: {
      ...SIMPLE_MODE_POLICIES[mode],
      direct_llm_auto_send_enabled: enabled,
    },
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
      send_enabled: false,
      direct_llm_policy: {
        ...current.direct_llm_policy,
        direct_llm_auto_send_enabled: false,
      },
    };
  }
  return {
    ...applySimpleReplyMode(current, inferSimpleReplyMode(current.direct_llm_policy), true),
    enabled: true,
    dry_run_enabled: true,
    send_enabled: true,
  };
}

function Toggle({
  checked,
  onChange,
  label,
  description,
  tone = "blue",
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description: string;
  tone?: "blue" | "amber" | "emerald";
}) {
  const enabledClass =
    tone === "amber" ? "bg-amber-500" : tone === "emerald" ? "bg-emerald-500" : "bg-blue-600";
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-md border border-slate-200 bg-white px-3 py-3">
      <span>
        <span className="block text-xs font-bold text-slate-800">{label}</span>
        <span className="mt-1 block text-[11px] leading-5 text-slate-500">{description}</span>
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors ${checked ? enabledClass : "bg-slate-300"}`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
            checked ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
    </label>
  );
}

function MultiSelectChips({
  options,
  value,
  onChange,
}: {
  options: Array<{ value: string; label: string }>;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const selected = new Set(value);
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => {
        const active = selected.has(option.value);
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => {
              const next = active
                ? value.filter((item) => item !== option.value)
                : [...value, option.value];
              onChange(next);
            }}
            className={`rounded-md border px-3 py-1.5 text-[11px] font-semibold transition-colors ${
              active
                ? "border-blue-200 bg-blue-50 text-blue-700"
                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function SendEnableConfirmModal({
  open,
  confirmText,
  onConfirmTextChange,
  onCancel,
  onConfirm,
  saving,
}: {
  open: boolean;
  confirmText: string;
  onConfirmTextChange: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
  saving: boolean;
}) {
  if (!open) return null;
  const canConfirm = confirmText === SEND_ENABLE_CONFIRM_TEXT && !saving;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 px-4">
      <div className="w-full max-w-[560px] overflow-hidden rounded-lg border border-amber-200 bg-white shadow-[0_24px_80px_rgba(15,23,42,0.28)]">
        <div className="border-b border-amber-200 bg-amber-50 px-5 py-4">
          <div className="flex items-start gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-white text-amber-600">
              <ShieldAlertIcon size={18} />
            </span>
            <div>
              <h2 className="text-sm font-bold text-amber-900">确认开启真实自动回复</h2>
              <p className="mt-1 text-xs leading-5 text-amber-800">
                开启后，该企业号在满足系统全局开关、人工接管、频控和安全上下文条件时，将自动回复客户私信。
              </p>
            </div>
          </div>
        </div>
        <div className="space-y-3 px-5 py-5 text-xs leading-6 text-slate-600">
          <p>注意：开启自动回复会真实发送抖音私信。请确认智能体话术、频控和人工接管策略已配置完成。</p>
          <p>
            若客户 / 会话白名单为空，则在系统允许全量模式时对该企业号全部客户生效。
          </p>
          <label className="block">
            <span className="font-semibold text-slate-700">
              请输入“{SEND_ENABLE_CONFIRM_TEXT}”
            </span>
            <input
              value={confirmText}
              onChange={(event) => onConfirmTextChange(event.target.value)}
              className="mt-2 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-amber-400 focus:ring-4 focus:ring-amber-500/10"
            />
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 px-5 py-4">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="h-9 rounded-md border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!canConfirm}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-amber-600 px-4 text-xs font-semibold text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? <LoaderIcon size={14} className="animate-spin" /> : null}
            确认开启
          </button>
        </div>
      </div>
    </div>
  );
}

export default function DouyinAutoReplySettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryAccountOpenId = searchParams.get("account_open_id")?.trim() || "";
  const [items, setItems] = useState<DouyinAutoReplySettingItem[]>([]);
  const [selectedAccountOpenId, setSelectedAccountOpenId] = useState<string>("");
  const [form, setForm] = useState<DouyinAutoReplySettingUpdateRequest>(defaultForm());
  const [savedSendEnabled, setSavedSendEnabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const selectedItem = useMemo(
    () => items.find((item) => item.account_open_id === selectedAccountOpenId) || null,
    [items, selectedAccountOpenId],
  );
  const aiAutoReplyEnabled =
    form.enabled && form.send_enabled && form.direct_llm_policy.direct_llm_auto_send_enabled;
  const simpleReplyMode = inferSimpleReplyMode(form.direct_llm_policy);

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
      setSavedSendEnabled(false);
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
        setSavedSendEnabled(Boolean(detail.send_enabled));
      })
      .catch((err) => setError(resolveErrorMessage(err)))
      .finally(() => setDetailLoading(false));
  }, [selectedAccountOpenId]);

  function updateForm<K extends keyof DouyinAutoReplySettingUpdateRequest>(
    key: K,
    value: DouyinAutoReplySettingUpdateRequest[K],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updatePolicy<K extends keyof DirectLlmPolicy>(key: K, value: DirectLlmPolicy[K]) {
    setForm((current) => updateDirectLlmPolicy(current, key, value));
  }

  function handleAiAutoReplyEnabledChange(checked: boolean) {
    setForm((current) => applyAiAutoReplyEnabled(current, checked));
  }

  function handleSimpleReplyModeChange(mode: SimpleReplyMode) {
    setForm((current) => applySimpleReplyMode(current, mode, true));
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
      setSavedSendEnabled(Boolean(updated.send_enabled));
      setNotice("自动回复策略已保存。策略只影响后续新客户消息，不会重跑历史自动回复记录。");
      toast.success("自动回复策略已保存");
    } catch (err) {
      const message = resolveErrorMessage(err);
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
      setConfirmOpen(false);
      setConfirmText("");
    }
  }

  function handleSave() {
    if (!selectedAccountOpenId || saving) return;
    if (!savedSendEnabled && form.send_enabled) {
      setConfirmText("");
      setConfirmOpen(true);
      return;
    }
    void saveSettings(form);
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
            {item.send_enabled ? "真实回复" : item.dry_run_enabled ? "dry-run" : "关闭"}
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
              按抖音企业号保存自动回复门禁配置；此页面不提供发送动作
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
            <div className="grid min-h-[180px] place-items-center text-xs text-slate-500">加载中...</div>
          ) : items.length === 0 ? (
            <div className="rounded-md border border-dashed border-slate-200 px-4 py-8 text-center text-xs leading-6 text-slate-500">
              暂无可配置的抖音企业号
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
                <div className="font-bold">此页面只保存配置，不会立即发送消息。</div>
                <div>开启后，该企业号在满足系统全局开关、人工接管、频控和安全上下文条件时，将自动回复客户私信。</div>
                <div>若客户 / 会话白名单为空，则在系统允许全量模式时对该企业号全部客户生效。</div>
                <div>注意：开启自动回复会真实发送抖音私信。请确认智能体话术、频控和人工接管策略已配置完成。</div>
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
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
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
                      <div>
                        <div className="text-sm font-bold text-slate-900">AI 自动回复</div>
                        <div className="mt-1 text-xs leading-5 text-slate-600">
                          开启后仅影响后续新客户消息，不会重跑历史自动回复记录。
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

                    <div className="mt-4">
                      <div className="mb-2 text-xs font-bold text-slate-800">回复模式</div>
                      <div className="grid gap-3 lg:grid-cols-3">
                        {SIMPLE_MODE_OPTIONS.map((option) => {
                          const active = simpleReplyMode === option.value;
                          return (
                            <button
                              key={option.value}
                              type="button"
                              onClick={() => handleSimpleReplyModeChange(option.value)}
                              className={`rounded-md border px-3 py-3 text-left transition-colors ${
                                active
                                  ? "border-blue-300 bg-white text-blue-900 shadow-sm"
                                  : "border-blue-100 bg-white/70 text-slate-700 hover:bg-white"
                              }`}
                            >
                              <span className="block text-xs font-bold">{option.label}</span>
                              <span className="mt-2 block text-[11px] leading-5 text-slate-600">
                                {option.description}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-5 text-amber-800">
                      系统始终禁止自动承诺库存、价格、车况、金融、过户、质保等事实信息。
                    </div>
                  </section>

                  <details className="rounded-md border border-slate-200 bg-white">
                    <summary className="cursor-pointer px-4 py-3 text-xs font-bold text-slate-800">
                      高级设置（一般无需修改）
                    </summary>
                    <div className="space-y-5 border-t border-slate-200 p-4">
                  <div className="grid gap-3 lg:grid-cols-3">
                    <Toggle
                      checked={form.enabled}
                      onChange={(checked) => updateForm("enabled", checked)}
                      label="总开关"
                      description="关闭后后端会跳过该企业号自动回复链路。"
                      tone="emerald"
                    />
                    <Toggle
                      checked={form.dry_run_enabled}
                      onChange={(checked) => updateForm("dry_run_enabled", checked)}
                      label="只决策不发送"
                      description="记录自动回复决策，用于上线前观察验收。"
                    />
                    <Toggle
                      checked={form.send_enabled}
                      onChange={(checked) => updateForm("send_enabled", checked)}
                      label="允许真实自动回复"
                      description="新私信进入后仍需通过全局开关、人工接管、频控和安全上下文门禁。"
                      tone="amber"
                    />
                  </div>

                  <div className="grid gap-4 lg:grid-cols-3">
                    <label className="block">
                      <span className="text-xs font-bold text-slate-700">最低置信度</span>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={form.min_confidence}
                        onChange={(event) => updateForm("min_confidence", Number(event.target.value))}
                        className="mt-2 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                      />
                    </label>
                    <label className="block">
                      <span className="text-xs font-bold text-slate-700">单会话每小时上限</span>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={form.max_replies_per_conversation_per_hour}
                        onChange={(event) =>
                          updateForm("max_replies_per_conversation_per_hour", Number(event.target.value))
                        }
                        className="mt-2 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                      />
                    </label>
                    <label className="block">
                      <span className="text-xs font-bold text-slate-700">单账号每小时上限</span>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={form.max_replies_per_account_per_hour}
                        onChange={(event) =>
                          updateForm("max_replies_per_account_per_hour", Number(event.target.value))
                        }
                        className="mt-2 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                      />
                    </label>
                  </div>

                  <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-6 text-amber-800">
                    <div className="font-bold">客户 / 会话白名单</div>
                    <div>
                      可选。填写后仅对白名单客户或会话自动回复；留空则按当前账号自动回复开关全量生效。
                    </div>
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <label className="block">
                      <span className="text-xs font-bold text-slate-700">客户 open_id 白名单</span>
                      <textarea
                        value={listToText(form.customer_whitelist_open_ids)}
                        onChange={(event) =>
                          updateForm("customer_whitelist_open_ids", textToList(event.target.value))
                        }
                        placeholder="每行一个客户 open_id，留空表示不按客户限制"
                        className="mt-2 min-h-[96px] w-full resize-y rounded-md border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                      />
                    </label>
                    <label className="block">
                      <span className="text-xs font-bold text-slate-700">会话 ID 白名单</span>
                      <textarea
                        value={listToText(form.conversation_whitelist_ids)}
                        onChange={(event) =>
                          updateForm("conversation_whitelist_ids", textToList(event.target.value))
                        }
                        placeholder="每行一个 conversation_short_id，留空表示不按会话限制"
                        className="mt-2 min-h-[96px] w-full resize-y rounded-md border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                      />
                    </label>
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <label className="block">
                      <span className="text-xs font-bold text-slate-700">最小自动回复间隔（秒）</span>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={form.min_interval_seconds}
                        onChange={(event) => updateForm("min_interval_seconds", Number(event.target.value))}
                        className="mt-2 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                      />
                    </label>
                    <label className="block">
                      <span className="text-xs font-bold text-slate-700">单会话每日自动回复上限</span>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={form.max_auto_replies_per_conversation_per_day}
                        onChange={(event) =>
                          updateForm("max_auto_replies_per_conversation_per_day", Number(event.target.value))
                        }
                        className="mt-2 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                      />
                    </label>
                  </div>

                  <div className="grid gap-3 lg:grid-cols-2">
                    <label className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-3">
                      <span>
                        <span className="block text-xs font-bold text-slate-700">要求 RAG 命中</span>
                        <span className="mt-1 block text-[11px] text-slate-500">未命中知识库时阻断真实回复。</span>
                      </span>
                      <input
                        type="checkbox"
                        checked={form.require_rag}
                        onChange={(event) => updateForm("require_rag", event.target.checked)}
                        className="h-4 w-4"
                      />
                    </label>
                    <label className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-3">
                      <span>
                        <span className="block text-xs font-bold text-slate-700">要求 RAG 来源</span>
                        <span className="mt-1 block text-[11px] text-slate-500">没有可追溯知识来源时阻断真实回复。</span>
                      </span>
                      <input
                        type="checkbox"
                        checked={form.require_rag_sources}
                        onChange={(event) => updateForm("require_rag_sources", event.target.checked)}
                        className="h-4 w-4"
                      />
                    </label>
                  </div>

                  <section className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-xs font-bold text-slate-800">Direct LLM 自动回复策略</div>
                        <div className="mt-1 text-[11px] leading-5 text-slate-500">
                          控制未命中知识库时的低风险回复尺度；系统始终禁止自动承诺库存、价格、车况、金融、过户、质保等事实信息。
                        </div>
                      </div>
                      <label className="flex shrink-0 items-center gap-2 text-xs font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={form.direct_llm_policy.direct_llm_auto_send_enabled}
                          onChange={(event) =>
                            updatePolicy("direct_llm_auto_send_enabled", event.target.checked)
                          }
                          className="h-4 w-4"
                        />
                        允许低风险自动发送
                      </label>
                    </div>

                    <div className="mt-4 grid gap-4 lg:grid-cols-3">
                      <label className="block">
                        <span className="text-xs font-bold text-slate-700">自动发送策略</span>
                        <select
                          value={form.direct_llm_policy.policy_level}
                          onChange={(event) =>
                            updatePolicy("policy_level", event.target.value as DirectLlmPolicy["policy_level"])
                          }
                          className="mt-2 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                        >
                          <option value="conservative">保守：只生成建议</option>
                          <option value="standard">标准：低风险场景可自动回复</option>
                          <option value="aggressive">积极：允许更多引导式回复</option>
                        </select>
                      </label>
                      <label className="block">
                        <span className="text-xs font-bold text-slate-700">具体车型/品牌咨询</span>
                        <select
                          value={form.direct_llm_policy.specific_model_strategy}
                          onChange={(event) =>
                            updatePolicy(
                              "specific_model_strategy",
                              event.target.value as DirectLlmPolicy["specific_model_strategy"],
                            )
                          }
                          className="mt-2 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                        >
                          <option value="manual_confirm">必须人工确认</option>
                          <option value="safe_clarify">自动发送安全澄清话术</option>
                        </select>
                      </label>
                      <label className="block">
                        <span className="text-xs font-bold text-slate-700">联系方式引导</span>
                        <select
                          value={form.direct_llm_policy.contact_guidance_level}
                          onChange={(event) =>
                            updatePolicy(
                              "contact_guidance_level",
                              event.target.value as DirectLlmPolicy["contact_guidance_level"],
                            )
                          }
                          className="mt-2 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10"
                        >
                          <option value="none">不主动索要</option>
                          <option value="customer_initiated_only">仅客户主动要求联系时引导</option>
                          <option value="soft_guidance">允许温和引导留资</option>
                        </select>
                      </label>
                    </div>

                    <div className="mt-4 grid gap-3 lg:grid-cols-4">
                      <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={form.direct_llm_policy.allow_greeting_auto_send}
                          onChange={(event) => updatePolicy("allow_greeting_auto_send", event.target.checked)}
                          className="h-4 w-4"
                        />
                        问候可自动回复
                      </label>
                      <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={form.direct_llm_policy.allow_general_intro_auto_send}
                          onChange={(event) => updatePolicy("allow_general_intro_auto_send", event.target.checked)}
                          className="h-4 w-4"
                        />
                        主营介绍可自动回复
                      </label>
                      <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={form.direct_llm_policy.allow_need_clarification_auto_send}
                          onChange={(event) => updatePolicy("allow_need_clarification_auto_send", event.target.checked)}
                          className="h-4 w-4"
                        />
                        需求澄清可自动回复
                      </label>
                      <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={form.direct_llm_policy.allow_brand_general_intro_auto_send}
                          onChange={(event) =>
                            updatePolicy("allow_brand_general_intro_auto_send", event.target.checked)
                          }
                          className="h-4 w-4"
                        />
                        品牌泛咨询可自动回复
                      </label>
                    </div>
                  </section>

                  <div>
                    <div className="mb-2 text-xs font-bold text-slate-700">允许意图</div>
                    <MultiSelectChips
                      options={ALLOWED_INTENT_OPTIONS}
                      value={form.allowed_intents}
                      onChange={(value) => updateForm("allowed_intents", value)}
                    />
                  </div>

                  <div>
                    <div className="mb-2 text-xs font-bold text-slate-700">阻断风险标记</div>
                    <MultiSelectChips
                      options={BLOCKED_RISK_FLAG_OPTIONS}
                      value={form.blocked_risk_flags}
                      onChange={(value) => updateForm("blocked_risk_flags", value)}
                    />
                  </div>
                    </div>
                  </details>

                  <div className="flex justify-end border-t border-slate-200 pt-4">
                    <button
                      type="button"
                      onClick={handleSave}
                      disabled={saving || detailLoading}
                      className="inline-flex h-10 items-center gap-2 rounded-md bg-blue-600 px-4 text-xs font-bold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {saving ? <LoaderIcon size={14} className="animate-spin" /> : <SaveIcon size={14} />}
                      保存配置
                    </button>
                  </div>
                </div>
              </section>

              <aside className="space-y-4">
                <section className="rounded-md border border-slate-200 bg-white p-4">
                  <div className="flex items-center gap-2 text-xs font-bold text-slate-800">
                    <BotIcon size={15} />
                    绑定 Agent
                  </div>
                  <div className="mt-3 space-y-2 text-xs text-slate-600">
                    <div className="flex justify-between gap-3">
                      <span>授权状态</span>
                      <span className="font-semibold">{bindStatusText(selectedItem.bind_status)}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span>Agent</span>
                      <span className="text-right font-semibold">{selectedItem.bound_agent_name || "未绑定"}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span>Agent 状态</span>
                      <span className="font-semibold">{agentStatusText(selectedItem.bound_agent_status)}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span>更新时间</span>
                      <span className="text-right">{formatDateTimeLocal(selectedItem.updated_at)}</span>
                    </div>
                  </div>
                </section>

                {!hasActiveAgent(selectedItem) ? (
                  <section className="rounded-md border border-amber-200 bg-amber-50 p-4 text-xs leading-6 text-amber-800">
                    <div className="flex items-start gap-2">
                      <AlertTriangleIcon size={15} className="mt-0.5 shrink-0" />
                      <div>
                        <div className="font-bold">当前企业号没有可用 Agent。</div>
                        <div>可以先保存配置，但后端实际自动回复会被绑定门禁阻断或不可用。</div>
                      </div>
                    </div>
                  </section>
                ) : (
                  <section className="rounded-md border border-emerald-200 bg-emerald-50 p-4 text-xs leading-6 text-emerald-800">
                    <div className="flex items-start gap-2">
                      <CheckCircle2Icon size={15} className="mt-0.5 shrink-0" />
                      <div>
                        <div className="font-bold">已绑定可用 Agent。</div>
                        <div>真实回复仍需通过后端全部门禁。</div>
                      </div>
                    </div>
                  </section>
                )}

                <section className="rounded-md border border-slate-200 bg-white p-4 text-xs leading-6 text-slate-600">
                  <div className="font-bold text-slate-800">安全边界</div>
                  <ul className="mt-2 list-disc space-y-1 pl-4">
                    <li>保存配置不会立即产生客户消息回复。</li>
                    <li>关闭真实自动回复不需要二次确认，便于快速止血。</li>
                    <li>是否发送由后端新私信事件和门禁决定。</li>
                    <li>前端只负责配置与展示，不提供运行触发入口。</li>
                  </ul>
                </section>
              </aside>
            </div>
          )}
        </main>
      </div>

      <SendEnableConfirmModal
        open={confirmOpen}
        confirmText={confirmText}
        onConfirmTextChange={setConfirmText}
        onCancel={() => {
          setConfirmOpen(false);
          setConfirmText("");
        }}
        onConfirm={() => void saveSettings(form)}
        saving={saving}
      />
    </section>
  );
}
