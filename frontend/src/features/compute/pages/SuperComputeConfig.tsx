import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  CpuIcon,
  Edit3Icon,
  GiftIcon,
  PackagePlusIcon,
  RefreshCwIcon,
  SaveIcon,
  SendIcon,
  XIcon,
} from "lucide-react";
import {
  createAdminComputePackage,
  fetchAdminComputeMarkupRatios,
  fetchAdminComputePackages,
  grantMerchantComputePackage,
  rechargeMerchantCompute,
  updateAdminComputePackage,
  updateAdminComputeMarkupRatio,
} from "../api";
import type { ComputePackageCreateRequest } from "../api";
import type {
  ComputeCapabilityKey,
  ComputeMarkupRatio,
  ComputePackage,
  ComputeSummary,
} from "../types";
import { formatDateTimeLocal } from "../../../lib/datetime";
import { userFacingError } from "../../../lib/userFacingError";

interface PackageFormState {
  id: number | null;
  name: string;
  price_yuan: string;
  token_amount: string;
  enabled: boolean;
}

const emptyPackageForm: PackageFormState = {
  id: null,
  name: "",
  price_yuan: "",
  token_amount: "",
  enabled: true,
};

// Phase 10 §0.2：能力顺序与中文标签（与后端 COMPUTE_CAPABILITY_KEYS 一致）
const CAPABILITY_ROWS: { key: ComputeCapabilityKey; label: string }[] = [
  { key: "douyin-cs", label: "抖音客服" },
  { key: "leads", label: "线索" },
  { key: "agents", label: "智能体" },
  { key: "wechat-assistant", label: "微信助手" },
  { key: "compute", label: "算力" },
  { key: "knowledge", label: "知识问答" },
  { key: "ai_edit", label: "AI剪辑" },
];

/**
 * Phase 10 §0.2：百分比字符串 → 基点（纯字符串拼接，禁浮点）。
 * 接受非负整数或最多两位小数："33"→3300，"33.5"→3350，"33.05"→3305。非法返回 null。
 */
function percentStringToBasisPoints(input: string): number | null {
  const trimmed = input.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return null;
  const dotIndex = trimmed.indexOf(".");
  const intPart = dotIndex === -1 ? trimmed : trimmed.slice(0, dotIndex);
  const fracPart = dotIndex === -1 ? "" : trimmed.slice(dotIndex + 1);
  const paddedFrac = (fracPart + "00").slice(0, 2);
  return Number.parseInt(intPart + paddedFrac, 10);
}

/**
 * Phase 10 §0.2：基点 → 百分比字符串（整数除法/取模，范围 INTEGER 内无浮点误差）。
 * 3300→"33"，3350→"33.50"，3305→"33.05"。
 */
function basisPointsToPercent(bp: number): string {
  const intPart = Math.floor(bp / 100);
  const frac = bp % 100;
  return frac === 0 ? String(intPart) : `${intPart}.${String(frac).padStart(2, "0")}`;
}

/** Phase 10 §0.2：单能力上浮比例的编辑态（失败不覆盖原值，保留用户输入）。 */
interface RatioEditState {
  percent: string;
  enabled: boolean;
  consumption_mode: "actual" | "custom";
  fixed_tokens: string;
  saving: boolean;
  error: string | null;
}

/** 功能 Token 消耗配置编辑弹窗态 */
interface RatioEditModalState {
  key: ComputeCapabilityKey;
  label: string;
  percent: string;
  enabled: boolean;
  consumption_mode: "actual" | "custom";
  fixed_tokens: string;
}

function resolveErrorMessage(err: unknown): string {
  return userFacingError(err, "数据加载失败，请稍后重试");
}

function toPositiveInteger(value: string): number | null {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed <= 0) return null;
  return parsed;
}

function buildPackagePayload(form: PackageFormState): ComputePackageCreateRequest | null {
  const name = form.name.trim();
  const price = toPositiveInteger(form.price_yuan);
  const tokens = toPositiveInteger(form.token_amount);
  if (!name || price === null || tokens === null) return null;
  return {
    name,
    price_yuan: price,
    token_amount: tokens,
    enabled: form.enabled,
  };
}

function ResultSummary({ summary }: { summary: ComputeSummary | null }) {
  if (!summary) return null;
  return (
    <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs text-emerald-800">
      <div className="flex items-center gap-2 font-semibold">
        <CheckCircle2Icon size={14} />
        操作已完成
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
        <span>商户：{summary.merchant_id}</span>
        <span>余额：{summary.balance_tokens} 算力点数</span>
        <span>今日消耗：{summary.today_consume}</span>
        <span>累计消耗：{summary.total_consume}</span>
      </div>
    </div>
  );
}

