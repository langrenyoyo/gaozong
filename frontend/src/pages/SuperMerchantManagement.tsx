import {
  BotIcon,
  GiftIcon,
  KeyRoundIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  ShieldOffIcon,
  XIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { readTokenPlans, TokenPlan } from "../data/superComputeConfigData";
import { forbiddenLibraries, followUpPrompts } from "../data/superConfigData";

type MerchantStatus = "启用" | "禁用";

interface Merchant {
  id: string;
  account: string;
  name: string;
  avatar: string;
  agents: string[];
  expiryDays: number;
  authorization: string[];
  forbiddenLibrary: string;
  followUpPrompt: string;
  computeBalance: number;
  status: MerchantStatus;
  createdAt: string;
}

type MerchantEditDraft = Omit<Merchant, "id" | "createdAt">;

const initialMerchants: Merchant[] = [
  {
    id: "m1",
    account: "18512345678",
    name: "高新精品二手车",
    avatar: "高新门店",
    agents: ["精品代步车", "检测报告讲解"],
    expiryDays: 0,
    authorization: ["抖音客服"],
    forbiddenLibrary: "二手车销售基础违禁词",
    followUpPrompt: "留资转化回访提示",
    computeBalance: 0,
    status: "启用",
    createdAt: "2026-01-01 12:12:12",
  },
  {
    id: "m2",
    account: "18587654321",
    name: "城南优选车行",
    avatar: "城南门店",
    agents: ["金融方案助手"],
    expiryDays: 365,
    authorization: ["自动分配线索"],
    forbiddenLibrary: "金融方案合规词库",
    followUpPrompt: "金融方案回访提示",
    computeBalance: 100000,
    status: "禁用",
    createdAt: "2026-01-01 12:12:12",
  },
  {
    id: "m3",
    account: "18600001111",
    name: "星河二手车",
    avatar: "星河门店",
    agents: ["精品代步车"],
    expiryDays: 365,
    authorization: ["每日报表推送"],
    forbiddenLibrary: "二手车销售基础违禁词",
    followUpPrompt: "沉默客户唤醒提示",
    computeBalance: 0,
    status: "启用",
    createdAt: "2026-01-01 12:12:12",
  },
  {
    id: "m4",
    account: "18700002222",
    name: "鼎盛名车",
    avatar: "鼎盛门店",
    agents: ["检测报告讲解"],
    expiryDays: 365,
    authorization: ["AI剪辑"],
    forbiddenLibrary: "车况承诺风险词",
    followUpPrompt: "留资转化回访提示",
    computeBalance: 100000,
    status: "禁用",
    createdAt: "2026-01-01 12:12:12",
  },
  {
    id: "m5",
    account: "18800003333",
    name: "东区车管家",
    avatar: "东区门店",
    agents: ["精品代步车", "金融方案助手"],
    expiryDays: 365,
    authorization: ["AI剪辑", "一键过审"],
    forbiddenLibrary: "二手车销售基础违禁词",
    followUpPrompt: "留资转化回访提示",
    computeBalance: 0,
    status: "启用",
    createdAt: "2026-01-01 12:12:12",
  },
  {
    id: "m6",
    account: "18900004444",
    name: "北城认证二手车",
    avatar: "北城门店",
    agents: ["金融方案助手"],
    expiryDays: 365,
    authorization: ["抖音客服"],
    forbiddenLibrary: "金融方案合规词库",
    followUpPrompt: "金融方案回访提示",
    computeBalance: 100000,
    status: "禁用",
    createdAt: "2026-01-01 12:12:12",
  },
];

const agentOptions = ["全部智能体", "精品代步车", "金融方案助手", "检测报告讲解"];
const statusOptions: Array<MerchantStatus | "全部状态"> = ["全部状态", "启用", "禁用"];
const authorizationOptions = ["抖音客服", "自动分配线索", "每日报表推送", "AI剪辑", "一键过审"];
const enabledForbiddenLibraries = forbiddenLibraries.filter((item) => item.status === "启用");
const enabledFollowUpPrompts = followUpPrompts.filter((item) => item.status === "启用");

function toggleRequiredOption(values: string[], value: string) {
  if (values.includes(value)) {
    return values.length > 1 ? values.filter((item) => item !== value) : values;
  }
  return [...values, value];
}

function formatDateTime(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}:${pad(date.getSeconds())}`;
}

function AddMerchantModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (merchant: Merchant) => void;
}) {
  const [merchantName, setMerchantName] = useState("");
  const [loginAccount, setLoginAccount] = useState("");
  const [selectedAgents, setSelectedAgents] = useState<string[]>(["精品代步车"]);
  const [selectedAuthorizations, setSelectedAuthorizations] = useState<string[]>(["抖音客服"]);
  const [selectedForbiddenLibrary, setSelectedForbiddenLibrary] = useState(enabledForbiddenLibraries[0]?.name || "");
  const [selectedFollowUpPrompt, setSelectedFollowUpPrompt] = useState(enabledFollowUpPrompts[0]?.name || "");

  const submitMerchant = () => {
    if (!merchantName.trim()) {
      toast.error("请输入商户名称");
      return;
    }
    if (!loginAccount.trim()) {
      toast.error("请输入登录账号");
      return;
    }

    onCreate({
      id: `m-${Date.now()}`,
      account: loginAccount.trim(),
      name: merchantName.trim(),
      avatar: "默认门店",
      agents: selectedAgents,
      expiryDays: 0,
      authorization: selectedAuthorizations,
      forbiddenLibrary: selectedForbiddenLibrary,
      followUpPrompt: selectedFollowUpPrompt,
      computeBalance: 0,
      status: "启用",
      createdAt: formatDateTime(new Date()),
    });
  };

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[620px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">新增商户</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">创建商户账号并分配智能体与功能授权</p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid gap-3 px-5 py-5 text-xs">
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">商户名称</span>
              <input
                value={merchantName}
                onChange={(event) => setMerchantName(event.target.value)}
                className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                placeholder="请输入商户名称"
              />
            </label>
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">登录账号</span>
              <input
                value={loginAccount}
                onChange={(event) => setLoginAccount(event.target.value)}
                className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                placeholder="请输入账号"
              />
            </label>
          </div>
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">分配智能体</span>
            <div className="flex flex-wrap gap-2">
              {agentOptions.slice(1).map((agent) => {
                const active = selectedAgents.includes(agent);
                return (
                  <button
                    key={agent}
                    onClick={() => setSelectedAgents((current) => toggleRequiredOption(current, agent))}
                    className={`h-8 rounded-lg px-3 font-semibold ${
                      active ? "bg-[#2563eb] text-white" : "bg-[#f4f6f8] text-[#374151]"
                    }`}
                  >
                    {agent}
                  </button>
                );
              })}
            </div>
          </label>
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">功能授权</span>
            <div className="flex flex-wrap gap-2">
              {authorizationOptions.map((authorization) => {
                const active = selectedAuthorizations.includes(authorization);
                return (
                  <button
                    key={authorization}
                    onClick={() => setSelectedAuthorizations((current) => toggleRequiredOption(current, authorization))}
                    className={`h-8 rounded-lg px-3 font-semibold ${
                      active ? "bg-[#2563eb] text-white" : "bg-[#f4f6f8] text-[#374151]"
                    }`}
                  >
                    {authorization}
                  </button>
                );
              })}
            </div>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">违禁词库</span>
              <select
                value={selectedForbiddenLibrary}
                onChange={(event) => setSelectedForbiddenLibrary(event.target.value)}
                className="h-10 rounded-xl border border-[#e4e8f0] bg-white px-3 outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
              >
                {enabledForbiddenLibraries.map((library) => (
                  <option key={library.id}>{library.name}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">回访提示词</span>
              <select
                value={selectedFollowUpPrompt}
                onChange={(event) => setSelectedFollowUpPrompt(event.target.value)}
                className="h-10 rounded-xl border border-[#e4e8f0] bg-white px-3 outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
              >
                {enabledFollowUpPrompts.map((prompt) => (
                  <option key={prompt.id}>{prompt.name}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="rounded-xl bg-[#f8fafc] px-3 py-2 text-[11px] leading-5 text-[#64748b] ring-1 ring-[#e4e8f0]">
            有效期、算力额度和启用状态创建后可在商户列表中单独操作。
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          <button onClick={submitMerchant} className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
            新增商户
          </button>
        </div>
      </div>
    </div>
  );
}

function NumberActionModal({
  merchant,
  mode,
  onClose,
  onConfirm,
}: {
  merchant: Merchant;
  mode: "extend" | "recharge";
  onClose: () => void;
  onConfirm: (value: number) => void;
}) {
  const [value, setValue] = useState("");
  const isExtend = mode === "extend";

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[420px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">{isExtend ? "商户延期" : "算力充值"}</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">{merchant.name}</p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid gap-3 px-5 py-5 text-xs">
          <div className="rounded-xl bg-[#f8fafc] px-3 py-3 text-[#64748b] ring-1 ring-[#e4e8f0]">
            当前{isExtend ? "有效期" : "算力余额"}：
            <b className="ml-1 text-[#1a1f2e]">
              {isExtend ? `${merchant.expiryDays} 天` : `${merchant.computeBalance.toLocaleString()} Token`}
            </b>
          </div>
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">{isExtend ? "延期天数" : "充值 Token 数量"}</span>
            <input
              value={value}
              onChange={(event) => setValue(event.target.value.replace(/[^\d]/g, ""))}
              className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder={isExtend ? "请输入延期天数" : "请输入 Token 数量"}
            />
          </label>
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          <button
            onClick={() => {
              const parsedValue = Number(value);
              if (!parsedValue || parsedValue <= 0) {
                toast.error(isExtend ? "请输入有效延期天数" : "请输入有效 Token 数量");
                return;
              }
              onConfirm(parsedValue);
            }}
            className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
          >
            确认{isExtend ? "延期" : "充值"}
          </button>
        </div>
      </div>
    </div>
  );
}

function PackageGrantModal({
  merchant,
  onClose,
  onGrant,
}: {
  merchant: Merchant;
  onClose: () => void;
  onGrant: (plan: TokenPlan) => void;
}) {
  const [plans] = useState<TokenPlan[]>(() => readTokenPlans());
  const [selectedPlanId, setSelectedPlanId] = useState(plans[0]?.id || "");
  const selectedPlan = plans.find((plan) => plan.id === selectedPlanId);

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[460px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">发放套餐</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">{merchant.name}</p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid gap-3 px-5 py-5 text-xs">
          <div className="rounded-xl bg-[#f8fafc] px-3 py-3 text-[#64748b] ring-1 ring-[#e4e8f0]">
            当前算力余额：
            <b className="ml-1 text-[#1a1f2e]">{merchant.computeBalance.toLocaleString()} Token</b>
          </div>
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">选择套餐</span>
            <select
              value={selectedPlanId}
              onChange={(event) => setSelectedPlanId(event.target.value)}
              className="h-10 rounded-xl border border-[#e4e8f0] bg-white px-3 outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
            >
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>
                  {plan.name} · {plan.token.toLocaleString()} Token · {plan.price} 元
                </option>
              ))}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-[#f8fafc] px-3 py-3 ring-1 ring-[#e4e8f0]">
              <div className="font-semibold text-[#98a2b3]">发放 Token</div>
              <div className="mt-1 font-bold text-[#1a1f2e]">{selectedPlan ? selectedPlan.token.toLocaleString() : "0"}</div>
            </div>
            <div className="rounded-xl bg-[#f8fafc] px-3 py-3 ring-1 ring-[#e4e8f0]">
              <div className="font-semibold text-[#98a2b3]">发放后余额</div>
              <div className="mt-1 font-bold text-[#1a1f2e]">
                {selectedPlan ? (merchant.computeBalance + selectedPlan.token).toLocaleString() : merchant.computeBalance.toLocaleString()}
              </div>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          <button
            onClick={() => {
              if (!selectedPlan) {
                toast.error("请选择套餐");
                return;
              }
              onGrant(selectedPlan);
            }}
            className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
          >
            确认发放
          </button>
        </div>
      </div>
    </div>
  );
}

function EditMerchantModal({
  merchant,
  onClose,
  onSave,
}: {
  merchant: Merchant;
  onClose: () => void;
  onSave: (draft: MerchantEditDraft) => void;
}) {
  const [draft, setDraft] = useState<MerchantEditDraft>({
    account: merchant.account,
    name: merchant.name,
    avatar: merchant.avatar,
    agents: merchant.agents,
    expiryDays: merchant.expiryDays,
    authorization: merchant.authorization,
    forbiddenLibrary: merchant.forbiddenLibrary,
    followUpPrompt: merchant.followUpPrompt,
    computeBalance: merchant.computeBalance,
    status: merchant.status,
  });

  const toggleAgent = (agentName: string) => {
    setDraft((current) => {
      const exists = current.agents.includes(agentName);
      const agents = exists ? current.agents.filter((item) => item !== agentName) : [...current.agents, agentName];
      return { ...current, agents: agents.length ? agents : current.agents };
    });
  };

  const toggleAuthorization = (authorization: string) => {
    setDraft((current) => ({
      ...current,
      authorization: toggleRequiredOption(current.authorization, authorization),
    }));
  };

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[620px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">编辑商户</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">更新商户账号、授权、词库和提示词配置</p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid gap-3 px-5 py-5 text-xs">
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">商户名称</span>
              <input
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              />
            </label>
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">登录账号</span>
              <input
                value={draft.account}
                disabled
                className="h-10 cursor-not-allowed rounded-xl border border-[#e4e8f0] bg-[#eef2f6] px-3 text-[#64748b] outline-none"
              />
              <span className="text-[11px] text-[#98a2b3]">创建后不可修改</span>
            </label>
          </div>

          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">分配智能体</span>
            <div className="flex flex-wrap gap-2">
              {agentOptions.slice(1).map((agentName) => {
                const active = draft.agents.includes(agentName);
                return (
                  <button
                    key={agentName}
                    onClick={() => toggleAgent(agentName)}
                    className={`h-8 rounded-lg px-3 font-semibold ${
                      active ? "bg-[#2563eb] text-white" : "bg-[#f4f6f8] text-[#374151]"
                    }`}
                  >
                    {agentName}
                  </button>
                );
              })}
            </div>
          </label>

          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">功能授权</span>
            <div className="flex flex-wrap gap-2">
              {authorizationOptions.map((authorization) => {
                const active = draft.authorization.includes(authorization);
                return (
                  <button
                    key={authorization}
                    onClick={() => toggleAuthorization(authorization)}
                    className={`h-8 rounded-lg px-3 font-semibold ${
                      active ? "bg-[#2563eb] text-white" : "bg-[#f4f6f8] text-[#374151]"
                    }`}
                  >
                    {authorization}
                  </button>
                );
              })}
            </div>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">违禁词库</span>
              <select
                value={draft.forbiddenLibrary}
                onChange={(event) => setDraft({ ...draft, forbiddenLibrary: event.target.value })}
                className="h-10 rounded-xl border border-[#e4e8f0] bg-white px-3 outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
              >
                {enabledForbiddenLibraries.map((library) => (
                  <option key={library.id}>{library.name}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">回访提示词</span>
              <select
                value={draft.followUpPrompt}
                onChange={(event) => setDraft({ ...draft, followUpPrompt: event.target.value })}
                className="h-10 rounded-xl border border-[#e4e8f0] bg-white px-3 outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
              >
                {enabledFollowUpPrompts.map((prompt) => (
                  <option key={prompt.id}>{prompt.name}</option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          <button
            onClick={() => onSave(draft)}
            className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
          >
            保存修改
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SuperMerchantManagement() {
  const [merchantList, setMerchantList] = useState<Merchant[]>(initialMerchants);
  const [keyword, setKeyword] = useState("");
  const [account, setAccount] = useState("");
  const [agent, setAgent] = useState("全部智能体");
  const [status, setStatus] = useState<MerchantStatus | "全部状态">("全部状态");
  const [showModal, setShowModal] = useState(false);
  const [extensionMerchant, setExtensionMerchant] = useState<Merchant | null>(null);
  const [rechargeMerchant, setRechargeMerchant] = useState<Merchant | null>(null);
  const [packageMerchant, setPackageMerchant] = useState<Merchant | null>(null);
  const [editingMerchant, setEditingMerchant] = useState<Merchant | null>(null);

  const filtered = useMemo(
    () =>
      merchantList.filter((merchant) => {
        const matchKeyword = !keyword.trim() || merchant.name.includes(keyword.trim());
        const matchAccount = !account.trim() || merchant.account.includes(account.trim());
        const matchAgent = agent === "全部智能体" || merchant.agents.includes(agent);
        const matchStatus = status === "全部状态" || merchant.status === status;
        return matchKeyword && matchAccount && matchAgent && matchStatus;
      }),
    [account, agent, keyword, merchantList, status],
  );

  const updateMerchant = (merchantId: string, patch: Partial<Merchant>) => {
    setMerchantList((current) => current.map((merchant) => (merchant.id === merchantId ? { ...merchant, ...patch } : merchant)));
  };

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <BotIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">商户管理</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">管理商户账号、功能授权、智能体和算力余额</p>
          </div>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
        >
          <PlusIcon size={14} />
          新增商户
        </button>
      </header>

      <div className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              className="h-9 w-[180px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请输入商户名称"
            />
          </label>
          <input
            value={account}
            onChange={(event) => setAccount(event.target.value)}
            className="h-9 w-[160px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
            placeholder="请输入账号"
          />
          <select
            value={agent}
            onChange={(event) => setAgent(event.target.value)}
            className="h-9 w-[160px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          >
            {agentOptions.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as MerchantStatus | "全部状态")}
            className="h-9 w-[140px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          >
            {statusOptions.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <button
            onClick={() => {
              setKeyword("");
              setAccount("");
              setAgent("全部智能体");
              setStatus("全部状态");
            }}
            className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151] hover:bg-[#f8fafc]"
          >
            <RefreshCwIcon size={14} />
            重置
          </button>
          <span className="text-xs font-semibold text-[#64748b]">
            共 <b className="text-[#2563eb]">{filtered.length}</b> 个商户
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="overflow-hidden rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-[#f8fafc] text-[#64748b]">
              <tr>
                <th className="w-[130px] px-4 py-3 font-semibold">账号</th>
                <th className="w-[150px] px-4 py-3 font-semibold">商户名称</th>
                <th className="px-4 py-3 font-semibold">智能体</th>
                <th className="w-[120px] px-4 py-3 font-semibold">有效期</th>
                <th className="w-[150px] px-4 py-3 font-semibold">功能授权</th>
                <th className="w-[150px] px-4 py-3 font-semibold">违禁词库</th>
                <th className="w-[150px] px-4 py-3 font-semibold">回访提示词</th>
                <th className="w-[140px] px-4 py-3 font-semibold">算力余额</th>
                <th className="w-[80px] px-4 py-3 font-semibold">状态</th>
                <th className="w-[140px] px-4 py-3 font-semibold">创建时间</th>
                <th className="w-[250px] px-4 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#eef2f6]">
              {filtered.map((merchant) => (
                <tr key={merchant.id} className="hover:bg-[#f8fafc]">
                  <td className="px-4 py-3 font-semibold text-[#1a1f2e]">{merchant.account}</td>
                  <td className="px-4 py-3">
                    <div className="font-bold text-[#1a1f2e]">{merchant.name}</div>
                    <div className="mt-1 text-[11px] text-[#98a2b3]">{merchant.avatar}</div>
                  </td>
                  <td className="px-4 py-3 text-[#374151]">{merchant.agents.join("、")}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="text-[#374151]">{merchant.expiryDays} 天</span>
                      <button
                        onClick={() => setExtensionMerchant(merchant)}
                        className="text-[11px] font-semibold text-[#2563eb] hover:text-[#1d4ed8]"
                      >
                        延期
                      </button>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="line-clamp-2 text-[#374151]">{merchant.authorization.join("、")}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="line-clamp-2 text-[#374151]">{merchant.forbiddenLibrary}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="line-clamp-2 text-[#374151]">{merchant.followUpPrompt}</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="text-[#374151]">{merchant.computeBalance.toLocaleString()}</span>
                      <button
                        onClick={() => setRechargeMerchant(merchant)}
                        className="text-[11px] font-semibold text-[#2563eb] hover:text-[#1d4ed8]"
                      >
                        充值
                      </button>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                        merchant.status === "启用" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {merchant.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[#64748b]">{merchant.createdAt}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        onClick={() => {
                          const nextStatus = merchant.status === "启用" ? "禁用" : "启用";
                          updateMerchant(merchant.id, { status: nextStatus });
                          toast.success(nextStatus === "启用" ? "已启用商户" : "已禁用商户");
                        }}
                        className="inline-flex h-7 items-center gap-1 rounded-lg bg-[#f4f6f8] px-2 text-[11px] font-semibold text-[#374151]"
                      >
                        <ShieldOffIcon size={12} />
                        {merchant.status === "启用" ? "禁用" : "启用"}
                      </button>
                      <button
                        onClick={() => setPackageMerchant(merchant)}
                        className="inline-flex h-7 items-center gap-1 rounded-lg bg-[#f0fdf4] px-2 text-[11px] font-semibold text-emerald-700"
                      >
                        <GiftIcon size={12} />
                        发放套餐
                      </button>
                      <button
                        onClick={() => setEditingMerchant(merchant)}
                        className="inline-flex h-7 items-center gap-1 rounded-lg bg-[#eff6ff] px-2 text-[11px] font-semibold text-[#2563eb]"
                      >
                        <PencilIcon size={12} />
                        编辑
                      </button>
                      <button
                        onClick={() => toast.success("已重置密码")}
                        className="inline-flex h-7 items-center gap-1 rounded-lg bg-amber-50 px-2 text-[11px] font-semibold text-amber-700"
                      >
                        <KeyRoundIcon size={12} />
                        重置密码
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex justify-center gap-2">
          {["<", "1", "2", ">"].map((page) => (
            <button
              key={page}
              className={`h-8 min-w-8 rounded-lg px-3 text-xs font-semibold ${
                page === "1" ? "bg-[#2563eb] text-white" : "bg-white text-[#64748b] ring-1 ring-[#e4e8f0]"
              }`}
            >
              {page}
            </button>
          ))}
        </div>
      </div>

      {showModal ? (
        <AddMerchantModal
          onClose={() => setShowModal(false)}
          onCreate={(merchant) => {
            setMerchantList((current) => [merchant, ...current]);
            setShowModal(false);
            toast.success("商户已创建");
          }}
        />
      ) : null}
      {extensionMerchant ? (
        <NumberActionModal
          merchant={extensionMerchant}
          mode="extend"
          onClose={() => setExtensionMerchant(null)}
          onConfirm={(days) => {
            updateMerchant(extensionMerchant.id, { expiryDays: extensionMerchant.expiryDays + days });
            setExtensionMerchant(null);
            toast.success(`已延期 ${days} 天`);
          }}
        />
      ) : null}
      {rechargeMerchant ? (
        <NumberActionModal
          merchant={rechargeMerchant}
          mode="recharge"
          onClose={() => setRechargeMerchant(null)}
          onConfirm={(tokens) => {
            updateMerchant(rechargeMerchant.id, { computeBalance: rechargeMerchant.computeBalance + tokens });
            setRechargeMerchant(null);
            toast.success(`已充值 ${tokens.toLocaleString()} Token`);
          }}
        />
      ) : null}
      {packageMerchant ? (
        <PackageGrantModal
          merchant={packageMerchant}
          onClose={() => setPackageMerchant(null)}
          onGrant={(plan) => {
            updateMerchant(packageMerchant.id, { computeBalance: packageMerchant.computeBalance + plan.token });
            setPackageMerchant(null);
            toast.success(`已发放 ${plan.name} 套餐`);
          }}
        />
      ) : null}
      {editingMerchant ? (
        <EditMerchantModal
          merchant={editingMerchant}
          onClose={() => setEditingMerchant(null)}
          onSave={(draft) => {
            updateMerchant(editingMerchant.id, draft);
            setEditingMerchant(null);
            toast.success("商户信息已保存");
          }}
        />
      ) : null}
    </section>
  );
}
