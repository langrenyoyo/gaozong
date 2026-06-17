import {
  CpuIcon,
  PencilIcon,
  PlusIcon,
  XIcon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { readTokenPlans, saveTokenPlans, TokenPlan } from "../data/superComputeConfigData";

type ConsumptionMode = "actual" | "custom";

interface FunctionCost {
  id: string;
  name: string;
  consumptionMode: ConsumptionMode;
  tokenAmount?: number;
  markup: string;
}

const initialFunctionCosts: FunctionCost[] = [
  { id: "f1", name: "AI回复", consumptionMode: "actual", markup: "33%" },
  { id: "f2", name: "线索分配", consumptionMode: "custom", tokenAmount: 1000, markup: "33%" },
  { id: "f3", name: "报表推送", consumptionMode: "custom", tokenAmount: 1000, markup: "33%" },
  { id: "f4", name: "AI剪辑", consumptionMode: "actual", markup: "33%" },
  { id: "f5", name: "一键过审", consumptionMode: "custom", tokenAmount: 1000, markup: "33%" },
];

function formatFunctionConsumption(cost: FunctionCost) {
  if (cost.consumptionMode === "actual") return "实际 + 上浮";
  return `${(cost.tokenAmount || 0).toLocaleString()}/次 + 上浮`;
}

function EditFunctionCostModal({
  initial,
  onClose,
  onSave,
}: {
  initial: FunctionCost;
  onClose: () => void;
  onSave: (cost: FunctionCost) => void;
}) {
  const [consumptionMode, setConsumptionMode] = useState<ConsumptionMode>(initial.consumptionMode);
  const [tokenAmount, setTokenAmount] = useState(initial.tokenAmount ? String(initial.tokenAmount) : "");
  const [markup, setMarkup] = useState(initial.markup.replace(/[^\d]/g, ""));

  const submitCost = () => {
    const parsedTokenAmount = Number(tokenAmount);
    const parsedMarkup = Number(markup);

    if (consumptionMode === "custom" && (!parsedTokenAmount || parsedTokenAmount <= 0)) {
      toast.error("请输入有效单次 Token 消耗量");
      return;
    }
    if (!parsedMarkup || parsedMarkup <= 0) {
      toast.error("请输入有效上浮比例");
      return;
    }

    onSave({
      ...initial,
      consumptionMode,
      tokenAmount: consumptionMode === "custom" ? parsedTokenAmount : undefined,
      markup: `${parsedMarkup}%`,
    });
  };

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[460px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">编辑 Token 消耗</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">{initial.name}</p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid gap-3 px-5 py-5 text-xs">
          <div className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">Token 消耗规则</span>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setConsumptionMode("actual")}
                className={`h-10 rounded-xl text-xs font-semibold ring-1 transition ${
                  consumptionMode === "actual"
                    ? "bg-[#eff6ff] text-[#2563eb] ring-blue-200"
                    : "bg-[#f8fafc] text-[#64748b] ring-[#e4e8f0] hover:bg-white"
                }`}
              >
                实际消耗
              </button>
              <button
                onClick={() => setConsumptionMode("custom")}
                className={`h-10 rounded-xl text-xs font-semibold ring-1 transition ${
                  consumptionMode === "custom"
                    ? "bg-[#eff6ff] text-[#2563eb] ring-blue-200"
                    : "bg-[#f8fafc] text-[#64748b] ring-[#e4e8f0] hover:bg-white"
                }`}
              >
                自定义消耗
              </button>
            </div>
          </div>
          {consumptionMode === "custom" ? (
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">单次 Token 消耗量</span>
              <div className="grid grid-cols-[1fr_auto] items-center overflow-hidden rounded-xl border border-[#e4e8f0] bg-[#f8fafc] focus-within:border-[#2563eb] focus-within:bg-white focus-within:ring-4 focus-within:ring-blue-500/10">
                <input
                  value={tokenAmount}
                  onChange={(event) => setTokenAmount(event.target.value.replace(/[^\d]/g, ""))}
                  className="h-10 bg-transparent px-3 outline-none"
                  placeholder="请输入单次 Token 消耗量"
                />
                <span className="px-3 font-semibold text-[#64748b]">Token/次</span>
              </div>
            </label>
          ) : null}
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">上浮比例</span>
            <div className="grid grid-cols-[1fr_auto] items-center overflow-hidden rounded-xl border border-[#e4e8f0] bg-[#f8fafc] focus-within:border-[#2563eb] focus-within:bg-white focus-within:ring-4 focus-within:ring-blue-500/10">
              <input
                value={markup}
                onChange={(event) => setMarkup(event.target.value.replace(/[^\d]/g, ""))}
                className="h-10 bg-transparent px-3 outline-none"
                placeholder="请输入上浮比例"
              />
              <span className="px-3 font-semibold text-[#64748b]">%</span>
            </div>
          </label>
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          <button onClick={submitCost} className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
            保存修改
          </button>
        </div>
      </div>
    </div>
  );
}

function AddPlanModal({
  initial,
  onClose,
  onSave,
}: {
  initial?: TokenPlan;
  onClose: () => void;
  onSave: (plan: TokenPlan) => void;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [token, setToken] = useState(initial ? String(initial.token) : "");
  const [price, setPrice] = useState(initial ? String(initial.price) : "");

  const submitPlan = () => {
    const parsedToken = Number(token);
    const parsedPrice = Number(price);

    if (!name.trim()) {
      toast.error("请输入套餐名称");
      return;
    }
    if (!parsedToken || parsedToken <= 0) {
      toast.error("请输入有效 Token 数量");
      return;
    }
    if (!parsedPrice || parsedPrice <= 0) {
      toast.error("请输入有效售价");
      return;
    }

    onSave({
      id: initial?.id || `p-${Date.now()}`,
      name: name.trim(),
      token: parsedToken,
      price: parsedPrice,
    });
  };

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[420px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">{initial ? "编辑 Token 套餐" : "新增 Token 套餐"}</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">配置商户可购买的算力套餐</p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid gap-3 px-5 py-5 text-xs">
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">套餐名称</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="例如：E"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">Token数量</span>
            <input
              value={token}
              onChange={(event) => setToken(event.target.value.replace(/[^\d]/g, ""))}
              className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请输入 Token 数量"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">售价</span>
            <input
              value={price}
              onChange={(event) => setPrice(event.target.value.replace(/[^\d]/g, ""))}
              className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请输入售价"
            />
          </label>
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          <button onClick={submitPlan} className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
            保存套餐
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SuperComputeConfig() {
  const [showModal, setShowModal] = useState(false);
  const [editingPlan, setEditingPlan] = useState<TokenPlan | null>(null);
  const [editingFunctionCost, setEditingFunctionCost] = useState<FunctionCost | null>(null);
  const [functionCostList, setFunctionCostList] = useState<FunctionCost[]>(initialFunctionCosts);
  const [tokenPlans, setTokenPlans] = useState<TokenPlan[]>(() => readTokenPlans());

  const saveFunctionCost = (cost: FunctionCost) => {
    setFunctionCostList((current) => current.map((item) => (item.id === cost.id ? cost : item)));
    setEditingFunctionCost(null);
    toast.success("Token 消耗配置已保存");
  };

  const savePlan = (plan: TokenPlan) => {
    setTokenPlans((current) => {
      const exists = current.some((item) => item.id === plan.id);
      const nextPlans = exists ? current.map((item) => (item.id === plan.id ? plan : item)) : [plan, ...current];
      saveTokenPlans(nextPlans);
      return nextPlans;
    });
    setShowModal(false);
    setEditingPlan(null);
    toast.success("套餐已保存");
  };

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <CpuIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">算力配置</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">配置功能 Token 消耗规则和商户可购买套餐</p>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <section className="rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="border-b border-[#e4e8f0] px-5 py-4">
            <div>
              <h2 className="text-sm font-bold text-[#1a1f2e]">功能 Token 消耗配置</h2>
              <p className="mt-1 text-xs text-[#8b95a6]">定义不同功能调用时的算力扣减规则</p>
            </div>
          </div>
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-[#f8fafc] text-[#64748b]">
              <tr>
                <th className="px-5 py-3 font-semibold">功能</th>
                <th className="px-5 py-3 font-semibold">Token消耗</th>
                <th className="px-5 py-3 font-semibold">上浮比例</th>
                <th className="w-[120px] px-5 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#eef2f6]">
              {functionCostList.map((item) => (
                <tr key={item.id} className="hover:bg-[#f8fafc]">
                  <td className="px-5 py-4 font-bold text-[#1a1f2e]">{item.name}</td>
                  <td className="px-5 py-4 text-[#374151]">{formatFunctionConsumption(item)}</td>
                  <td className="px-5 py-4">
                    <span className="rounded-md bg-[#eff6ff] px-2 py-0.5 text-[11px] font-semibold text-[#2563eb]">
                      {item.markup}
                    </span>
                  </td>
                  <td className="px-5 py-4">
                    <button
                      onClick={() => setEditingFunctionCost(item)}
                      className="inline-flex h-7 items-center gap-1 rounded-lg bg-[#f4f6f8] px-2 text-[11px] font-semibold text-[#374151]"
                    >
                      <PencilIcon size={12} />
                      编辑
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mt-5 rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
            <div>
              <h2 className="text-sm font-bold text-[#1a1f2e]">Token 套餐配置</h2>
              <p className="mt-1 text-xs text-[#8b95a6]">维护商户充值套餐的 Token 数量与售价</p>
            </div>
            <button
              onClick={() => setShowModal(true)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#2563eb] px-3 text-xs font-semibold text-white"
            >
              <PlusIcon size={13} />
              新增套餐
            </button>
          </div>
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-[#f8fafc] text-[#64748b]">
              <tr>
                <th className="px-5 py-3 font-semibold">套餐</th>
                <th className="px-5 py-3 font-semibold">Token数量</th>
                <th className="px-5 py-3 font-semibold">售价</th>
                <th className="w-[120px] px-5 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#eef2f6]">
              {tokenPlans.map((plan) => (
                <tr key={plan.id} className="hover:bg-[#f8fafc]">
                  <td className="px-5 py-4 font-bold text-[#1a1f2e]">{plan.name}</td>
                  <td className="px-5 py-4 text-[#374151]">{plan.token.toLocaleString()}</td>
                  <td className="px-5 py-4 text-[#374151]">{plan.price}</td>
                  <td className="px-5 py-4">
                    <button
                      onClick={() => setEditingPlan(plan)}
                      className="inline-flex h-7 items-center gap-1 rounded-lg bg-[#f4f6f8] px-2 text-[11px] font-semibold text-[#374151]"
                    >
                      <PencilIcon size={12} />
                      编辑
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      {showModal || editingPlan ? (
        <AddPlanModal
          initial={editingPlan || undefined}
          onClose={() => {
            setShowModal(false);
            setEditingPlan(null);
          }}
          onSave={savePlan}
        />
      ) : null}
      {editingFunctionCost ? (
        <EditFunctionCostModal
          initial={editingFunctionCost}
          onClose={() => setEditingFunctionCost(null)}
          onSave={saveFunctionCost}
        />
      ) : null}
    </section>
  );
}
