import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  AlertCircleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CoinsIcon,
  PlusIcon,
  QrCodeIcon,
  RefreshCwIcon,
  TrendingDownIcon,
  WalletIcon,
  XIcon,
} from "lucide-react";
import {
  createComputeRechargeOrder,
  fetchComputePackages,
  fetchComputeSummary,
  fetchComputeTransactions,
} from "../api/compute";
import type {
  ComputePackage,
  ComputeRechargeOrder,
  ComputeSummary,
  ComputeTransaction,
} from "../api/types";
import { formatDateTimeLocal } from "../lib/datetime";

// 流水类型中文标签（对齐后端 transaction_type 枚举）
const TRANSACTION_TYPE_LABELS: Record<string, string> = {
  recharge: "充值",
  grant_package: "发放套餐",
  consume: "消耗",
};

const PAGE_SIZE = 10;

function formatPayMethod(value: string): string {
  if (value === "alipay") return "支付宝";
  if (value === "wechat") return "微信支付";
  return value || "-";
}

/** Token 变动展示：正数加 +，负数保留 -。 */
function formatTokenChange(delta: number): string {
  return delta > 0 ? `+${delta}` : String(delta);
}

/** 从 axios 错误里提取后端 message，便于在 UI/Toast 展示可读原因。 */
function resolveErrorMessage(err: unknown): string {
  if (err && typeof err === "object") {
    const anyErr = err as {
      response?: { data?: { message?: string; detail?: string | { message?: string } } };
      message?: string;
    };
    const detail = anyErr.response?.data?.detail;
    if (detail && typeof detail === "object" && detail.message) return detail.message;
    return anyErr.response?.data?.message || anyErr.message || "请求失败";
  }
  return err instanceof Error ? err.message : "请求失败";
}

function StatCard({
  label,
  value,
  icon,
  accent,
  loading,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  accent: string;
  loading: boolean;
}) {
  return (
    <div className="rounded-xl border border-[#e4e8f0] bg-white px-4 py-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex items-center gap-2 text-xs font-semibold text-[#8b95a6]">
        <span className={`grid h-7 w-7 place-items-center rounded-lg ${accent}`}>{icon}</span>
        {label}
      </div>
      <div className="mt-3 text-2xl font-bold text-[#1a1f2e]">
        {loading ? <span className="text-[#cbd5e1]">--</span> : value}
      </div>
      <div className="mt-1 text-[11px] text-[#8b95a6]">Token</div>
    </div>
  );
}

interface RechargeModalProps {
  packages: ComputePackage[];
  loadingPackages: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function RechargeModal({ packages, loadingPackages, onClose, onSuccess }: RechargeModalProps) {
  const [selectedPackageId, setSelectedPackageId] = useState<number | null>(null);
  const [customTokens, setCustomTokens] = useState("");
  const [payMethod, setPayMethod] = useState<"wechat" | "alipay">("wechat");
  const [submitting, setSubmitting] = useState(false);
  const [order, setOrder] = useState<ComputeRechargeOrder | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);

  const handleSelectPackage = (id: number) => {
    setSelectedPackageId(id);
    setCustomTokens("");
    setErrorText(null);
  };

  const handleCustomInput = (value: string) => {
    setCustomTokens(value);
    setSelectedPackageId(null);
    setErrorText(null);
  };

