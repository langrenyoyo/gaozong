import {
  BookOpenIcon,
  BotIcon,
  ChevronLeftIcon,
  ClockIcon,
  CopyIcon,
  MessageSquareIcon,
  MoreVerticalIcon,
  PencilIcon,
  PlusIcon,
  SaveIcon,
  SendIcon,
  Trash2Icon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

interface AgentTemplate {
  id: string;
  name: string;
  createdAt: string;
  avatar: string;
  prompt: string;
  knowledge: string;
}

const initialAgentTemplates: AgentTemplate[] = [
  {
    id: "a1",
    name: "精品代步车",
    createdAt: "2026-01-01 12:12:12",
    avatar: "sales-car",
    prompt: "你是二手车门店的销售客服，需要先确认客户关注的车型、预算和到店意向。",
    knowledge: "库存车辆：宝马3系、奥迪A4L、凯美瑞、雅阁。重点说明车况、价格、检测报告和到店服务。",
  },
  {
    id: "a2",
    name: "金融方案助手",
    createdAt: "2026-01-01 12:10:08",
    avatar: "finance-agent",
    prompt: "围绕首付、月供、分期方案进行说明，语气克制清晰。",
    knowledge: "支持首付比例、贷款年限、月供估算、金融顾问跟进。",
  },
  {
    id: "a3",
    name: "检测报告讲解",
    createdAt: "2026-01-01 11:48:26",
    avatar: "inspection-agent",
    prompt: "重点解释车辆检测报告，避免过度承诺。",
    knowledge: "检测报告包含漆面、结构件、发动机、变速箱、内饰磨损。",
  },
];

interface AgentDraft {
  name: string;
  prompt: string;
  knowledge: string;
}

function formatDateTime(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}:${pad(date.getSeconds())}`;
}

function ChatTestPanel() {
  return (
    <aside className="flex min-h-0 flex-col bg-white">
      <div className="flex items-center justify-between border-b border-[#e4e8f0] px-4 py-4">
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <MessageSquareIcon size={16} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-[#1a1f2e]">聊天测试</h2>
            <p className="mt-1 text-[11px] text-[#8b95a6]">实时验证智能体回复口径</p>
          </div>
        </div>
        <button className="h-8 rounded-lg px-2 text-[11px] font-semibold text-[#64748b] hover:bg-[#f8fafc]">
          清空对话
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <div className="mb-4 flex items-start gap-2.5">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#eff6ff] text-[#2563eb]">
            <MessageSquareIcon size={14} />
          </div>
          <div>
            <div className="mb-1 text-[10px] text-[#8b95a6]">客户</div>
            <div className="rounded-2xl rounded-tl bg-[#f8fafc] px-4 py-2.5 text-xs leading-6 text-[#374151] ring-1 ring-[#e4e8f0]">
              请问这台车最低多少钱？还能不能看车？
            </div>
          </div>
        </div>
        <div className="flex flex-row-reverse items-start gap-2.5">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#1a2035] text-white">
            <BotIcon size={14} />
          </div>
          <div className="max-w-[82%]">
            <div className="mb-1 text-right text-[10px] text-[#8b95a6]">AI</div>
            <div className="rounded-2xl rounded-tr bg-[#1a2035] px-4 py-2.5 text-xs leading-6 text-white">
              您好，这台车我先帮您确认库存和车况。您主要关注价格，还是想先看检测报告？
            </div>
          </div>
        </div>
      </div>
      <div className="border-t border-[#e4e8f0] p-4">
        <div className="grid grid-cols-[1fr_auto] gap-2 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] p-2 focus-within:border-[#2563eb] focus-within:ring-4 focus-within:ring-blue-500/10">
          <textarea className="min-h-16 resize-none bg-transparent px-2 py-1 text-xs outline-none placeholder:text-[#9ca3af]" placeholder="输入消息测试智能体效果..." />
          <button className="mt-auto grid h-8 w-8 place-items-center rounded-lg bg-[#2563eb] text-white">
            <SendIcon size={14} />
          </button>
        </div>
      </div>
    </aside>
  );
}

function AgentEditorPage({
  mode,
  draft,
  onBack,
  onDraftChange,
  onSave,
}: {
  mode: "create" | "edit";
  draft: AgentDraft;
  onBack: () => void;
  onDraftChange: (draft: AgentDraft) => void;
  onSave: () => void;
}) {
  const promptCount = draft.prompt.length;

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <button
            onClick={onBack}
            className="grid h-9 w-9 place-items-center rounded-xl text-[#64748b] hover:bg-[#f4f6f8] hover:text-[#1a1f2e]"
            aria-label="返回智能体列表"
          >
            <ChevronLeftIcon size={18} />
          </button>
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <BotIcon size={22} />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-[15px] font-bold text-[#1a1f2e]">
              {mode === "create" ? "新增商户智能体" : draft.name}
            </h1>
            <p className="mt-1 text-xs text-[#8b95a6]">更新时间：2026-06-01 16:14</p>
          </div>
        </div>
        <button
          onClick={onSave}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
        >
          <SaveIcon size={14} />
          保存
        </button>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(560px,1fr)_360px]">
        <section className="flex min-h-0 flex-col border-r border-[#e4e8f0] bg-white">
          <div className="shrink-0 border-b border-[#e4e8f0] px-5 py-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="inline-flex items-center gap-2 text-xs font-bold text-[#1a1f2e]">
                <BotIcon size={15} className="text-[#2563eb]" />
                智能体基础信息
              </div>
              <span className="text-[11px] text-[#8b95a6]">用于商户侧 AI 客服回复</span>
            </div>
            <label className="grid max-w-[520px] gap-1.5 text-xs">
              <span className="font-semibold text-[#64748b]">智能体名称</span>
              <input
                value={draft.name}
                onChange={(event) => onDraftChange({ ...draft, name: event.target.value })}
                className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-[#374151] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                placeholder="请输入智能体名称"
              />
            </label>
          </div>

          <div className="flex min-h-0 flex-1 flex-col px-5 py-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="inline-flex items-center gap-2 text-xs font-bold text-[#1a1f2e]">
                <MessageSquareIcon size={15} className="text-[#2563eb]" />
                提示词
              </div>
              <span className="text-[11px] text-[#8b95a6]">{promptCount} / 10000</span>
            </div>
            <textarea
              value={draft.prompt}
              onChange={(event) => onDraftChange({ ...draft, prompt: event.target.value })}
              className="min-h-[300px] flex-1 resize-none rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-4 py-3 text-xs leading-6 text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请输入智能体提示词"
            />
          </div>

          <div className="shrink-0 border-t border-[#e4e8f0] px-5 py-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="inline-flex items-center gap-2 text-xs font-bold text-[#1a1f2e]">
                <BookOpenIcon size={15} className="text-[#2563eb]" />
                知识库
              </div>
              <button className="h-8 rounded-lg bg-[#eff6ff] px-3 text-[11px] font-semibold text-[#2563eb]">
                添加知识
              </button>
            </div>
            <textarea
              value={draft.knowledge}
              onChange={(event) => onDraftChange({ ...draft, knowledge: event.target.value })}
              className="min-h-28 w-full resize-none rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 py-2 text-xs leading-6 text-[#374151] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请输入智能体可参考的知识库内容"
            />
          </div>
        </section>

        <ChatTestPanel />
      </div>
    </section>
  );
}

export default function SuperMerchantAgent() {
  const [editorMode, setEditorMode] = useState<"list" | "create" | "edit">("list");
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentTemplate[]>(initialAgentTemplates);
  const [draft, setDraft] = useState<AgentDraft>({
    name: "新建商户智能体",
    prompt: "你是二手车门店的销售客服，需要先确认客户关注的车型、预算和到店意向。",
    knowledge: "",
  });

  const openCreatePage = () => {
    setDraft({
      name: "新建商户智能体",
      prompt: "你是二手车门店的销售客服，需要根据客户问题，用清晰、克制、可信的语气介绍车辆信息，并引导客户补充车型、预算和到店意向。",
      knowledge: "",
    });
    setEditorMode("create");
  };

  const openEditPage = (agent: AgentTemplate) => {
    setDraft({
      name: agent.name,
      prompt: agent.prompt,
      knowledge: agent.knowledge,
    });
    setEditorMode("edit");
  };

  const copyAgent = (agent: AgentTemplate) => {
    const baseName = `${agent.name} 副本`;
    const sameNameCount = agents.filter((item) => item.name === baseName || item.name.startsWith(`${baseName} `)).length;
    const copiedAgent: AgentTemplate = {
      ...agent,
      id: `${agent.id}-copy-${Date.now()}`,
      name: sameNameCount ? `${baseName} ${sameNameCount + 1}` : baseName,
      avatar: `${agent.avatar}-copy-${Date.now()}`,
      createdAt: formatDateTime(new Date()),
    };

    setAgents((current) => {
      const sourceIndex = current.findIndex((item) => item.id === agent.id);
      if (sourceIndex === -1) {
        return [copiedAgent, ...current];
      }
      return [...current.slice(0, sourceIndex + 1), copiedAgent, ...current.slice(sourceIndex + 1)];
    });
    setOpenMenuId(null);
    toast.success("已创建智能体副本");
  };

  if (editorMode !== "list") {
    return (
      <AgentEditorPage
        mode={editorMode}
        draft={draft}
        onBack={() => setEditorMode("list")}
        onDraftChange={setDraft}
        onSave={() => {
          toast.success(editorMode === "create" ? "智能体已保存" : "配置已保存");
          setEditorMode("list");
        }}
      />
    );
  }

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <BotIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">商户智能体</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">维护商户侧 AI 客服的提示词、知识库和调试效果</p>
          </div>
        </div>
        <button
          onClick={openCreatePage}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
        >
          <PlusIcon size={14} />
          添加智能体
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="grid grid-cols-4 gap-4 max-[1440px]:grid-cols-3 max-[1180px]:grid-cols-2">
          {agents.map((agent) => (
            <article
              key={agent.id}
              role="button"
              tabIndex={0}
              onClick={() => openEditPage(agent)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  openEditPage(agent);
                }
              }}
              className="relative flex min-h-[198px] cursor-pointer flex-col rounded-xl border border-[#e4e8f0] bg-white px-5 pb-4 pt-5 text-center shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-smooth hover:border-[#bfdbfe] hover:shadow-[0_14px_32px_rgba(30,83,126,0.10)] focus:outline-none focus:ring-4 focus:ring-blue-500/10"
            >
              <div className="mx-auto grid h-12 w-12 place-items-center overflow-hidden rounded-full bg-[#eff6ff] ring-4 ring-[#f8fafc]">
                <img
                  src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${agent.avatar}&backgroundColor=b6e3f4,c0aede,d1d4f9`}
                  alt={agent.name}
                  className="h-full w-full"
                />
              </div>

              <h2 className="mt-3 truncate text-sm font-bold text-[#1a1f2e]">{agent.name}</h2>
              <p className="mx-auto mt-3 line-clamp-2 min-h-10 max-w-[260px] text-xs leading-5 text-[#8b95a6]">
                {agent.prompt}
              </p>

              <div className="mt-auto flex items-center justify-between gap-3 pt-4 text-xs text-[#8b95a6]">
                <span className="inline-flex min-w-0 items-center gap-1.5">
                  <ClockIcon size={13} />
                  <span className="truncate">{agent.createdAt}</span>
                </span>
                <button
                  onClick={(event) => {
                    event.stopPropagation();
                    setOpenMenuId(openMenuId === agent.id ? null : agent.id);
                  }}
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#f8fafc] text-[#8b95a6] hover:bg-[#eff6ff] hover:text-[#2563eb]"
                  aria-label="打开操作菜单"
                >
                  <MoreVerticalIcon size={16} />
                </button>
              </div>

              {openMenuId === agent.id ? (
                <div className="absolute bottom-10 right-4 z-10 w-[96px] overflow-hidden rounded-lg border border-[#e4e8f0] bg-white py-1 text-left text-xs shadow-[0_18px_48px_rgba(15,23,42,0.16)]">
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      openEditPage(agent);
                      setOpenMenuId(null);
                    }}
                    className="flex h-9 w-full items-center gap-2 px-3 font-semibold text-[#374151] hover:bg-[#f8fafc]"
                  >
                    <PencilIcon size={13} />
                    编辑
                  </button>
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      copyAgent(agent);
                    }}
                    className="flex h-9 w-full items-center gap-2 px-3 font-semibold text-[#374151] hover:bg-[#f8fafc]"
                  >
                    <CopyIcon size={13} />
                    复制
                  </button>
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      setOpenMenuId(null);
                    }}
                    className="flex h-9 w-full items-center gap-2 px-3 font-semibold text-red-600 hover:bg-red-50"
                  >
                    <Trash2Icon size={13} />
                    删除
                  </button>
                </div>
              ) : null}
            </article>
          ))}

        </div>

        <div className="mt-5 flex items-center justify-center gap-3 text-xs text-[#c0c6d0]">
          <span className="h-px w-12 bg-[#e4e8f0]" />
          已经到底了
          <span className="h-px w-12 bg-[#e4e8f0]" />
        </div>
      </div>
    </section>
  );
}
