import axios from "axios";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { BookOpenIcon, PlusIcon, RefreshCwIcon, TagsIcon } from "lucide-react";
import { toast } from "sonner";
import {
  KnowledgeCategory,
  createKnowledgeCategory,
  getKnowledgeCategories,
} from "../api/aiAgents";

interface CategoryDraft {
  name: string;
  category_key: string;
  sort_order: string;
}

const emptyDraft: CategoryDraft = {
  name: "",
  category_key: "",
  sort_order: "",
};

function categoryTypeLabel(category: KnowledgeCategory): string {
  if (category.is_base || category.scope_type === "system") return "系统内置";
  if (category.scope_type === "merchant") return "商户分类";
  return category.scope_type || "未知类型";
}

function categoryStatusLabel(category: KnowledgeCategory): string {
  if (category.status) {
    if (category.status === "active") return "启用";
    if (category.status === "disabled") return "停用";
    return category.status;
  }
  if (category.is_active === false) return "停用";
  return "启用";
}

function isConflictError(error: unknown): boolean {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    const data = error.response?.data as unknown;
    const record = data && typeof data === "object" ? data as Record<string, unknown> : {};
    const detail = record.detail && typeof record.detail === "object" ? record.detail as Record<string, unknown> : {};
    const code = String(record.err_code || record.code || detail.err_code || detail.code || "");
    const message = String(record.message || record.detail || detail.message || error.message || "");

    return (
      status === 409 ||
      code === "KNOWLEDGE_CATEGORY_CONFLICT" ||
      /conflict/i.test(message) ||
      message.includes("已存在")
    );
  }

  if (error instanceof Error) {
    return /conflict/i.test(error.message) || error.message.includes("已存在");
  }

  return false;
}

function normalizeSortOrder(value: string): number | undefined {
  const text = value.trim();
  if (!text) return undefined;
  const next = Number(text);
  return Number.isFinite(next) ? next : undefined;
}