  const handleSubmit = async () => {
    setErrorText(null);
    const customValue = customTokens.trim();
    if (selectedPackageId === null && (!customValue || Number(customValue) <= 0)) {
      setErrorText("请选择套餐或输入自定义 Token 数量");
      return;
    }
    setSubmitting(true);
    try {
      const response = await createComputeRechargeOrder({
        package_id: selectedPackageId ?? undefined,
        custom_tokens: customValue ? Number(customValue) : undefined,
        pay_method: payMethod,
      });
      setOrder(response.data);
      onSuccess();
      toast.success("已创建充值订单（mock，未真实支付）");
    } catch (err) {
      const message = resolveErrorMessage(err);
      setErrorText(message);
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[520px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">算力充值</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">选择套餐或自定义金额（一期 mock，不真实扣款）</p>
          </div>
          <button
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]"
            aria-label="关闭充值弹窗"
          >
            <XIcon size={16} />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto px-5 py-5">
          {order ? (
            <div className="grid place-items-center rounded-2xl border border-[#e4e8f0] bg-[#f8fafc] px-5 py-7 text-center">
              <div className="grid h-20 w-20 place-items-center rounded-2xl border border-[#dbe3ef] bg-white text-[#2563eb]">
                <QrCodeIcon size={44} />
              </div>
              <p className="mt-4 text-sm font-bold text-[#1a1f2e]">充值订单已创建（mock）</p>
              <p className="mt-1 text-xs text-[#8b95a6]">充值订单为 mock_pending，真实支付暂未接入。</p>
              <p className="mt-1 text-xs text-[#8b95a6]">不会调用微信支付或支付宝真实支付，余额以后台入账或测试接口为准。</p>
              <div className="mt-4 w-full space-y-1.5 rounded-xl bg-white px-3 py-3 text-left text-xs ring-1 ring-[#e4e8f0]">
                <div className="flex justify-between">
                  <span className="text-[#8b95a6]">订单号</span>
                  <span className="font-semibold text-[#1a1f2e]">{order.order_no}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#8b95a6]">充值 Token</span>
                  <span className="font-semibold text-[#1a1f2e]">{order.tokens}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#8b95a6]">支付方式</span>
                  <span className="font-semibold text-[#1a1f2e]">{formatPayMethod(order.pay_method)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#8b95a6]">金额</span>
                  <span className="font-semibold text-[#1a1f2e]">
                    {order.price_yuan === null || order.price_yuan === undefined ? "自定义 Token" : `¥${order.price_yuan}`}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#8b95a6]">状态</span>
                  <span className="font-semibold text-amber-600">{order.status}</span>
                </div>
              </div>
              <button onClick={onClose} className="mt-4 h-9 rounded-xl bg-[#2563eb] px-5 text-xs font-semibold text-white">
                关闭
              </button>
            </div>
          ) : (
            <>
              <h3 className="text-xs font-bold text-[#1a1f2e]">套餐充值</h3>
              {loadingPackages ? (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="h-20 animate-pulse rounded-xl bg-[#f1f5f9]" />
                  ))}
                </div>
              ) : packages.length === 0 ? (
                <div className="mt-3 rounded-xl border border-dashed border-[#cbd5e1] bg-[#f8fafc] px-4 py-6 text-center text-xs text-[#8b95a6]">
                  暂无可用套餐，可使用下方自定义金额
                </div>
              ) : (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {packages.map((pkg) => {
                    const active = selectedPackageId === pkg.id;
                    return (
                      <button
                        key={pkg.id}
                        onClick={() => handleSelectPackage(pkg.id)}
                        className={`rounded-xl border px-3 py-3 text-left transition-smooth ${
                          active
                            ? "border-[#2563eb] bg-[#eff6ff] ring-2 ring-[#2563eb]/15"
                            : "border-[#e4e8f0] bg-white hover:border-[#cbd5e1]"
                        }`}
                      >
                        <div className="text-sm font-bold text-[#1a1f2e]">{pkg.name}</div>
                        <div className="mt-1 text-[11px] text-[#8b95a6]">¥{pkg.price_yuan}</div>
                        <div className="mt-0.5 text-xs font-semibold text-[#2563eb]">{pkg.token_amount} Token</div>
                      </button>
                    );
                  })}
                </div>
              )}

              <h3 className="mt-5 text-xs font-bold text-[#1a1f2e]">自定义 Token 数量</h3>
              <div className="mt-3 flex h-10 items-center rounded-xl border border-[#e4e8f0] bg-white px-3 focus-within:border-[#2563eb]">
                <input
                  type="number"
                  min={1}
                  value={customTokens}
                  onChange={(event) => handleCustomInput(event.target.value)}
                  placeholder="输入 Token 数量"
                  className="h-full w-full bg-transparent text-sm outline-none placeholder:text-[#9ca3af]"
                />
                <span className="ml-2 text-xs text-[#8b95a6]">Token</span>
              </div>

              <h3 className="mt-5 text-xs font-bold text-[#1a1f2e]">支付方式</h3>
              <div className="mt-3 grid grid-cols-2 gap-2">
                {([
                  { key: "wechat", label: "微信支付" },
                  { key: "alipay", label: "支付宝" },
                ] as const).map((item) => {
                  const active = payMethod === item.key;
                  return (
                    <button
                      key={item.key}
                      onClick={() => setPayMethod(item.key)}
                      className={`h-10 rounded-xl border text-xs font-semibold transition-smooth ${
                        active
                          ? "border-[#2563eb] bg-[#eff6ff] text-[#2563eb]"
                          : "border-[#e4e8f0] bg-white text-[#475467] hover:border-[#cbd5e1]"
                      }`}
                    >
                      {item.label}
                    </button>
                  );
                })}
              </div>

              {errorText ? (
                <p className="mt-3 flex items-center gap-1.5 text-xs text-red-500">
                  <AlertCircleIcon size={13} />
                  {errorText}
                </p>
              ) : null}
            </>
          )}
        </div>

