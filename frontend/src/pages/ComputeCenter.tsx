import {
  ArrowDownCircleIcon,
  ArrowUpCircleIcon,
  CheckCircle2Icon,
  CoinsIcon,
  CreditCardIcon,
  GaugeIcon,
  HistoryIcon,
  QrCodeIcon,
  RefreshCwIcon,
  WalletCardsIcon,
  XIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { computeSummary, TokenRecord, tokenRecords } from "../data/computeCenterData";
import { readTokenPlans, TokenPlan } from "../data/superComputeConfigData";

type RechargeMode = "plan" | "custom";
type PayMethod = "微信" | "支付宝";

function formatToken(value: number) {
  return `${value.toLocaleString()} Token`;
}

function formatDateTime(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}:${pad(date.getSeconds())}`;
}

function RechargeModal({
  onClose,
  onPaid,
}: {
  onClose: () => void;
  onPaid: (payload: { amount: number; token: number; method: PayMethod; label: string }) => void;
}) {
  const [plans] = useState<TokenPlan[]>(() => readTokenPlans());
  const [mode, setMode] = useState<RechargeMode>("plan");
  const [selectedPlanId, setSelectedPlanId] = useState(plans[0]?.id || "");
  const [customAmount, setCustomAmount] = useState("");
  const [payMethod, setPayMethod] = useState<PayMethod>("微信");
  const [paymentCodeCreated, setPaymentCodeCreated] = useState(false);
  const [orderNo, setOrderNo] = useState("");
  const selectedPlan = plans.find((plan) => plan.id === selectedPlanId) || plans[0];
  const bestTokenRate = Math.max(...plans.map((plan) => plan.token / Math.max(plan.price, 1)), 1000);
  const customPrice = Number(customAmount);
  const rechargeAmount = mode === "plan" ? selectedPlan?.price || 0 : customPrice || 0;
  const rechargeToken = mode === "plan" ? selectedPlan?.token || 0 : Math.round((customPrice || 0) * bestTokenRate);
  const rechargeLabel = mode === "plan" && selectedPlan ? `${selectedPlan.name} 套餐` : "自定义充值";

  const resetPaymentCode = () => {
    setPaymentCodeCreated(false);
    setOrderNo("");
  };

  const createPaymentCode = () => {
    if (mode === "custom" && (!customPrice || customPrice <= 0)) {
      toast.error("请输入有效充值金额");
      return;
    }
    if (!rechargeAmount || !rechargeToken) {
      toast.error("请选择充值套餐");
      return;
    }
    setOrderNo(`XG${Date.now()}`);
    setPaymentCodeCreated(true);
  };

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[720px] overflow-hidden rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">算力充值</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">选择套餐或自定义金额后生成付款码</p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid gap-5 px-5 py-5 text-xs lg:grid-cols-[1fr_260px]">
          <div className="grid gap-4">
            <div className="grid grid-cols-2 rounded-xl bg-[#eef2f7] p-1">
              {([
                ["plan", "套餐充值"],
                ["custom", "自定义金额"],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => {
                    setMode(value);
                    resetPaymentCode();
                  }}
                  className={`h-9 rounded-lg font-semibold transition-smooth ${
                    mode === value
                      ? "bg-white text-[#1a1f2e] shadow-[0_1px_2px_rgba(15,23,42,0.08)]"
                      : "text-[#64748b] hover:text-[#1a1f2e]"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {mode === "plan" ? (
              <div className="grid grid-cols-2 gap-2">
                {plans.map((plan) => {
                  const active = selectedPlanId === plan.id;
                  return (
                    <button
                      key={plan.id}
                      onClick={() => {
                        setSelectedPlanId(plan.id);
                        resetPaymentCode();
                      }}
                      className={`rounded-xl border px-3 py-3 text-left transition-smooth ${
                        active ? "border-blue-200 bg-[#eff6ff] ring-2 ring-blue-500/10" : "border-[#e4e8f0] bg-[#f8fafc] hover:bg-white"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-bold text-[#1a1f2e]">{plan.name}</span>
                        <span className="rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-[#2563eb] ring-1 ring-blue-100">
                          {plan.price} 元
                        </span>
                      </div>
                      <div className="mt-2 text-xs font-semibold text-[#64748b]">{formatToken(plan.token)}</div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="grid gap-3">
                <label className="grid gap-1.5">
                  <span className="font-semibold text-[#64748b]">充值金额</span>
                  <div className="grid grid-cols-[auto_1fr_auto] items-center overflow-hidden rounded-xl border border-[#e4e8f0] bg-[#f8fafc] focus-within:border-[#2563eb] focus-within:bg-white focus-within:ring-4 focus-within:ring-blue-500/10">
                    <span className="pl-3 text-sm font-bold text-[#64748b]">￥</span>
                    <input
                      value={customAmount}
                      onChange={(event) => {
                        setCustomAmount(event.target.value.replace(/[^\d]/g, ""));
                        resetPaymentCode();
                      }}
                      className="h-10 bg-transparent px-2 text-sm outline-none"
                      placeholder="请输入充值金额"
                    />
                    <span className="pr-3 font-semibold text-[#64748b]">元</span>
                  </div>
                </label>
                <div className="rounded-xl bg-[#f8fafc] px-3 py-3 text-[#64748b] ring-1 ring-[#e4e8f0]">
                  预计到账：
                  <b className="ml-1 text-[#1a1f2e]">{formatToken(rechargeToken)}</b>
                </div>
              </div>
            )}

            <div className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">支付方式</span>
              <div className="grid grid-cols-2 gap-2">
                {(["微信", "支付宝"] as const).map((method) => (
                  <button
                    key={method}
                    onClick={() => {
                      setPayMethod(method);
                      resetPaymentCode();
                    }}
                    className={`h-10 rounded-xl font-semibold ring-1 transition-smooth ${
                      payMethod === method
                        ? method === "微信"
                          ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                          : "bg-[#eff6ff] text-[#2563eb] ring-blue-200"
                        : "bg-[#f8fafc] text-[#64748b] ring-[#e4e8f0] hover:bg-white"
                    }`}
                  >
                    {method}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <aside className="rounded-2xl border border-[#e4e8f0] bg-[#f8fafc] p-4">
            <div className="text-xs font-semibold text-[#64748b]">支付金额</div>
            <div className="mt-1 text-2xl font-bold text-[#1a1f2e]">￥{rechargeAmount.toLocaleString()}</div>
            <div className="mt-2 text-xs text-[#64748b]">{rechargeLabel} · {formatToken(rechargeToken)}</div>

            <div className="mt-4 grid h-44 place-items-center rounded-2xl bg-white text-[#2563eb] ring-1 ring-[#e4e8f0]">
              {paymentCodeCreated ? (
                <div className="grid place-items-center gap-2 text-center">
                  <QrCodeIcon size={96} />
                  <span className="text-[11px] font-semibold text-[#64748b]">{payMethod}付款码</span>
                </div>
              ) : (
                <div className="grid place-items-center gap-2 text-center text-[#98a2b3]">
                  <QrCodeIcon size={56} />
                  <span className="text-[11px] font-semibold">待生成付款码</span>
                </div>
              )}
            </div>
            {paymentCodeCreated ? (
              <div className="mt-3 rounded-xl bg-white px-3 py-2 text-[11px] text-[#64748b] ring-1 ring-[#e4e8f0]">
                订单号：<b className="text-[#1a1f2e]">{orderNo}</b>
              </div>
            ) : null}
          </aside>
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          {paymentCodeCreated ? (
            <button
              onClick={() => onPaid({ amount: rechargeAmount, token: rechargeToken, method: payMethod, label: rechargeLabel })}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
            >
              <CheckCircle2Icon size={14} />
              完成支付
            </button>
          ) : (
            <button
              onClick={createPaymentCode}
              className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
            >
              生成付款码
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ComputeCenter() {
  const [showRechargeModal, setShowRechargeModal] = useState(false);
  const [summary, setSummary] = useState(computeSummary);
  const [records, setRecords] = useState<TokenRecord[]>(tokenRecords);
  const statCards = useMemo(
    () => [
      {
        label: "今日消耗",
        value: summary.today,
        icon: <GaugeIcon size={18} />,
        tone: "bg-blue-100 text-blue-700 ring-blue-200",
      },
      {
        label: "昨日消耗",
        value: summary.yesterday,
        icon: <HistoryIcon size={18} />,
        tone: "bg-slate-100 text-slate-700 ring-slate-200",
      },
      {
        label: "累计消耗",
        value: summary.totalUsed,
        icon: <ArrowDownCircleIcon size={18} />,
        tone: "bg-amber-100 text-amber-700 ring-amber-200",
      },
      {
        label: "累计充值",
        value: summary.totalRecharge,
        suffix: "元",
        icon: <ArrowUpCircleIcon size={18} />,
        tone: "bg-emerald-100 text-emerald-700 ring-emerald-200",
      },
    ],
    [summary],
  );

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <CoinsIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">小高算力</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">查看 Token 余额、消耗统计和最近明细</p>
          </div>
        </div>
        <button className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151]">
          <RefreshCwIcon size={14} />
          刷新
        </button>
      </header>

      <section className="border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
              <WalletCardsIcon size={24} />
            </div>
            <div>
              <p className="text-xs font-semibold text-[#667085]">算力余额</p>
              <div className="mt-1 flex items-end gap-2">
                <strong className="text-3xl leading-none text-[#1a1f2e]">
                  {summary.balance.toLocaleString()}
                </strong>
                <span className="pb-0.5 text-sm font-semibold text-[#667085]">Token</span>
              </div>
            </div>
          </div>
          <button
            onClick={() => setShowRechargeModal(true)}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
          >
            <CreditCardIcon size={14} />
            立即充值
          </button>
        </div>
      </section>

      <div className="grid shrink-0 grid-cols-4 gap-0 border-b border-[#e4e8f0] bg-white">
        {statCards.map((card) => (
          <section
            key={card.label}
            className="flex items-center gap-3 border-r border-[#f0f2f7] px-5 py-4 last:border-r-0"
          >
            <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ring-1 ${card.tone}`}>
              {card.icon}
            </div>
            <div>
              <p className="text-xs font-semibold text-[#667085]">{card.label}</p>
              <p className="mt-1 text-xl font-bold text-[#1a1f2e]">
                {card.value.toLocaleString()}
                <span className="ml-1 text-xs font-semibold text-[#98a2b3]">
                  {card.suffix || "Token"}
                </span>
              </p>
            </div>
          </section>
        ))}
      </div>

      <section className="min-h-0 flex-1 overflow-hidden bg-white">
        <div className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
          <div>
            <h2 className="text-sm font-bold text-[#1a1f2e]">Token 明细</h2>
            <p className="mt-1 text-xs text-[#98a2b3]">记录功能消耗、充值和任务扣减情况</p>
          </div>
          <span className="rounded-full bg-[#eff6ff] px-3 py-1 text-xs font-semibold text-[#2563eb]">
            {records.length} 条记录
          </span>
        </div>

        <div className="overflow-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="bg-[#f8fafc] text-[#64748b]">
              <tr>
                <th className="px-5 py-3 font-semibold">类型</th>
                <th className="px-5 py-3 font-semibold">Token 变动</th>
                <th className="px-5 py-3 font-semibold">备注</th>
                <th className="px-5 py-3 font-semibold">时间</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => {
                const isIncome = record.change > 0;
                return (
                  <tr key={record.id} className="border-t border-[#f0f2f7] hover:bg-[#f8fafc]">
                    <td className="px-5 py-3 font-semibold text-[#1a1f2e]">{record.type}</td>
                    <td className="px-5 py-3">
                      <span className={`font-bold ${isIncome ? "text-emerald-600" : "text-[#475467]"}`}>
                        {isIncome ? "+" : "-"} {formatToken(Math.abs(record.change))}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-[#475467]">{record.note}</td>
                    <td className="px-5 py-3 text-[#667085]">{record.time}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-center gap-2 border-t border-[#f0f2f7] py-3">
          <button className="h-8 w-8 rounded-lg bg-[#eef2f7] text-xs text-[#64748b]">{"<"}</button>
          <button className="h-8 w-8 rounded-lg bg-[#2563eb] text-xs font-semibold text-white">1</button>
          <button className="h-8 w-8 rounded-lg bg-[#eef2f7] text-xs text-[#64748b]">2</button>
          <button className="h-8 w-8 rounded-lg bg-[#eef2f7] text-xs text-[#64748b]">{">"}</button>
        </div>
      </section>

      {showRechargeModal ? (
        <RechargeModal
          onClose={() => setShowRechargeModal(false)}
          onPaid={({ amount, token, method, label }) => {
            setSummary((current) => ({
              ...current,
              balance: current.balance + token,
              totalRecharge: current.totalRecharge + amount,
            }));
            setRecords((current) => [
              {
                id: `recharge-${Date.now()}`,
                type: "充值",
                change: token,
                note: `${method}支付充值(${amount}元 · ${label})`,
                time: formatDateTime(new Date()),
              },
              ...current,
            ]);
            setShowRechargeModal(false);
            toast.success("充值已完成");
          }}
        />
      ) : null}
    </section>
  );
}
