import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  BookOpenIcon,
  BoxesIcon,
  CheckCircle2Icon,
  DatabaseIcon,
  FilePlus2Icon,
  RefreshCwIcon,
} from "lucide-react";
import { toast } from "sonner";
import { KnowledgeCategory, getKnowledgeCategories } from "../api";
import {
  CreateRagDocumentResponse,
  TrainRagResponse,
  createRagDocument,
  listDouyinAccounts,
  trainRag,
} from "../api";
import type { DouyinAccountItem } from "../../douyin-cs/types";

interface DocumentDraft {
  title: string;
  content: string;
  brand: string;
  vehicle_name: string;
}

const emptyDraft: DocumentDraft = {
  title: "",
  content: "",
  brand: "",
  vehicle_name: "",
};

function isAuthorizedAccount(account: DouyinAccountItem): boolean {
  return account.authorization_status === "authorized";
}

function isCategoryAvailable(category: KnowledgeCategory): boolean {
  return category.status !== "disabled" && category.is_active !== false;
}

function categoryTypeLabel(category?: KnowledgeCategory | null): string {
  if (!category) return "未选择";
  if (category.is_base || category.scope_type === "system") return "小高知识库";
  if (category.scope_type === "merchant") return category.name || "小高知识库";
  return category.name || "小高知识库";
}

function displayAccountName(account: DouyinAccountItem): string {
  return account.account_name || account.account_open_id || "未命名企业号";
}

function shortId(value?: string | null): string {
  if (!value) return "-";
  return value.length > 18 ? `${value.slice(0, 10)}...${value.slice(-6)}` : value;
}

function optionalText(value: string): string | undefined {
  const text = value.trim();
  return text || undefined;
}

