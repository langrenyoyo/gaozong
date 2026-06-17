import {
  AlertTriangleIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  ShieldCheckIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { ForbiddenLibrary, forbiddenLibraries, LibraryStatus } from "../data/superConfigData";

const statusOptions: Array<LibraryStatus | "全部状态"> = ["全部状态", "启用", "停用"];

function formatDateTime(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}`;
}

function ForbiddenLibraryModal({
  initial,
  onClose,
  onSave,
}: {
  initial?: ForbiddenLibrary;
  onClose: () => void;
  onSave: (library: ForbiddenLibrary) => void;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [scene, setScene] = useState(initial?.scene || "");
  const [wordsText, setWordsText] = useState(initial?.words.join("\n") || "");

  const submit = () => {
    const words = wordsText
      .split("\n")
      .map((word) => word.trim())
      .filter(Boolean);

    if (!name.trim()) {
      toast.error("请输入词库名称");
      return;
    }
    if (!scene.trim()) {
      toast.error("请输入适用场景");
      return;
    }
    if (!words.length) {
      toast.error("请输入违禁词");
      return;
    }

    onSave({
      id: initial?.id || `fw-${Date.now()}`,
      name: name.trim(),
      scene: scene.trim(),
      words,
      merchantCount: initial?.merchantCount || 0,
      status: initial?.status || "启用",
      updatedAt: formatDateTime(new Date()),
    });
  };

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[560px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 className="text-base font-bold text-[#1a1f2e]">{initial ? "编辑违禁词库" : "新增违禁词库"}</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">维护后可在商户管理中为商户单独选择</p>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid gap-3 px-5 py-5 text-xs">
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">词库名称</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请输入词库名称"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">适用场景</span>
            <input
              value={scene}
              onChange={(event) => setScene(event.target.value)}
              className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="例如：客户销售 / 金融咨询"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">违禁词</span>
            <textarea
              value={wordsText}
              onChange={(event) => setWordsText(event.target.value)}
              className="min-h-32 resize-none rounded-xl border border-[#e4e8f0] bg-white px-3 py-2 leading-6 outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
              placeholder="请输入违禁词，一行一个"
            />
          </label>
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          <button onClick={submit} className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
            保存词库
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SuperForbiddenWords() {
  const [libraries, setLibraries] = useState<ForbiddenLibrary[]>(forbiddenLibraries);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState<LibraryStatus | "全部状态">("全部状态");
  const [editingLibrary, setEditingLibrary] = useState<ForbiddenLibrary | null>(null);
  const [showModal, setShowModal] = useState(false);

  const filtered = useMemo(
    () =>
      libraries.filter((library) => {
        const text = `${library.name}${library.scene}${library.words.join("")}`;
        const matchKeyword = !keyword.trim() || text.includes(keyword.trim());
        const matchStatus = status === "全部状态" || library.status === status;
        return matchKeyword && matchStatus;
      }),
    [keyword, libraries, status],
  );

  const saveLibrary = (library: ForbiddenLibrary) => {
    setLibraries((current) => {
      const exists = current.some((item) => item.id === library.id);
      return exists ? current.map((item) => (item.id === library.id ? library : item)) : [library, ...current];
    });
    setEditingLibrary(null);
    setShowModal(false);
    toast.success("词库已保存");
  };

  const toggleStatus = (library: ForbiddenLibrary) => {
    const nextStatus: LibraryStatus = library.status === "启用" ? "停用" : "启用";
    setLibraries((current) =>
      current.map((item) => (item.id === library.id ? { ...item, status: nextStatus, updatedAt: formatDateTime(new Date()) } : item)),
    );
    toast.success(nextStatus === "启用" ? "已启用词库" : "已停用词库");
  };

  const deleteLibrary = (library: ForbiddenLibrary) => {
    setLibraries((current) => current.filter((item) => item.id !== library.id));
    toast.success("词库已删除");
  };

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#fff7ed] text-[#ea580c]">
            <AlertTriangleIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">违禁词库</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">统一维护合规词库，并在商户管理中按商户分配</p>
          </div>
        </div>
        <button onClick={() => setShowModal(true)} className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
          <PlusIcon size={14} />
          新增词库
        </button>
      </header>

      <div className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
            <input value={keyword} onChange={(event) => setKeyword(event.target.value)} className="h-9 w-[240px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10" placeholder="搜索词库名称、场景或词条" />
          </label>
          <select value={status} onChange={(event) => setStatus(event.target.value as LibraryStatus | "全部状态")} className="h-9 w-[140px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10">
            {statusOptions.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <button
            onClick={() => {
              setKeyword("");
              setStatus("全部状态");
            }}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151] hover:bg-[#f8fafc]"
          >
            <RefreshCwIcon size={14} />
            重置
          </button>
          <span className="ml-auto text-xs font-semibold text-[#64748b]">
            共 <b className="text-[#2563eb]">{filtered.length}</b> 个词库
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="overflow-hidden rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-[#f8fafc] text-[#64748b]">
              <tr>
                <th className="w-[220px] px-4 py-3 font-semibold">词库名称</th>
                <th className="w-[130px] px-4 py-3 font-semibold">适用场景</th>
                <th className="px-4 py-3 font-semibold">词条预览</th>
                <th className="w-[110px] px-4 py-3 font-semibold">使用商户</th>
                <th className="w-[80px] px-4 py-3 font-semibold">状态</th>
                <th className="w-[140px] px-4 py-3 font-semibold">更新时间</th>
                <th className="w-[190px] px-4 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#eef2f6]">
              {filtered.map((library) => (
                <tr key={library.id} className="hover:bg-[#f8fafc]">
                  <td className="px-4 py-3 font-bold text-[#1a1f2e]">{library.name}</td>
                  <td className="px-4 py-3 text-[#374151]">{library.scene}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      {library.words.map((word) => (
                        <span key={word} className="rounded-md bg-[#fff7ed] px-2 py-1 text-[11px] font-semibold text-[#c2410c] ring-1 ring-orange-100">
                          {word}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-[#374151]">{library.merchantCount} 个</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${library.status === "启用" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                      {library.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[#64748b]">{library.updatedAt}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-nowrap gap-1.5">
                      <button onClick={() => toggleStatus(library)} className="inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-lg bg-[#f4f6f8] px-2 text-[11px] font-semibold text-[#374151]">
                        <ShieldCheckIcon size={12} />
                        {library.status === "启用" ? "停用" : "启用"}
                      </button>
                      <button onClick={() => setEditingLibrary(library)} className="inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-lg bg-[#eff6ff] px-2 text-[11px] font-semibold text-[#2563eb]">
                        <PencilIcon size={12} />
                        编辑
                      </button>
                      <button onClick={() => deleteLibrary(library)} className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-red-50 text-red-600">
                        <Trash2Icon size={12} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {showModal || editingLibrary ? (
        <ForbiddenLibraryModal
          initial={editingLibrary || undefined}
          onClose={() => {
            setShowModal(false);
            setEditingLibrary(null);
          }}
          onSave={saveLibrary}
        />
      ) : null}
    </section>
  );
}