type ComputeConfigView = "ratios" | "packages" | "merchant-grant";

const CONFIG_VIEWS: Array<{ id: ComputeConfigView; label: string }> = [
  { id: "ratios", label: "计费比例" },
  { id: "packages", label: "套餐管理" },
  { id: "merchant-grant", label: "商户发放" },
];

function normalizeConfigView(value: string | null): ComputeConfigView {
  return CONFIG_VIEWS.some((item) => item.id === value)
    ? (value as ComputeConfigView)
    : "ratios";
}

export default function SuperComputeConfig() {
  const [packages, setPackages] = useState<ComputePackage[]>([]);
  const [loadingPackages, setLoadingPackages] = useState(false);
  const [packageError, setPackageError] = useState<string | null>(null);
  const [packageForm, setPackageForm] = useState<PackageFormState>(emptyPackageForm);
  const [savingPackage, setSavingPackage] = useState(false);
  const [packageFormError, setPackageFormError] = useState<string | null>(null);

  const [rechargeMerchantId, setRechargeMerchantId] = useState("");
  const [rechargeTokens, setRechargeTokens] = useState("");
  const [rechargeRemark, setRechargeRemark] = useState("");
  const [rechargeSubmitting, setRechargeSubmitting] = useState(false);
  const [rechargeError, setRechargeError] = useState<string | null>(null);
  const [rechargeResult, setRechargeResult] = useState<ComputeSummary | null>(null);

  const [grantMerchantId, setGrantMerchantId] = useState("");
  const [grantPackageId, setGrantPackageId] = useState("");
  const [grantSubmitting, setGrantSubmitting] = useState(false);
  const [grantError, setGrantError] = useState<string | null>(null);
  const [grantResult, setGrantResult] = useState<ComputeSummary | null>(null);

  // Phase 10 §0.2：六能力上浮比例（独立区，不嵌套套餐卡片）
  const [ratios, setRatios] = useState<ComputeMarkupRatio[]>([]);
  const [ratioLoading, setRatioLoading] = useState(false);
  const [ratioError, setRatioError] = useState<string | null>(null);
  const [ratioEdits, setRatioEdits] = useState<Record<string, RatioEditState>>({});
  const [ratioModal, setRatioModal] = useState<RatioEditModalState | null>(null);

  const [searchParams, setSearchParams] = useSearchParams();
  const activeView = normalizeConfigView(searchParams.get("view"));
  const selectView = (view: ComputeConfigView) => {
    setSearchParams({ view }, { replace: true });
  };

  const selectedGrantPackage = useMemo(
    () => packages.find((pkg) => String(pkg.id) === grantPackageId) || null,
    [packages, grantPackageId],
  );

  const enabledPackages = useMemo(() => packages.filter((pkg) => pkg.enabled), [packages]);

  const loadPackages = useCallback(async () => {
    setLoadingPackages(true);
    setPackageError(null);
    try {
      const response = await fetchAdminComputePackages();
      setPackages(response.data);
    } catch (err) {
      const message = resolveErrorMessage(err);
      setPackages([]);
      setPackageError(message);
      toast.error(`套餐加载失败：${message}`);
    } finally {
      setLoadingPackages(false);
    }
  }, []);

  const loadRatios = useCallback(async () => {
    setRatioLoading(true);
    setRatioError(null);
    try {
      const response = await fetchAdminComputeMarkupRatios();
      setRatios(response.data);
      const edits: Record<string, RatioEditState> = {};
      for (const r of response.data) {
        edits[r.capability_key] = {
          percent: basisPointsToPercent(r.markup_basis_points),
          enabled: r.enabled,
          consumption_mode: (r.consumption_mode === "custom" ? "custom" : "actual"),
          fixed_tokens: r.fixed_tokens_per_call ? String(r.fixed_tokens_per_call) : "",
          saving: false,
          error: null,
        };
      }
      setRatioEdits(edits);
    } catch (err) {
      const message = resolveErrorMessage(err);
      setRatios([]);
      setRatioError(message);
      toast.error(`上浮比例加载失败：${message}`);
    } finally {
      setRatioLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeView === "ratios") {
      void loadRatios();
    } else {
      void loadPackages();
    }
  }, [activeView, loadPackages, loadRatios]);

  const handleEditRatioPercent = (key: string, percent: string) => {
    setRatioEdits((prev) => ({
      ...prev,
      [key]: { ...prev[key], percent, error: null },
    }));
  };

  const handleEditRatioEnabled = (key: string, enabled: boolean) => {
    setRatioEdits((prev) => ({
      ...prev,
      [key]: { ...prev[key], enabled, error: null },
    }));
  };

  const handleSaveRatio = async (key: ComputeCapabilityKey) => {
    const edit = ratioEdits[key];
    if (!edit) return;
    const basisPoints = percentStringToBasisPoints(edit.percent);
    if (basisPoints === null) {
      setRatioEdits((prev) => ({
        ...prev,
        [key]: { ...prev[key], error: "请输入非负数字，最多两位小数（如 33 或 33.5）。" },
      }));
      return;
    }
    setRatioEdits((prev) => ({
      ...prev,
      [key]: { ...prev[key], saving: true, error: null },
    }));
    try {
      const response = await updateAdminComputeMarkupRatio(key, {
        markup_basis_points: basisPoints,
        enabled: edit.enabled,
        consumption_mode: edit.consumption_mode,
        fixed_tokens_per_call:
          edit.consumption_mode === "custom" && edit.fixed_tokens.trim()
            ? Number(edit.fixed_tokens)
            : null,
      });
      setRatios((prev) =>
        prev.map((r) => (r.capability_key === key ? response.data : r)),
      );
      // 成功后用后端回显值重置编辑态（失败不覆盖原值，保留用户输入）
      setRatioEdits((prev) => ({
        ...prev,
        [key]: {
          percent: basisPointsToPercent(response.data.markup_basis_points),
          enabled: response.data.enabled,
          consumption_mode: response.data.consumption_mode === "custom" ? "custom" : "actual",
          fixed_tokens: response.data.fixed_tokens_per_call ? String(response.data.fixed_tokens_per_call) : "",
          saving: false,
          error: null,
        },
      }));
      const label = CAPABILITY_ROWS.find((r) => r.key === key)?.label || key;
      toast.success(`${label}上浮比例已保存`);
    } catch (err) {
      const message = resolveErrorMessage(err);
      setRatioEdits((prev) => ({
        ...prev,
        [key]: { ...prev[key], saving: false, error: message },
      }));
      toast.error(message);
    }
  };

  const openRatioModal = (key: ComputeCapabilityKey) => {
    const edit = ratioEdits[key];
    const label = CAPABILITY_ROWS.find((r) => r.key === key)?.label || key;
    if (!edit) return;
    setRatioModal({
      key,
      label,
      percent: edit.percent,
      enabled: edit.enabled,
      consumption_mode: edit.consumption_mode,
      fixed_tokens: edit.fixed_tokens,
    });
  };

  const saveRatioModal = async () => {
    if (!ratioModal) return;
    const { key } = ratioModal;
    const fixedTokens = ratioModal.consumption_mode === "custom" ? ratioModal.fixed_tokens.trim() : "";
    if (ratioModal.consumption_mode === "custom" && (!fixedTokens || !/^\d+$/.test(fixedTokens) || Number(fixedTokens) <= 0)) {
      setRatioEdits((prev) => ({ ...prev, [key]: { ...prev[key], error: "自定义消耗需填写正整数单次 Token 数" } }));
      return;
    }
    setRatioEdits((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        percent: ratioModal.percent,
        enabled: ratioModal.enabled,
        consumption_mode: ratioModal.consumption_mode,
        fixed_tokens: ratioModal.fixed_tokens,
        error: null,
      },
    }));
    setRatioModal(null);
    await handleSaveRatio(key);
  };

  const handleEditPackage = (pkg: ComputePackage) => {
    setPackageForm({
      id: pkg.id,
      name: pkg.name,
      price_yuan: String(pkg.price_yuan),
      token_amount: String(pkg.token_amount),
      enabled: pkg.enabled,
    });
    setPackageFormError(null);
  };

  const resetPackageForm = () => {
    setPackageForm(emptyPackageForm);
    setPackageFormError(null);
  };

  const handleSavePackage = async () => {
    const payload = buildPackagePayload(packageForm);
    if (!payload) {
      setPackageFormError("请填写套餐名称，并确保价格和算力点数数量均为大于 0 的整数。");
      return;
    }
    setSavingPackage(true);
    setPackageFormError(null);
    try {
      if (packageForm.id) {
        await updateAdminComputePackage(packageForm.id, payload);
        toast.success("套餐已更新");
      } else {
        await createAdminComputePackage(payload);
        toast.success("套餐已创建");
      }
      resetPackageForm();
      await loadPackages();
    } catch (err) {
      const message = resolveErrorMessage(err);
      setPackageFormError(message);
      toast.error(message);
    } finally {
      setSavingPackage(false);
    }
  };

  const handleTogglePackage = async (pkg: ComputePackage) => {
    try {
      await updateAdminComputePackage(pkg.id, { enabled: !pkg.enabled });
      toast.success(pkg.enabled ? "套餐已禁用" : "套餐已启用");
      await loadPackages();
    } catch (err) {
      toast.error(resolveErrorMessage(err));
    }
  };

  const handleRecharge = async () => {
    const merchantId = rechargeMerchantId.trim();
    const tokens = toPositiveInteger(rechargeTokens);
    if (!merchantId) {
      setRechargeError("请输入商户登录账号。");
      return;
    }
    if (tokens === null) {
      setRechargeError("算力点数数量必须为大于 0 的整数。");
      return;
    }
    setRechargeSubmitting(true);
    setRechargeError(null);
    setRechargeResult(null);
    try {
      const response = await rechargeMerchantCompute(merchantId, {
        tokens,
        remark: rechargeRemark.trim() || undefined,
      });
      setRechargeResult(response.data);
      toast.success("后台充值已完成");
    } catch (err) {
      const message = resolveErrorMessage(err);
      setRechargeError(message);
      toast.error(message);
    } finally {
      setRechargeSubmitting(false);
    }
  };

  const handleGrantPackage = async () => {
    const merchantId = grantMerchantId.trim();
    const packageId = Number(grantPackageId);
    if (!merchantId) {
      setGrantError("请输入商户登录账号。");
      return;
    }
    if (!packageId || !packages.some((pkg) => pkg.id === packageId)) {
      setGrantError("请选择有效套餐。");
      return;
    }
    setGrantSubmitting(true);
    setGrantError(null);
    setGrantResult(null);
    try {
      const response = await grantMerchantComputePackage(merchantId, { package_id: packageId });
      setGrantResult(response.data);
      toast.success("套餐已发放");
    } catch (err) {
      const message = resolveErrorMessage(err);
      setGrantError(message);
      toast.error(message);
    } finally {
      setGrantSubmitting(false);
    }
  };

  const handleRefresh = () => {
    if (activeView === "ratios") {
      void loadRatios();
    } else {
      void loadPackages();
    }
  };
  const refreshLoading = activeView === "ratios" ? ratioLoading : loadingPackages;

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <CpuIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">算力配置</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">平台算力套餐、商户后台充值和套餐发放</p>
            <nav aria-label="算力配置视图" className="mt-3 inline-flex rounded-lg border border-[#e4e8f0] bg-[#f8fafc] p-0.5 text-xs font-semibold">
              {CONFIG_VIEWS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={activeView === item.id}
                  onClick={() => selectView(item.id)}
                  className={`rounded-md px-4 py-1.5 transition ${
                    activeView === item.id
                      ? "bg-white text-[#2563eb] shadow-sm"
                      : "text-[#8b95a6] hover:text-[#475467]"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </nav>
          </div>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshLoading}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#dbe3ef] bg-white px-4 text-xs font-semibold text-[#475467] disabled:opacity-60"
        >
          <RefreshCwIcon size={14} className={refreshLoading ? "animate-spin" : ""} />
          刷新
        </button>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-5">
        {activeView === "ratios" ? (
          <>
        {/* Phase 10 §0.2：六能力上浮比例（独立区，不嵌套套餐卡片） */}
        <section className="rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex items-center justify-between border-b border-[#e4e8f0] px-4 py-3">
            <div>
              <h2 className="text-sm font-bold text-[#1a1f2e]">能力上浮比例</h2>
              <p className="mt-1 text-[11px] text-[#8b95a6]">
                设置各项 AI 能力的计费加成比例
              </p>
            </div>
            <button
              onClick={() => void loadRatios()}
              disabled={ratioLoading}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#dbe3ef] bg-white px-3 text-[11px] font-semibold text-[#475467] disabled:opacity-60"
            >
              <RefreshCwIcon size={13} className={ratioLoading ? "animate-spin" : ""} />
              刷新
            </button>
          </div>

          {ratioError ? (
            <div className="flex items-center gap-2 px-4 py-8 text-xs text-red-600">
              <AlertCircleIcon size={14} />
              <span>上浮比例加载失败：{ratioError}</span>
              <button onClick={() => void loadRatios()} className="ml-2 underline">
                重试
              </button>
            </div>
          ) : ratioLoading && ratios.length === 0 ? (
            <div className="space-y-2 px-4 py-4">
              {[0, 1, 2, 3, 4, 5, 6].map((i) => (
                <div key={i} className="h-12 animate-pulse rounded-xl bg-[#f1f5f9]" />
              ))}
            </div>
          ) : ratios.length === 0 ? (
            <div className="grid place-items-center px-4 py-10 text-center">
              <p className="text-xs text-[#8b95a6]">
                算力比例配置异常，请联系管理员处理。
              </p>
            </div>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="bg-[#f8fafc] text-[11px] font-semibold text-[#8b95a6]">
                <tr>
                  <th className="px-4 py-2.5">功能</th>
                  <th className="px-4 py-2.5">Token 消耗</th>
                  <th className="px-4 py-2.5">上浮比例</th>
                  <th className="px-4 py-2.5">状态</th>
                  <th className="px-4 py-2.5 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {CAPABILITY_ROWS.map((row) => {
                  const edit = ratioEdits[row.key];
                  if (!edit) return null;
                  const tokenConsumption =
                    edit.consumption_mode === "custom" && edit.fixed_tokens
                      ? `${Number(edit.fixed_tokens).toLocaleString()}/次 + 上浮`
                      : "实际 + 上浮";
                  return (
                    <tr key={row.key} className="border-t border-[#f1f5f9]">
                      <td className="px-4 py-3 font-semibold text-[#1a1f2e]">{row.label}</td>
                      <td className="px-4 py-3 text-[#475467]">{tokenConsumption}</td>
                      <td className="px-4 py-3">
                        <span className="rounded-md bg-[#eff6ff] px-2 py-0.5 text-[11px] font-semibold text-[#2563eb]">
                          {edit.percent || "0"}%
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${edit.enabled ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                          {edit.enabled ? "启用" : "停用"}
                        </span>
                        {edit.error ? (
                          <div className="mt-1 flex items-center gap-1 text-[10px] text-red-500">
                            <AlertCircleIcon size={11} />
                            {edit.error}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => openRatioModal(row.key)}
                          disabled={edit.saving}
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#dbe3ef] bg-white px-3 text-[11px] font-semibold text-[#475467] hover:bg-[#f8fafc] disabled:opacity-60"
                        >
                          {edit.saving ? <RefreshCwIcon size={12} className="animate-spin" /> : <Edit3Icon size={12} />}
                          {edit.saving ? "保存中" : "编辑"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <div className="border-t border-[#e4e8f0] px-4 py-2.5 text-[11px] text-[#8b95a6]">
            实际消耗=按真实用量计费+上浮；自定义消耗=固定单次定额+上浮（与真实用量无关）。
          </div>
        </section>

        {ratioModal ? (
          <div className="fixed inset-0 z-20 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm" role="dialog" aria-modal="true">
            <div className="w-full max-w-[480px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
              <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
                <h2 className="text-base font-bold text-[#1a1f2e]">编辑 · {ratioModal.label}</h2>
                <button type="button" onClick={() => setRatioModal(null)} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
                  <XIcon size={16} />
                </button>
              </div>
              <div className="space-y-4 px-5 py-5">
                <div>
                  <div className="mb-2 text-xs font-semibold text-[#475467]">Token 消耗规则</div>
                  <div className="grid grid-cols-2 gap-2 rounded-xl bg-[#eef2f7] p-1">
                    {(["actual", "custom"] as const).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => setRatioModal((m) => (m ? { ...m, consumption_mode: mode } : m))}
                        className={`h-8 rounded-lg text-xs font-semibold transition-colors ${
                          ratioModal.consumption_mode === mode
                            ? "bg-white text-[#1a1f2e] shadow-[0_1px_2px_rgba(15,23,42,0.08)]"
                            : "text-[#8b95a6] hover:text-[#1a1f2e]"
                        }`}
                      >
                        {mode === "actual" ? "实际消耗" : "自定义消耗"}
                      </button>
                    ))}
                  </div>
                  {ratioModal.consumption_mode === "custom" ? (
                    <div className="mt-2">
                      <label className="text-xs font-semibold text-[#475467]">单次 Token 消耗量</label>
                      <input
                        type="number"
                        min={1}
                        value={ratioModal.fixed_tokens}
                        onChange={(e) => setRatioModal((m) => (m ? { ...m, fixed_tokens: e.target.value } : m))}
                        placeholder="如 1000"
                        className="mt-1 h-9 w-full rounded-lg border border-[#dbe3ef] px-3 text-sm outline-none focus:border-[#2563eb]"
                      />
                    </div>
                  ) : (
                    <p className="mt-2 text-[11px] text-[#8b95a6]">按 LLM 真实用量计费，再叠加下方上浮比例。</p>
                  )}
                </div>
                <div>
                  <label className="text-xs font-semibold text-[#475467]">上浮比例（%）</label>
                  <input
                    value={ratioModal.percent}
                    onChange={(e) => setRatioModal((m) => (m ? { ...m, percent: e.target.value } : m))}
                    placeholder="如 33"
                    className="mt-1 h-9 w-full rounded-lg border border-[#dbe3ef] px-3 text-sm outline-none focus:border-[#2563eb]"
                  />
                </div>
                <label className="flex items-center gap-2 text-xs font-semibold text-[#475467]">
                  <input
                    type="checkbox"
                    checked={ratioModal.enabled}
                    onChange={(e) => setRatioModal((m) => (m ? { ...m, enabled: e.target.checked } : m))}
                    className="h-4 w-4 rounded border-[#cbd5e1]"
                  />
                  启用该能力上浮
                </label>
              </div>
              <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
                <button type="button" onClick={() => setRatioModal(null)} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
                  取消
                </button>
                <button type="button" onClick={() => void saveRatioModal()} className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
                  <SaveIcon size={14} />
                  保存
                </button>
              </div>
            </div>
          </div>
        ) : null}
          </>
        ) : null}

        {activeView === "packages" ? (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)]">
          <section className="rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="flex items-center justify-between border-b border-[#e4e8f0] px-4 py-3">
              <div>
                <h2 className="text-sm font-bold text-[#1a1f2e]">套餐列表</h2>
                <p className="mt-1 text-[11px] text-[#8b95a6]">来源：后台套餐配置</p>
              </div>
              <span className="rounded-full bg-[#eff6ff] px-2.5 py-1 text-[11px] font-semibold text-[#2563eb]">
                {packages.length} 个套餐
              </span>
            </div>

            {packageError ? (
              <div className="flex items-center gap-2 px-4 py-8 text-xs text-red-600">
                <AlertCircleIcon size={14} />
                <span>套餐加载失败：{packageError}</span>
                <button onClick={() => void loadPackages()} className="ml-2 underline">
                  重试
                </button>
              </div>
            ) : loadingPackages && packages.length === 0 ? (
              <div className="space-y-2 px-4 py-4">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="h-16 animate-pulse rounded-xl bg-[#f1f5f9]" />
                ))}
              </div>
            ) : packages.length === 0 ? (
              <div className="grid place-items-center px-4 py-12 text-center">
                <PackagePlusIcon size={28} className="text-[#cbd5e1]" />
                <p className="mt-2 text-xs text-[#8b95a6]">暂无套餐，可在右侧创建。</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-xs">
                  <thead>
                    <tr className="border-b border-[#e4e8f0] text-[#8b95a6]">
                      <th className="px-4 py-2.5 font-semibold">套餐名称</th>
                      <th className="px-4 py-2.5 font-semibold">价格</th>
                      <th className="px-4 py-2.5 font-semibold">算力点数数量</th>
                      <th className="px-4 py-2.5 font-semibold">状态</th>
                      <th className="px-4 py-2.5 font-semibold">更新时间</th>
                      <th className="px-4 py-2.5 font-semibold">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {packages.map((pkg) => (
                      <tr key={pkg.id} className="border-b border-[#f1f5f9] last:border-0">
                        <td className="px-4 py-3 font-semibold text-[#1a1f2e]">{pkg.name}</td>
                        <td className="px-4 py-3 text-[#475467]">￥{pkg.price_yuan}</td>
                        <td className="px-4 py-3 text-[#475467]">{pkg.token_amount}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`rounded-full px-2 py-1 text-[11px] font-semibold ${
                              pkg.enabled
                                ? "bg-emerald-50 text-emerald-700"
                                : "bg-slate-100 text-slate-500"
                            }`}
                          >
                            {pkg.enabled ? "启用" : "禁用"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-[#8b95a6]">
                          {formatDateTimeLocal(pkg.updated_at || pkg.created_at)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => handleEditPackage(pkg)}
                              className="inline-flex h-8 items-center gap-1 rounded-lg border border-[#dbe3ef] bg-white px-2.5 text-[11px] font-semibold text-[#475467]"
                            >
                              <Edit3Icon size={13} />
                              编辑
                            </button>
                            <button
                              onClick={() => void handleTogglePackage(pkg)}
                              className={`h-8 rounded-lg px-2.5 text-[11px] font-semibold ${
                                pkg.enabled
                                  ? "bg-slate-100 text-slate-600"
                                  : "bg-[#eff6ff] text-[#2563eb]"
                              }`}
                            >
                              {pkg.enabled ? "禁用" : "启用"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <aside className="space-y-5">
            <section className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <div className="flex items-center gap-2">
                <PackagePlusIcon size={16} className="text-[#2563eb]" />
                <h2 className="text-sm font-bold text-[#1a1f2e]">
                  {packageForm.id ? "编辑套餐" : "新增套餐"}
                </h2>
              </div>
              <div className="mt-4 space-y-3">
                <label className="block text-xs font-semibold text-[#475467]">
                  套餐名称
                  <input
                    value={packageForm.name}
                    onChange={(event) => setPackageForm((current) => ({ ...current, name: event.target.value }))}
                    className="mt-1 h-10 w-full rounded-xl border border-[#dbe3ef] px-3 text-sm outline-none focus:border-[#2563eb]"
                    placeholder="例如：基础版"
                  />
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block text-xs font-semibold text-[#475467]">
                    价格（元）
                    <input
                      type="number"
                      min={1}
                      value={packageForm.price_yuan}
                      onChange={(event) => setPackageForm((current) => ({ ...current, price_yuan: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-xl border border-[#dbe3ef] px-3 text-sm outline-none focus:border-[#2563eb]"
                    />
                  </label>
                  <label className="block text-xs font-semibold text-[#475467]">
                    算力点数数量
                    <input
                      type="number"
                      min={1}
                      value={packageForm.token_amount}
                      onChange={(event) => setPackageForm((current) => ({ ...current, token_amount: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-xl border border-[#dbe3ef] px-3 text-sm outline-none focus:border-[#2563eb]"
                    />
                  </label>
                </div>
                <label className="flex items-center gap-2 text-xs font-semibold text-[#475467]">
                  <input
                    type="checkbox"
                    checked={packageForm.enabled}
                    onChange={(event) => setPackageForm((current) => ({ ...current, enabled: event.target.checked }))}
                    className="h-4 w-4 rounded border-[#cbd5e1]"
                  />
                  启用套餐
                </label>
                {packageFormError ? (
                  <p className="flex items-center gap-1.5 text-xs text-red-500">
                    <AlertCircleIcon size={13} />
                    {packageFormError}
                  </p>
                ) : null}
                <div className="flex justify-end gap-2 pt-1">
                  {packageForm.id ? (
                    <button
                      onClick={resetPackageForm}
                      className="h-9 rounded-xl border border-[#dbe3ef] bg-white px-4 text-xs font-semibold text-[#475467]"
                    >
                      取消编辑
                    </button>
                  ) : null}
                  <button
                    onClick={() => void handleSavePackage()}
                    disabled={savingPackage}
                    className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white disabled:opacity-60"
                  >
                    {savingPackage ? <RefreshCwIcon size={14} className="animate-spin" /> : <SaveIcon size={14} />}
                    {savingPackage ? "保存中" : "保存套餐"}
                  </button>
                </div>
              </div>
            </section>
          </aside>
        </div>
        ) : null}

        {activeView === "merchant-grant" ? (
        <>
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-800">
          <div className="font-semibold">后台充值/发放为管理操作，不代表真实支付。</div>
          <div>真实支付暂未接入；请确认商户登录账号后再操作，页面不会调用微信支付或支付宝真实接口。</div>
        </div>
        <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-2">
          <section className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="flex items-center gap-2">
              <SendIcon size={16} className="text-[#2563eb]" />
              <div>
                <h2 className="text-sm font-bold text-[#1a1f2e]">商户充值算力点数</h2>
                <p className="mt-1 text-[11px] text-[#8b95a6]">充值接口：后台管理服务</p>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
              <label className="block text-xs font-semibold text-[#475467]">
                商户登录账号
                <input
                  value={rechargeMerchantId}
                  onChange={(event) => setRechargeMerchantId(event.target.value)}
                  className="mt-1 h-10 w-full rounded-xl border border-[#dbe3ef] px-3 text-sm outline-none focus:border-[#2563eb]"
                  placeholder="例如：merchant-a"
                />
              </label>
              <label className="block text-xs font-semibold text-[#475467]">
                算力点数 数量
                <input
                  type="number"
                  min={1}
                  value={rechargeTokens}
                  onChange={(event) => setRechargeTokens(event.target.value)}
                  className="mt-1 h-10 w-full rounded-xl border border-[#dbe3ef] px-3 text-sm outline-none focus:border-[#2563eb]"
                />
              </label>
            </div>
            <label className="mt-3 block text-xs font-semibold text-[#475467]">
              备注
              <textarea
                value={rechargeRemark}
                onChange={(event) => setRechargeRemark(event.target.value)}
                className="mt-1 min-h-[72px] w-full resize-none rounded-xl border border-[#dbe3ef] px-3 py-2 text-sm outline-none focus:border-[#2563eb]"
                placeholder="后台充值原因或审批备注"
              />
            </label>
            {rechargeError ? (
              <p className="mt-3 flex items-center gap-1.5 text-xs text-red-500">
                <AlertCircleIcon size={13} />
                {rechargeError}
              </p>
            ) : null}
            <ResultSummary summary={rechargeResult} />
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => void handleRecharge()}
                disabled={rechargeSubmitting}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white disabled:opacity-60"
              >
                {rechargeSubmitting ? <RefreshCwIcon size={14} className="animate-spin" /> : <SendIcon size={14} />}
                {rechargeSubmitting ? "提交中" : "确认后台充值"}
              </button>
            </div>
          </section>

          <section className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="flex items-center gap-2">
              <GiftIcon size={16} className="text-[#2563eb]" />
              <div>
                <h2 className="text-sm font-bold text-[#1a1f2e]">发放套餐</h2>
                <p className="mt-1 text-[11px] text-[#8b95a6]">发放接口：后台管理服务</p>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
              <label className="block text-xs font-semibold text-[#475467]">
                商户登录账号
                <input
                  value={grantMerchantId}
                  onChange={(event) => setGrantMerchantId(event.target.value)}
                  className="mt-1 h-10 w-full rounded-xl border border-[#dbe3ef] px-3 text-sm outline-none focus:border-[#2563eb]"
                  placeholder="例如：merchant-a"
                />
              </label>
              <label className="block text-xs font-semibold text-[#475467]">
                套餐
                <select
                  value={grantPackageId}
                  onChange={(event) => setGrantPackageId(event.target.value)}
                  className="mt-1 h-10 w-full rounded-xl border border-[#dbe3ef] bg-white px-3 text-sm outline-none focus:border-[#2563eb]"
                >
                  <option value="">请选择套餐</option>
                  {enabledPackages.map((pkg) => (
                    <option key={pkg.id} value={pkg.id}>
                      {pkg.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="mt-3 rounded-xl bg-[#f8fafc] px-4 py-3 text-xs text-[#64748b]">
              {selectedGrantPackage ? (
                <div className="grid grid-cols-2 gap-2">
                  <span>套餐：{selectedGrantPackage.name}</span>
                  <span>算力点数：{selectedGrantPackage.token_amount}</span>
                  <span>价格：￥{selectedGrantPackage.price_yuan}</span>
                  <span>状态：{selectedGrantPackage.enabled ? "启用" : "禁用"}</span>
                </div>
              ) : (
                "选择套餐后会展示发放算力点数数量。禁用套餐不会出现在可发放列表中。"
              )}
            </div>
            {grantError ? (
              <p className="mt-3 flex items-center gap-1.5 text-xs text-red-500">
                <AlertCircleIcon size={13} />
                {grantError}
              </p>
            ) : null}
            <ResultSummary summary={grantResult} />
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => void handleGrantPackage()}
                disabled={grantSubmitting}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white disabled:opacity-60"
              >
                {grantSubmitting ? <RefreshCwIcon size={14} className="animate-spin" /> : <GiftIcon size={14} />}
                {grantSubmitting ? "提交中" : "确认发放套餐"}
              </button>
            </div>
          </section>
        </div>
        </>
        ) : null}
      </main>
    </section>
  );
}