        {!order ? (
          <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
            <button
              onClick={onClose}
              className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]"
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white disabled:opacity-60"
            >
              {submitting ? <RefreshCwIcon size={14} className="animate-spin" /> : <PlusIcon size={14} />}
              {submitting ? "提交中" : "创建订单"}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function ComputeCenter() {
  const [summary, setSummary] = useState<ComputeSummary | null>(null);
  const [transactions, setTransactions] = useState<ComputeTransaction[]>([]);
  const [packages, setPackages] = useState<ComputePackage[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [loadingTransactions, setLoadingTransactions] = useState(false);
  const [loadingPackages, setLoadingPackages] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [transactionError, setTransactionError] = useState<string | null>(null);
  const [packageError, setPackageError] = useState<string | null>(null);
  const [showRecharge, setShowRecharge] = useState(false);

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true);
    setSummaryError(null);
    try {
      const response = await fetchComputeSummary();
      setSummary(response.data);
    } catch (err) {
      setSummary(null);
      setSummaryError(resolveErrorMessage(err));
    } finally {
      setLoadingSummary(false);
    }
  }, []);

  const loadTransactions = useCallback(async (targetPage: number) => {
    setLoadingTransactions(true);
    setTransactionError(null);
    try {
      const response = await fetchComputeTransactions({
        page: targetPage,
        page_size: PAGE_SIZE,
      });
      setTransactions(response.data.items);
      setTotal(response.data.total);
      setPage(response.data.page);
    } catch (err) {
      setTransactions([]);
      setTotal(0);
      setTransactionError(resolveErrorMessage(err));
    } finally {
      setLoadingTransactions(false);
    }
  }, []);

