import { useCallback, useEffect, useMemo, useState } from "react";
import { ShieldCheckIcon, PlusIcon, RefreshCwIcon, PencilIcon } from "lucide-react";
import { toast } from "sonner";
import {
  getForbiddenWordLibraries,
  getForbiddenWords,
  createForbiddenWord,
  updateForbiddenWord,
  toggleForbiddenWord,
  type ForbiddenWord,
  type ForbiddenWordLibrary,
} from "../api/forbiddenWords";
import { userFacingError } from "../lib/userFacingError";

// 违禁词超管管理页：词库筛选 + 关键词搜索 + 词条 CRUD（新增/编辑/启停）。
// 后端一期未提供 DELETE，删除通过禁用实现；命中日志查询不在本阶段。
interface EditState {
  word: string;
  safe_word: string;
  severity: string;
  library_key: string;
}

const EMPTY_EDIT: EditState = { word: "", safe_word: "", severity: "", library_key: "" };

export default function SuperForbiddenWords() {
  const [libraries, setLibraries] = useState<ForbiddenWordLibrary[]>([]);
  const [items, setItems] = useState<ForbiddenWord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [libraryKey, setLibraryKey] = useState<string>("");
  const [keyword, setKeyword] = useState("");
  const [enabledFilter, setEnabledFilter] = useState<"all" | "true" | "false">("all");

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<EditState>(EMPTY_EDIT);
  const [submitting, setSubmitting] = useState(false);

  const loadLibraries = useCallback(async () => {
    try {
      const libs = await getForbiddenWordLibraries();
      setLibraries(libs);
    } catch (err) {
      toast.error(userFacingError(err, "违禁词库加载失败"));
    }
  }, []);

  const loadWords = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getForbiddenWords({
        library_key: libraryKey || undefined,
        enabled: enabledFilter === "all" ? null : enabledFilter === "true",
        keyword: keyword.trim() || undefined,
      });
      setItems(data.items || []);
    } catch (err) {
      const msg = userFacingError(err, "违禁词加载失败，请稍后重试");
      setError(msg);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [libraryKey, keyword, enabledFilter]);

  useEffect(() => {
    void loadLibraries();
  }, [loadLibraries]);

  useEffect(() => {
    void loadWords();
  }, [loadWords]);

  const libraryName = useMemo(() => {
    const map = new Map(libraries.map((lib) => [lib.library_key, lib.name]));
    return (key: string) => map.get(key) || key;
  }, [libraries]);

  const openCreate = () => {
    setEditingId(null);
    setForm({ ...EMPTY_EDIT, library_key: libraryKey || libraries[0]?.library_key || "" });
    setShowForm(true);
  };

  const openEdit = (item: ForbiddenWord) => {
    setEditingId(item.id);
    setForm({
      word: item.word,
      safe_word: item.safe_word,
      severity: item.severity || "",
      library_key: item.library_key,
    });
    setShowForm(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.library_key) {
      toast.error("请选择违禁词库");
      return;
    }
    if (!form.word.trim() || !form.safe_word.trim()) {
      toast.error("违禁词和安全替换词均不能为空");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        word: form.word.trim(),
        safe_word: form.safe_word.trim(),
        severity: form.severity.trim() || null,
        library_key: form.library_key,
      };
      if (editingId !== null) {
        await updateForbiddenWord(editingId, {
          word: payload.word,
          safe_word: payload.safe_word,
          severity: payload.severity,
        });
        toast.success("违禁词已更新");
      } else {
        await createForbiddenWord(payload);
        toast.success("违禁词已新增");
      }
      setShowForm(false);
      setForm(EMPTY_EDIT);
      setEditingId(null);
      void loadWords();
    } catch (err) {
      toast.error(userFacingError(err, "保存失败，请检查输入或重试"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggle = async (item: ForbiddenWord) => {
    try {
      await toggleForbiddenWord(item.id, !item.enabled);
      setItems((prev) => prev.map((row) => (row.id === item.id ? { ...row, enabled: !row.enabled } : row)));
      toast.success(item.enabled ? "已禁用" : "已启用");
    } catch (err) {
      toast.error(userFacingError(err, "启停失败"));
    }
  };

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <ShieldCheckIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">违禁词配置</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">违禁词命中后替换为安全词，不拦截</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void loadWords()}
            className="grid h-9 w-9 place-items-center rounded-lg border border-[#e4e8f0] bg-white text-[#475569] transition hover:bg-[#f8fafc]"
            title="刷新"
          >
            <RefreshCwIcon size={16} />
          </button>
          <button
            type="button"
            onClick={openCreate}
            className="flex h-9 items-center gap-1.5 rounded-lg bg-[#2563eb] px-3 text-xs font-semibold text-white transition hover:bg-[#1d4ed8]"
          >
            <PlusIcon size={15} /> 新增违禁词
          </button>
        </div>
      </header>

      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-[#e4e8f0] bg-white px-5 py-3">
        <select
          value={libraryKey}
          onChange={(e) => setLibraryKey(e.target.value)}
          className="h-9 rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs text-[#1a1f2e] outline-none focus:border-[#2563eb]"
        >
          <option value="">全部词库</option>
          {libraries.map((lib) => (
            <option key={lib.library_key} value={lib.library_key}>
              {lib.name}
            </option>
          ))}
        </select>
        <select
          value={enabledFilter}
          onChange={(e) => setEnabledFilter(e.target.value as "all" | "true" | "false")}
          className="h-9 rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs text-[#1a1f2e] outline-none focus:border-[#2563eb]"
        >
          <option value="all">全部状态</option>
          <option value="true">已启用</option>
          <option value="false">已禁用</option>
        </select>
        <input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="搜索违禁词"
          className="h-9 w-48 rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs text-[#1a1f2e] outline-none focus:border-[#2563eb]"
        />
      </div>

      <main className="min-h-0 flex-1 overflow-auto p-5">
        {error ? (
          <div className="rounded-lg border border-[#fecaca] bg-[#fef2f2] px-4 py-3 text-xs text-[#b91c1c]">{error}</div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-[#e4e8f0] bg-white">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#f8fafc] text-[#64748b]">
                <tr>
                  <th className="px-4 py-3 font-semibold">词库</th>
                  <th className="px-4 py-3 font-semibold">违禁词</th>
                  <th className="px-4 py-3 font-semibold">安全替换词</th>
                  <th className="px-4 py-3 font-semibold">严重级别</th>
                  <th className="px-4 py-3 font-semibold">命中次数</th>
                  <th className="px-4 py-3 font-semibold">状态</th>
                  <th className="px-4 py-3 text-right font-semibold">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f1f5f9]">
                {loading ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-[#8b95a6]">加载中...</td>
                  </tr>
                ) : items.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-[#8b95a6]">暂无违禁词</td>
                  </tr>
                ) : (
                  items.map((item) => (
                    <tr key={item.id} className="text-[#1a1f2e]">
                      <td className="px-4 py-3">{libraryName(item.library_key)}</td>
                      <td className="px-4 py-3 font-medium">{item.word}</td>
                      <td className="px-4 py-3 text-[#0f766e]">{item.safe_word}</td>
                      <td className="px-4 py-3 text-[#64748b]">{item.severity || "-"}</td>
                      <td className="px-4 py-3 text-[#64748b]">{item.hit_count}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                            item.enabled ? "bg-[#dcfce7] text-[#166534]" : "bg-[#f1f5f9] text-[#64748b]"
                          }`}
                        >
                          {item.enabled ? "启用" : "禁用"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => openEdit(item)}
                            className="grid h-7 w-7 place-items-center rounded-md border border-[#e4e8f0] text-[#475569] transition hover:bg-[#f8fafc]"
                            title="编辑"
                          >
                            <PencilIcon size={14} />
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleToggle(item)}
                            className={`rounded-md px-2.5 text-[11px] font-semibold transition ${
                              item.enabled
                                ? "border border-[#e4e8f0] text-[#b91c1c] hover:bg-[#fef2f2]"
                                : "bg-[#dcfce7] text-[#166534] hover:bg-[#bbf7d0]"
                            }`}
                          >
                            {item.enabled ? "禁用" : "启用"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {showForm ? (
        <div className="absolute inset-0 z-30 grid place-items-center bg-black/30">
          <form
            onSubmit={(e) => void handleSubmit(e)}
            className="w-[440px] rounded-xl bg-white p-5 shadow-[0_18px_50px_rgba(0,0,0,0.2)]"
          >
            <h2 className="text-sm font-bold text-[#1a1f2e]">{editingId !== null ? "编辑违禁词" : "新增违禁词"}</h2>
            <div className="mt-4 space-y-3">
              <label className="block">
                <span className="text-xs font-medium text-[#475569]">所属词库</span>
                <select
                  value={form.library_key}
                  onChange={(e) => setForm((f) => ({ ...f, library_key: e.target.value }))}
                  disabled={editingId !== null}
                  className="mt-1 h-9 w-full rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs text-[#1a1f2e] outline-none focus:border-[#2563eb] disabled:bg-[#f8fafc]"
                >
                  <option value="">请选择词库</option>
                  {libraries.map((lib) => (
                    <option key={lib.library_key} value={lib.library_key}>
                      {lib.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs font-medium text-[#475569]">违禁词</span>
                <input
                  value={form.word}
                  onChange={(e) => setForm((f) => ({ ...f, word: e.target.value }))}
                  className="mt-1 h-9 w-full rounded-lg border border-[#e4e8f0] px-3 text-xs outline-none focus:border-[#2563eb]"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-[#475569]">安全替换词</span>
                <input
                  value={form.safe_word}
                  onChange={(e) => setForm((f) => ({ ...f, safe_word: e.target.value }))}
                  className="mt-1 h-9 w-full rounded-lg border border-[#e4e8f0] px-3 text-xs outline-none focus:border-[#2563eb]"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-[#475569]">严重级别（可选）</span>
                <input
                  value={form.severity}
                  onChange={(e) => setForm((f) => ({ ...f, severity: e.target.value }))}
                  placeholder="如 high / medium / low"
                  className="mt-1 h-9 w-full rounded-lg border border-[#e4e8f0] px-3 text-xs outline-none focus:border-[#2563eb]"
                />
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingId(null);
                  setForm(EMPTY_EDIT);
                }}
                className="h-9 rounded-lg border border-[#e4e8f0] px-4 text-xs font-semibold text-[#475569] hover:bg-[#f8fafc]"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="h-9 rounded-lg bg-[#2563eb] px-4 text-xs font-semibold text-white transition hover:bg-[#1d4ed8] disabled:opacity-60"
              >
                {submitting ? "保存中..." : "保存"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </section>
  );
}