export default function KnowledgeBasePage() {
  const [accounts, setAccounts] = useState<DouyinAccountItem[]>([]);
  const [categories, setCategories] = useState<KnowledgeCategory[]>([]);
  const [selectedAccountOpenId, setSelectedAccountOpenId] = useState("");
  const [selectedCategoryKey, setSelectedCategoryKey] = useState("");
  const [forceRebuild, setForceRebuild] = useState(false);
  const [draft, setDraft] = useState<DocumentDraft>(emptyDraft);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [training, setTraining] = useState(false);
  const [lastDocument, setLastDocument] = useState<(CreateRagDocumentResponse & { title?: string; category_key?: string }) | null>(null);
  const [lastTraining, setLastTraining] = useState<TrainRagResponse | null>(null);

  const authorizedAccounts = useMemo(() => accounts.filter(isAuthorizedAccount), [accounts]);
  const selectedAccount = useMemo(
    () => accounts.find((account) => account.account_open_id === selectedAccountOpenId) || null,
    [accounts, selectedAccountOpenId],
  );
  const availableCategories = useMemo(() => categories.filter(isCategoryAvailable), [categories]);
  const selectedCategory = useMemo(
    () => categories.find((category) => category.category_key === selectedCategoryKey) || null,
    [categories, selectedCategoryKey],
  );
  const hasAuthorizedAccount = authorizedAccounts.length > 0;
  const canSubmit = hasAuthorizedAccount && Boolean(selectedAccountOpenId) && Boolean(selectedCategoryKey);

  const loadPageData = async () => {
    setLoading(true);
    try {
      const [accountResult, categoryResult] = await Promise.all([
        listDouyinAccounts(),
        getKnowledgeCategories(),
      ]);

      const nextAccounts = accountResult.items || [];
      const nextCategories = categoryResult || [];
      const firstAuthorized = nextAccounts.find(isAuthorizedAccount);
      const baseCategory =
        nextCategories.find((category) => isCategoryAvailable(category) && (category.category_key === "base" || category.is_base)) ||
        nextCategories.find(isCategoryAvailable);

      setAccounts(nextAccounts);
      setCategories(nextCategories);
      setSelectedAccountOpenId((current) => {
        if (current && nextAccounts.some((account) => account.account_open_id === current && isAuthorizedAccount(account))) {
          return current;
        }
        return firstAuthorized?.account_open_id || "";
      });
      setSelectedCategoryKey((current) => {
        if (current && nextCategories.some((category) => category.category_key === current && isCategoryAvailable(category))) {
          return current;
        }
        return baseCategory?.category_key || "";
      });
    } catch (error) {
      toast.error("知识库页面数据加载失败");
      setAccounts([]);
      setCategories([]);
      setSelectedAccountOpenId("");
      setSelectedCategoryKey("");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadPageData();
  }, []);

  const validateSelection = (): boolean => {
    if (!hasAuthorizedAccount) {
      toast.error("请先完成抖音企业号授权");
      return false;
    }
    if (!selectedAccountOpenId) {
      toast.error("请选择已授权的抖音企业号");
      return false;
    }
    if (!selectedCategoryKey || !selectedCategory || !isCategoryAvailable(selectedCategory)) {
      toast.error("请选择可用的知识范围");
      return false;
    }
    return true;
  };

  const submitDocument = async (event: FormEvent) => {
    event.preventDefault();
    if (!validateSelection()) return;

    const title = draft.title.trim();
    const content = draft.content.trim();
    if (!title) {
      toast.error("请填写知识标题");
      return;
    }
    if (!content) {
      toast.error("请填写知识内容");
      return;
    }

    setCreating(true);
    try {
      const result = await createRagDocument({
        account_open_id: selectedAccountOpenId,
        category_key: selectedCategoryKey,
        title,
        content,
        brand: optionalText(draft.brand),
        vehicle_name: optionalText(draft.vehicle_name),
      });
      setLastDocument({ ...result, title, category_key: selectedCategoryKey });
      setDraft(emptyDraft);
      toast.success("知识文档已创建，可点击训练生效");
    } catch (error) {
      toast.error("创建知识文档失败");
    } finally {
      setCreating(false);
    }
  };

  const submitTraining = async () => {
    if (!validateSelection()) return;

    setTraining(true);
    try {
      const result = await trainRag({
        account_open_id: selectedAccountOpenId,
        category_key: selectedCategoryKey,
        force_rebuild: forceRebuild,
      });
      setLastTraining(result);
      toast.success("知识训练已完成");
    } catch (error) {
      toast.error("知识训练失败");
    } finally {
      setTraining(false);
    }
  };

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
              <BookOpenIcon size={22} />
            </div>
            <div>
              <h1 className="text-[15px] font-bold text-[#1a1f2e]">小高知识库</h1>
              <p className="mt-1 text-xs text-[#8b95a6]">
                维护商家客服可参考的常用问答、门店服务、车型说明和接待话术。
              </p>
            </div>
          </div>
          <button
            onClick={loadPageData}
            disabled={loading || creating || training}
            className="grid h-9 w-9 place-items-center rounded-xl border border-[#dfe5ee] bg-white text-[#64748b] hover:bg-[#f8fafc] disabled:opacity-60"
            aria-label="刷新知识库页面数据"
          >
            <RefreshCwIcon size={15} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
        {!hasAuthorizedAccount && !loading ? (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
            请先完成抖音企业号授权。未授权时不能创建知识文档，也不能触发训练。
          </div>
        ) : null}
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(620px,1fr)_380px] overflow-hidden max-[1180px]:grid-cols-1">
        <form onSubmit={submitDocument} className="min-h-0 overflow-y-auto p-5">
          <div className="mb-4 grid grid-cols-2 gap-4 max-[860px]:grid-cols-1">
            <section className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <div className="mb-3 flex items-center gap-2">
                <DatabaseIcon size={16} className="text-[#2563eb]" />
                <h2 className="text-sm font-bold text-[#1a1f2e]">适用账号</h2>
              </div>
              <select
                value={selectedAccountOpenId}
                onChange={(event) => setSelectedAccountOpenId(event.target.value)}
                disabled={loading || authorizedAccounts.length === 0}
                className="h-10 w-full rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10 disabled:opacity-60"
              >
                {authorizedAccounts.length === 0 ? (
                  <option value="">暂无已授权企业号</option>
                ) : (
                  authorizedAccounts.map((account) => (
                    <option key={account.account_open_id} value={account.account_open_id}>
                      {displayAccountName(account)}
                    </option>
                  ))
                )}
              </select>
              <p className="mt-2 text-[11px] text-[#8b95a6]">
                {selectedAccount
                  ? `当前选择：${displayAccountName(selectedAccount)}`
                  : "请选择已授权账号。"}
              </p>
            </section>

            <section className="rounded-xl border border-[#e4e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <div className="mb-3 flex items-center gap-2">
                <BoxesIcon size={16} className="text-[#2563eb]" />
                <h2 className="text-sm font-bold text-[#1a1f2e]">知识范围</h2>
              </div>
              <select
                value={selectedCategoryKey}
                onChange={(event) => setSelectedCategoryKey(event.target.value)}
                disabled={loading || availableCategories.length === 0}
                className="h-10 w-full rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10 disabled:opacity-60"
              >
                {availableCategories.length === 0 ? (
                  <option value="">暂无可用知识范围</option>
                ) : (
                  availableCategories.map((category) => (
                    <option key={category.category_key} value={category.category_key}>
                      {categoryTypeLabel(category)}
                    </option>
                  ))
                )}
              </select>
              <p className="mt-2 text-[11px] text-[#8b95a6]">
                {selectedCategory ? `当前选择：${categoryTypeLabel(selectedCategory)}。` : "请选择知识范围。"}
              </p>
            </section>
          </div>

          <section className="rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="border-b border-[#e4e8f0] px-5 py-4">
              <div className="flex items-center gap-2">
                <FilePlus2Icon size={17} className="text-[#2563eb]" />
                <h2 className="text-sm font-bold text-[#1a1f2e]">新增知识</h2>
              </div>
              <p className="mt-1 text-xs text-[#8b95a6]">
                新增后点击右侧整理按钮，客服回复建议即可参考这些内容。
              </p>
            </div>

            <div className="space-y-4 px-5 py-5">
              <label className="grid gap-1.5 text-xs">
                  <span className="font-semibold text-[#475569]">标题</span>
                <input
                  value={draft.title}
                  onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                  className="h-10 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                  placeholder="例如：门店金融方案说明"
                />
              </label>

              <label className="grid gap-1.5 text-xs">
                  <span className="font-semibold text-[#475569]">内容</span>
                <textarea
                  value={draft.content}
                  onChange={(event) => setDraft({ ...draft, content: event.target.value })}
                  className="min-h-[260px] resize-none rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 py-3 text-sm leading-6 text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                  placeholder="填写客服可参考的知识内容。"
                />
              </label>

              <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
                <label className="grid gap-1.5 text-xs">
                  <span className="font-semibold text-[#475569]">品牌（可选）</span>
                  <input
                    value={draft.brand}
                    onChange={(event) => setDraft({ ...draft, brand: event.target.value })}
                    className="h-10 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                    placeholder="例如：比亚迪"
                  />
                </label>
                <label className="grid gap-1.5 text-xs">
                  <span className="font-semibold text-[#475569]">车型（可选）</span>
                  <input
                    value={draft.vehicle_name}
                    onChange={(event) => setDraft({ ...draft, vehicle_name: event.target.value })}
                    className="h-10 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                    placeholder="例如：海鸥"
                  />
                </label>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-[#e4e8f0] px-5 py-4 max-[760px]:flex-col max-[760px]:items-stretch">
              <p className="text-xs text-[#8b95a6]">新增后点击“整理小高知识库”生效。</p>
              <button
                type="submit"
                disabled={!canSubmit || creating || training}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {creating ? <RefreshCwIcon size={14} className="animate-spin" /> : <FilePlus2Icon size={14} />}
                新增知识
              </button>
            </div>
          </section>
        </form>

        <aside className="min-h-0 overflow-y-auto border-l border-[#e4e8f0] bg-white p-5 max-[1180px]:border-l-0 max-[1180px]:border-t">
          <section className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-4">
            <div className="flex items-center gap-2">
              <RefreshCwIcon size={16} className="text-[#2563eb]" />
              <h2 className="text-sm font-bold text-[#1a1f2e]">整理小高知识库</h2>
            </div>
            <p className="mt-2 text-xs leading-5 text-[#64748b]">
              将新增内容整理为客服回复建议可参考的知识。
            </p>
            <label className="mt-4 flex items-center gap-2 text-xs font-semibold text-[#475569]">
              <input
                type="checkbox"
                checked={forceRebuild}
                onChange={(event) => setForceRebuild(event.target.checked)}
                className="h-4 w-4 rounded border-[#cbd5e1]"
              />
              重新整理全部内容
            </label>
            <button
              type="button"
              onClick={submitTraining}
              disabled={!canSubmit || creating || training}
              className="mt-4 inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-xl bg-[#0f766e] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(15,118,110,0.18)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {training ? <RefreshCwIcon size={14} className="animate-spin" /> : <CheckCircle2Icon size={14} />}
              整理小高知识库
            </button>
          </section>

          <section className="mt-4 rounded-xl border border-[#e4e8f0] bg-white p-4">
            <h2 className="text-sm font-bold text-[#1a1f2e]">最近一次新增</h2>
            {lastDocument ? (
              <dl className="mt-3 space-y-2 text-xs">
                <div className="flex justify-between gap-3">
                  <dt className="text-[#8b95a6]">记录</dt>
                  <dd className="font-semibold text-[#1a1f2e]">{lastDocument.document_id ?? "-"}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-[#8b95a6]">标题</dt>
                  <dd className="min-w-0 truncate font-semibold text-[#1a1f2e]">{lastDocument.title || "-"}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-[#8b95a6]">状态</dt>
                  <dd className="font-semibold text-[#0f766e]">{lastDocument.status || "created"}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-3 text-xs leading-5 text-[#8b95a6]">尚未新增知识。</p>
            )}
          </section>

          <section className="mt-4 rounded-xl border border-[#e4e8f0] bg-white p-4">
            <h2 className="text-sm font-bold text-[#1a1f2e]">最近一次整理</h2>
            {lastTraining ? (
              <dl className="mt-3 space-y-2 text-xs">
                <div className="flex justify-between gap-3">
                  <dt className="text-[#8b95a6]">记录</dt>
                  <dd className="font-semibold text-[#1a1f2e]">{lastTraining.training_run_id ?? "-"}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-[#8b95a6]">知识条数</dt>
                  <dd className="font-semibold text-[#1a1f2e]">{lastTraining.document_count ?? "-"}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-[#8b95a6]">状态</dt>
                  <dd className="font-semibold text-[#0f766e]">{lastTraining.status || "-"}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-3 text-xs leading-5 text-[#8b95a6]">尚未整理小高知识库。</p>
            )}
          </section>

          <section className="mt-4 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] p-4 text-xs leading-5 text-[#64748b]">
            <div>当前账号：{selectedAccount ? displayAccountName(selectedAccount) : "未选择"}</div>
            <div className="mt-1">知识范围：{selectedCategory ? categoryTypeLabel(selectedCategory) : "未选择"}</div>
          </section>
        </aside>
      </div>
    </section>
  );
}