  const loadPackages = useCallback(async () => {
    setLoadingPackages(true);
    setPackageError(null);
    try {
      const response = await fetchComputePackages();
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

  useEffect(() => {
    void loadSummary();
    void loadPackages();
    void loadTransactions(1);
  }, [loadSummary, loadPackages, loadTransactions]);

  const handleRechargeSuccess = useCallback(() => {
    // mock 订单不入账，余额可能不变属正常；刷新以保持流水与最新余额一致
    void loadSummary();
    void loadTransactions(page);
  }, [loadSummary, loadTransactions, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <CoinsIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">小高算力</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">Token 余额、消耗和充值记录</p>
          </div>
        </div>
        <button
          onClick={() => setShowRecharge(true)}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
        >
          <PlusIcon size={14} />
          立即充值
        </button>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-5">
        {/* 统计卡片：余额 / 今日 / 昨日 / 累计（一期不含累计充值） */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard
            label="算力余额"
            value={summary ? String(summary.balance_tokens) : "0"}
            icon={<WalletIcon size={15} />}
            accent="bg-[#eff6ff] text-[#2563eb]"
            loading={loadingSummary}
          />
          <StatCard
            label="今日消耗"
            value={summary ? String(summary.today_consume) : "0"}
            icon={<TrendingDownIcon size={15} />}
            accent="bg-[#fef2f2] text-[#ef4444]"
            loading={loadingSummary}
          />
          <StatCard
            label="昨日消耗"
            value={summary ? String(summary.yesterday_consume) : "0"}
            icon={<TrendingDownIcon size={15} />}
            accent="bg-[#fff7ed] text-[#f97316]"
            loading={loadingSummary}
          />
          <StatCard
            label="累计消耗"
            value={summary ? String(summary.total_consume) : "0"}
            icon={<TrendingDownIcon size={15} />}
            accent="bg-[#f5f3ff] text-[#7c3aed]"
            loading={loadingSummary}
          />
        </div>

        {summaryError ? (
          <div className="mt-4 flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-600">
            <AlertCircleIcon size={14} />
            <span>余额加载失败：{summaryError}</span>
            <button onClick={() => void loadSummary()} className="ml-auto underline">
              重试
            </button>
          </div>
        ) : null}

        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-800">
          <div className="font-semibold">充值订单为 mock_pending，真实支付暂未接入。</div>
          <div>不会调用微信支付或支付宝真实支付；余额以后台入账或测试接口为准。</div>
        </div>

        <div className="mt-5 rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex items-center justify-between border-b border-[#e4e8f0] px-4 py-3">
            <h2 className="text-sm font-bold text-[#1a1f2e]">可用套餐</h2>
            <button
              onClick={() => void loadPackages()}
              disabled={loadingPackages}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#475467] disabled:opacity-60"
            >
              <RefreshCwIcon size={13} className={loadingPackages ? "animate-spin" : ""} />
              刷新
            </button>
          </div>

          {packageError ? (
            <div className="flex items-center gap-2 px-4 py-6 text-xs text-red-600">
              <AlertCircleIcon size={14} />
              <span>套餐加载失败：{packageError}</span>
              <button onClick={() => void loadPackages()} className="ml-2 underline">
                重试
              </button>
            </div>
          ) : loadingPackages && packages.length === 0 ? (
            <div className="grid grid-cols-1 gap-3 px-4 py-4 md:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-24 animate-pulse rounded-xl bg-[#f1f5f9]" />
              ))}
            </div>
          ) : packages.length === 0 ? (
            <div className="px-4 py-8 text-center text-xs text-[#8b95a6]">暂无可用套餐，可在充值弹窗中使用自定义 Token 数量创建模拟订单。</div>
          ) : (
            <div className="grid grid-cols-1 gap-3 px-4 py-4 md:grid-cols-3">
              {packages.map((pkg) => (
                <button
                  key={pkg.id}
                  onClick={() => setShowRecharge(true)}
                  className="rounded-xl border border-[#e4e8f0] bg-white px-4 py-4 text-left transition-smooth hover:border-[#2563eb] hover:bg-[#eff6ff]"
                >
                  <div className="text-sm font-bold text-[#1a1f2e]">{pkg.name}</div>
                  <div className="mt-2 text-lg font-bold text-[#2563eb]">¥{pkg.price_yuan}</div>
                  <div className="mt-1 text-xs text-[#8b95a6]">{pkg.token_amount} Token</div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Token 明细表 */}
        <div className="mt-5 rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex items-center justify-between border-b border-[#e4e8f0] px-4 py-3">
            <h2 className="text-sm font-bold text-[#1a1f2e]">Token 明细</h2>
            <button
              onClick={() => void loadTransactions(page)}
              disabled={loadingTransactions}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#475467] disabled:opacity-60"
            >
              <RefreshCwIcon size={13} className={loadingTransactions ? "animate-spin" : ""} />
              刷新
            </button>
          </div>

          {transactionError ? (
            <div className="flex items-center gap-2 px-4 py-6 text-xs text-red-600">
              <AlertCircleIcon size={14} />
              <span>明细加载失败：{transactionError}</span>
              <button onClick={() => void loadTransactions(page)} className="ml-2 underline">
                重试
              </button>
            </div>
          ) : loadingTransactions && transactions.length === 0 ? (
            <div className="space-y-2 px-4 py-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-9 animate-pulse rounded-lg bg-[#f1f5f9]" />
              ))}
            </div>
          ) : transactions.length === 0 ? (
            <div className="grid place-items-center px-4 py-12 text-center">
              <CoinsIcon size={28} className="text-[#cbd5e1]" />
              <p className="mt-2 text-xs text-[#8b95a6]">暂无 Token 明细</p>
            </div>
          ) : (
            <>
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#e4e8f0] text-[#8b95a6]">
                    <th className="px-4 py-2.5 font-semibold">类型</th>
                    <th className="px-4 py-2.5 font-semibold">Token 变动</th>
                    <th className="px-4 py-2.5 font-semibold">备注</th>
                    <th className="px-4 py-2.5 font-semibold">时间</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((tx) => {
                    const income = tx.delta_tokens > 0;
                    return (
                      <tr key={tx.id} className="border-b border-[#f1f5f9] last:border-0">
                        <td className="px-4 py-2.5 text-[#1a1f2e]">
                          {TRANSACTION_TYPE_LABELS[tx.transaction_type] || tx.transaction_type}
                        </td>
                        <td className={`px-4 py-2.5 font-semibold ${income ? "text-emerald-600" : "text-[#475467]"}`}>
                          {formatTokenChange(tx.delta_tokens)}
                        </td>
                        <td className="max-w-[260px] truncate px-4 py-2.5 text-[#475467]">
                          {tx.remark || "-"}
                        </td>
                        <td className="px-4 py-2.5 text-[#8b95a6]">
                          {formatDateTimeLocal(tx.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              <div className="flex items-center justify-between border-t border-[#e4e8f0] px-4 py-3 text-xs text-[#8b95a6]">
                <span>
                  共 {total} 条，第 {page}/{totalPages} 页
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => void loadTransactions(page - 1)}
                    disabled={page <= 1 || loadingTransactions}
                    className="grid h-7 w-7 place-items-center rounded-lg border border-[#e4e8f0] bg-white text-[#475467] disabled:opacity-40"
                    aria-label="上一页"
                  >
                    <ChevronLeftIcon size={14} />
                  </button>
                  <button
                    onClick={() => void loadTransactions(page + 1)}
                    disabled={page >= totalPages || loadingTransactions}
                    className="grid h-7 w-7 place-items-center rounded-lg border border-[#e4e8f0] bg-white text-[#475467] disabled:opacity-40"
                    aria-label="下一页"
                  >
                    <ChevronRightIcon size={14} />
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </main>

      {showRecharge ? (
        <RechargeModal
          packages={packages}
          loadingPackages={loadingPackages}
          onClose={() => setShowRecharge(false)}
          onSuccess={handleRechargeSuccess}
        />
      ) : null}
    </section>
  );
}