export default function KnowledgeCategoriesPage() {
  const [categories, setCategories] = useState<KnowledgeCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<CategoryDraft>(emptyDraft);

  const baseCount = useMemo(() => categories.filter((category) => category.is_base || category.scope_type === "system").length, [categories]);
  const merchantCount = useMemo(() => categories.filter((category) => category.scope_type === "merchant" && !category.is_base).length, [categories]);

  const loadCategories = async () => {
    setLoading(true);
    try {
      const items = await getKnowledgeCategories();
      setCategories(items);
    } catch (error) {
      toast.error("知识分类加载失败");
      setCategories([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadCategories();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const name = draft.name.trim();
    const categoryKey = draft.category_key.trim();

    if (!name) {
      toast.error("请填写分类名称");
      return;
    }

    if (!categoryKey) {
      toast.error("请填写分类标识");
      return;
    }

    if (categoryKey === "base") {
      toast.error("分类标识不能使用 base");
      return;
    }

    setSaving(true);
    try {
      await createKnowledgeCategory({
        name,
        category_key: categoryKey,
        sort_order: normalizeSortOrder(draft.sort_order),
      });
      toast.success("知识分类已创建");
      setDraft(emptyDraft);
      await loadCategories();
    } catch (error) {
      toast.error(isConflictError(error) ? "分类标识已存在，请更换 category_key" : "创建分类失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <TagsIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">知识分类</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">查看系统内置分类，创建商户自己的知识分类。</p>
          </div>
        </div>
        <button
          onClick={loadCategories}
          disabled={loading || saving}
          className="grid h-9 w-9 place-items-center rounded-xl border border-[#dfe5ee] bg-white text-[#64748b] hover:bg-[#f8fafc] disabled:opacity-60"
          aria-label="刷新知识分类"
        >
          <RefreshCwIcon size={15} className={loading ? "animate-spin" : ""} />
        </button>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(620px,1fr)_360px] overflow-hidden max-[1180px]:grid-cols-1">
        <div className="min-h-0 overflow-y-auto p-5">
          <div className="mb-4 grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-[#e4e8f0] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <div className="text-[11px] font-semibold text-[#8b95a6]">全部分类</div>
              <div className="mt-2 text-xl font-bold text-[#1a1f2e]">{categories.length}</div>
            </div>
            <div className="rounded-xl border border-[#e4e8f0] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <div className="text-[11px] font-semibold text-[#8b95a6]">系统内置</div>
              <div className="mt-2 text-xl font-bold text-[#1a1f2e]">{baseCount}</div>
            </div>
            <div className="rounded-xl border border-[#e4e8f0] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <div className="text-[11px] font-semibold text-[#8b95a6]">商户分类</div>
              <div className="mt-2 text-xl font-bold text-[#1a1f2e]">{merchantCount}</div>
            </div>
          </div>

          <div className="overflow-hidden rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="grid grid-cols-[minmax(140px,1.2fr)_minmax(160px,1fr)_110px_90px_80px] gap-3 border-b border-[#e4e8f0] bg-[#f8fafc] px-4 py-3 text-[11px] font-bold text-[#64748b]">
              <span>分类名称</span>
              <span>分类标识</span>
              <span>类型</span>
              <span>状态</span>
              <span className="text-right">排序</span>
            </div>

            {loading ? (
              <div className="grid h-56 place-items-center text-sm text-[#64748b]">正在加载知识分类...</div>
            ) : categories.length === 0 ? (
              <div className="grid h-56 place-items-center">
                <div className="text-center">
                  <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[#eff6ff] text-[#2563eb]">
                    <BookOpenIcon size={24} />
                  </div>
                  <p className="mt-3 text-sm font-bold text-[#1a1f2e]">暂无知识分类</p>
                  <p className="mt-1 text-xs text-[#8b95a6]">创建商户分类后会显示在这里。</p>
                </div>
              </div>
            ) : (
              <div className="divide-y divide-[#edf1f6]">
                {categories.map((category) => (
                  <div
                    key={category.category_key}
                    className="grid min-h-14 grid-cols-[minmax(140px,1.2fr)_minmax(160px,1fr)_110px_90px_80px] items-center gap-3 px-4 py-3 text-xs text-[#475569]"
                  >
                    <span className="min-w-0 truncate font-semibold text-[#1a1f2e]">{category.name || category.category_key}</span>
                    <code className="min-w-0 truncate rounded-lg bg-[#f1f5f9] px-2 py-1 font-mono text-[11px] text-[#334155]">
                      {category.category_key}
                    </code>
                    <span className={category.is_base || category.scope_type === "system" ? "font-semibold text-[#2563eb]" : "font-semibold text-[#0f766e]"}>
                      {categoryTypeLabel(category)}
                    </span>
                    <span className={categoryStatusLabel(category) === "启用" ? "text-emerald-600" : "text-[#94a3b8]"}>
                      {categoryStatusLabel(category)}
                    </span>
                    <span className="text-right text-[#64748b]">{category.sort_order ?? "-"}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <aside className="min-h-0 border-l border-[#e4e8f0] bg-white max-[1180px]:border-l-0 max-[1180px]:border-t">
          <form onSubmit={submit} className="flex h-full min-h-0 flex-col">
            <div className="border-b border-[#e4e8f0] px-5 py-4">
              <div className="flex items-center gap-2.5">
                <div className="grid h-9 w-9 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
                  <PlusIcon size={18} />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-[#1a1f2e]">创建商户分类</h2>
                  <p className="mt-1 text-[11px] text-[#8b95a6]">分类标识创建后本阶段不提供编辑。</p>
                </div>
              </div>
            </div>

            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5">
              <label className="grid gap-1.5 text-xs">
                <span className="font-semibold text-[#475569]">分类名称</span>
                <input
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                  className="h-10 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                  placeholder="例如：门店活动"
                />
              </label>

              <label className="grid gap-1.5 text-xs">
                <span className="font-semibold text-[#475569]">分类标识 category_key</span>
                <input
                  value={draft.category_key}
                  onChange={(event) => setDraft({ ...draft, category_key: event.target.value })}
                  className="h-10 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 font-mono text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                  placeholder="例如：store_campaign"
                />
              </label>

              <label className="grid gap-1.5 text-xs">
                <span className="font-semibold text-[#475569]">排序 sort_order</span>
                <input
                  type="number"
                  value={draft.sort_order}
                  onChange={(event) => setDraft({ ...draft, sort_order: event.target.value })}
                  className="h-10 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                  placeholder="可不填"
                />
              </label>

              <div className="rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 py-3 text-xs leading-5 text-[#64748b]">
                系统内置分类由平台维护；商户分类创建后可在智能体编辑页选择使用。
              </div>
            </div>

            <div className="border-t border-[#e4e8f0] px-5 py-4">
              <button
                type="submit"
                disabled={saving}
                className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:opacity-60"
              >
                {saving ? <RefreshCwIcon size={14} className="animate-spin" /> : <PlusIcon size={14} />}
                创建分类
              </button>
            </div>
          </form>
        </aside>
      </div>
    </section>
  );
}
