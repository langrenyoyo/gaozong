import {
  ClapperboardIcon,
  Edit3Icon,
  PlayIcon,
  RotateCcwIcon,
  SearchIcon,
  UploadCloudIcon,
  Wand2Icon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { MaterialItem, MaterialType, materials } from "../data/materialLibraryData";

const typeClass: Record<MaterialType, string> = {
  口播: "bg-[#eff6ff] text-[#2563eb]",
  高光: "bg-[#d1fae5] text-[#047857]",
};

function VideoPreview({ material }: { material: MaterialItem }) {
  const [scriptMap, setScriptMap] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftScript, setDraftScript] = useState("");
  const [recognizingId, setRecognizingId] = useState<string | null>(null);
  const currentScript = scriptMap[material.id] || material.script;
  const isEditing = editingId === material.id;
  const isRecognizing = recognizingId === material.id;

  const startEdit = () => {
    setEditingId(material.id);
    setDraftScript(currentScript);
  };

  const saveEdit = () => {
    setScriptMap((prev) => ({ ...prev, [material.id]: draftScript.trim() || currentScript }));
    setEditingId(null);
  };

  const recognizeAgain = () => {
    setRecognizingId(material.id);
    window.setTimeout(() => {
      setScriptMap((prev) => ({
        ...prev,
        [material.id]:
          material.type === "口播"
            ? "重新识别完成：本段口播围绕车型亮点、车况说明、价格优势和到店引导展开，可继续用于匹配高光素材。"
            : "重新识别完成：已识别外观细节、内饰空间、仪表中控和车辆动态镜头，可用于剪辑镜头匹配。",
      }));
      setRecognizingId(null);
    }, 800);
  };

  return (
    <div className="flex min-h-0 flex-col border-l border-[#e4e8f0] bg-white">
      <div className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
        <div>
          <h2 className="text-[15px] font-bold text-[#1a1f2e]">{material.filename}</h2>
          <p className="mt-1 text-xs text-[#8b95a6]">
            {material.title} · 时长 {material.duration}
          </p>
        </div>
        <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${typeClass[material.type]}`}>
          {material.type}
        </span>
      </div>

      <div className="shrink-0 bg-[#101828] p-4">
        <div className="relative h-[min(38vh,360px)] min-h-[240px] overflow-hidden rounded-xl bg-[#111827]">
          <img src={material.imageUrl} alt={material.title} className="h-full w-full object-cover" />
          <div className="absolute inset-0 bg-gradient-to-t from-[#101828]/55 via-transparent to-[#101828]/10" />
          <button className="absolute left-1/2 top-1/2 grid h-14 w-14 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white text-[#101828] shadow-[0_18px_34px_rgba(0,0,0,0.28)] transition-smooth hover:scale-105">
            <PlayIcon size={24} fill="currentColor" />
          </button>
        </div>
        <div className="flex items-center gap-3 px-2 pb-1 pt-3 text-xs text-white/70">
          <span>00:00</span>
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/15">
            <div className="h-full w-[34%] rounded-full bg-[#60a5fa]" />
          </div>
          <span>{material.duration}</span>
        </div>
      </div>

      <div className="mx-5 mt-4 min-h-0 flex-1 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-4">
        <div className="mb-2 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-[#1a1f2e]">
              {material.type === "口播" ? "口播文案" : "片段描述"}
            </h3>
            <p className="mt-1 text-xs text-[#98a2b3]">
              {material.type === "口播" ? "用于匹配高光素材" : "用于剪辑镜头匹配"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {isEditing ? (
              <>
                <button
                  onClick={() => setEditingId(null)}
                  className="h-8 rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#64748b]"
                >
                  取消
                </button>
                <button
                  onClick={saveEdit}
                  className="h-8 rounded-lg bg-[#2563eb] px-3 text-xs font-semibold text-white"
                >
                  保存
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={startEdit}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#475467] transition-smooth hover:bg-[#f8fafc]"
                >
                  <Edit3Icon size={13} />
                  编辑
                </button>
                <button
                  onClick={recognizeAgain}
                  disabled={isRecognizing}
                  className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#eff6ff] px-3 text-xs font-semibold text-[#2563eb] transition-smooth hover:bg-[#dbeafe] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RotateCcwIcon size={13} className={isRecognizing ? "animate-spin" : ""} />
                  {isRecognizing ? "识别中" : "重新识别"}
                </button>
              </>
            )}
          </div>
        </div>
        {isEditing ? (
          <textarea
            value={draftScript}
            onChange={(event) => setDraftScript(event.target.value)}
            className="min-h-[132px] w-full resize-none rounded-xl border border-[#dbe3ef] bg-white p-3 text-sm leading-7 text-[#374151] outline-none transition-smooth focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10"
          />
        ) : (
          <div className="max-h-[160px] overflow-y-auto rounded-xl bg-white p-3 text-sm leading-7 text-[#374151] ring-1 ring-[#eef2f6]">
            {currentScript}
          </div>
        )}
      </div>

      <div className="flex shrink-0 justify-end border-t border-[#e4e8f0] px-5 py-4">
        <button className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
          <Wand2Icon size={14} />
          用于剪辑
        </button>
      </div>
    </div>
  );
}

export default function MaterialLibrary() {
  const [selectedId, setSelectedId] = useState(materials[0].id);
  const [keyword, setKeyword] = useState("");
  const [type, setType] = useState<MaterialType | "全部">("全部");
  const selected = materials.find((item) => item.id === selectedId) || materials[0];

  const filtered = useMemo(
    () =>
      materials.filter((item) => {
        const matchKeyword =
          !keyword.trim() ||
          item.title.includes(keyword.trim()) ||
          item.filename.includes(keyword.trim());
        const matchType = type === "全部" || item.type === type;
        return matchKeyword && matchType;
      }),
    [keyword, type],
  );

  const grouped = filtered.reduce<Record<string, MaterialItem[]>>((acc, item) => {
    acc[item.date] = acc[item.date] || [];
    acc[item.date].push(item);
    return acc;
  }, {});

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <ClapperboardIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">小高素材库</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">管理口播和高光视频素材</p>
          </div>
        </div>
        <button className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
          <UploadCloudIcon size={14} />
          上传素材
        </button>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)]">
        <aside className="flex min-h-0 flex-col border-r border-[#e4e8f0] bg-white">
          <div className="border-b border-[#e4e8f0] p-4">
            <label className="relative block">
              <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
              <input
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                className="h-9 w-full rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                placeholder="输入标题搜索"
              />
            </label>
            <div className="mt-3 grid grid-cols-3 rounded-xl bg-[#eef2f7] p-1">
              {(["全部", "口播", "高光"] as const).map((item) => (
                <button
                  key={item}
                  onClick={() => setType(item)}
                  className={`h-8 rounded-lg text-xs font-semibold transition-smooth ${
                    type === item
                      ? "bg-white text-[#1a1f2e] shadow-[0_1px_2px_rgba(15,23,42,0.08)]"
                      : "text-[#8b95a6] hover:text-[#1a1f2e]"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {Object.entries(grouped).map(([date, items]) => (
              <div key={date} className="mb-4 last:mb-0">
                <div className="mb-2 text-xs font-bold text-[#667085]">{date}</div>
                <div className="grid gap-2">
                  {items.map((item) => {
                    const active = selectedId === item.id;
                    return (
                      <button
                        key={item.id}
                        onClick={() => setSelectedId(item.id)}
                        className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left transition-smooth ${
                          active ? "bg-[#eff6ff] ring-1 ring-[#bfdbfe]" : "hover:bg-[#f8fafc]"
                        }`}
                      >
                        <div className="relative h-14 w-16 shrink-0 overflow-hidden rounded-xl bg-[#e0edff]">
                          <img src={item.imageUrl} alt={item.title} className="h-full w-full object-cover" />
                          <div className="absolute inset-0 bg-[#101828]/16" />
                          <div className="absolute left-1/2 top-1/2 grid h-6 w-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white/90 text-[#101828]">
                            <PlayIcon size={12} fill="currentColor" />
                          </div>
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-xs font-bold text-[#1a1f2e]">{item.title}</div>
                          <div className="mt-1 text-[11px] text-[#98a2b3]">时长：{item.duration}</div>
                          <span className={`mt-1 inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${typeClass[item.type]}`}>
                            {item.type}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </aside>

        <VideoPreview material={selected} />
      </div>
    </section>
  );
}
