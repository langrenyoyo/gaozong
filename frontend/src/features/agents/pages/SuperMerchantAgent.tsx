import {
  BotIcon,
  BookOpenIcon,
  ClockIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SaveIcon,
  SendIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  AiAgent,
  AiAgentPayload,
  KnowledgeCategory,
  createAiAgent,
  deleteAiAgent,
  fetchAiAgents,
  getAgentKnowledgeCategories,
  getKnowledgeCategories,
  trainingChat,
  updateAiAgent,
  updateAgentKnowledgeCategories,
} from "../api";
import { formatDateTimeLocal } from "../../../lib/datetime";

interface ChatMessage {
  id: string;
  sender: "ai" | "user";
  content: string;
}

const welcomeMessage: ChatMessage = {
  id: "welcome",
  sender: "ai",
  content: "你好，请输入你想训练的问题，我会按引导留资的思路给出回答。",
};

const emptyDraft: AiAgentPayload = {
  name: "",
  prompt: "",
  knowledge_base_text: "",
};

const BASE_CATEGORY_KEY = "base";

function promptPreview(prompt: string): string {
  return prompt.trim() || "暂无提示词";
}

function agentAvatar(agent: AiAgent) {
  return agent.avatar_url || `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(agent.avatar_seed)}`;
}

function canSelectCategory(category: KnowledgeCategory): boolean {
  return category.scope_type === "merchant" && category.category_key !== BASE_CATEGORY_KEY && category.is_active !== false && category.status !== "disabled";
}

function filterMerchantCategoryKeys(keys: string[], categories: KnowledgeCategory[]): string[] {
  const selectableKeys = new Set(categories.filter(canSelectCategory).map((category) => category.category_key));
  const seen = new Set<string>();
  return keys.filter((key) => {
    if (!selectableKeys.has(key) || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function AgentEditor({
  agent,
  saving,
  onClose,
  onSave,
}: {
  agent: AiAgent | null;
  saving: boolean;
  onClose: () => void;
  onSave: (payload: AiAgentPayload, categoryKeys: string[] | null) => void;
}) {
  const [draft, setDraft] = useState<AiAgentPayload>(emptyDraft);
  const [categories, setCategories] = useState<KnowledgeCategory[]>([]);
  const [selectedCategoryKeys, setSelectedCategoryKeys] = useState<string[]>([]);
  const [categoryLoading, setCategoryLoading] = useState(false);
  const [categoryLoadFailed, setCategoryLoadFailed] = useState(false);
  const [bindingLoadFailed, setBindingLoadFailed] = useState(false);
  const nameInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setDraft(
      agent
        ? {
            name: agent.name,
            prompt: agent.prompt,
            knowledge_base_text: agent.knowledge_base_text,
            avatar_url: agent.avatar_url,
          }
        : emptyDraft,
    );
  }, [agent]);

  useEffect(() => {
    window.setTimeout(() => nameInputRef.current?.focus(), 0);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadCategoryOptions() {
      setCategoryLoading(true);
      setCategoryLoadFailed(false);
      setBindingLoadFailed(false);
      setCategories([]);
      setSelectedCategoryKeys([]);

      try {
        const items = await getKnowledgeCategories();
        if (cancelled) return;
        setCategories(items);

        if (!agent) return;

        try {
          const binding = await getAgentKnowledgeCategories(agent.agent_id);
          if (cancelled) return;
          setSelectedCategoryKeys(filterMerchantCategoryKeys(binding.category_keys, items));
        } catch (error) {
          if (cancelled) return;
          setBindingLoadFailed(true);
          toast.warning("知识分类绑定加载失败，本次保存不会更新分类");
        }
      } catch (error) {
        if (cancelled) return;
        setCategoryLoadFailed(true);
        toast.warning("知识分类加载失败，可先保存智能体基础信息");
      } finally {
        if (!cancelled) {
          setCategoryLoading(false);
        }
      }
    }

    void loadCategoryOptions();

    return () => {
      cancelled = true;
    };
  }, [agent]);

  const selectableCategories = useMemo(() => categories.filter(canSelectCategory), [categories]);

  const toggleCategory = (categoryKey: string) => {
    setSelectedCategoryKeys((current) =>
      current.includes(categoryKey) ? current.filter((key) => key !== categoryKey) : [...current, categoryKey],
    );
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.name.trim()) {
      nameInputRef.current?.focus();
      toast.error("请填写智能体名称");
      return;
    }
    onSave({
      ...draft,
      name: draft.name.trim(),
      prompt: draft.prompt || "",
      knowledge_base_text: draft.knowledge_base_text || "",
    }, bindingLoadFailed || categoryLoadFailed ? null : filterMerchantCategoryKeys(selectedCategoryKeys, categories));
  };

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-slate-950/36 p-6 backdrop-blur-sm">
      <form
        onSubmit={submit}
        className="grid max-h-[88vh] w-full max-w-[760px] grid-rows-[auto_1fr_auto] overflow-hidden rounded-2xl border border-[#dfe5ee] bg-white shadow-[0_24px_90px_rgba(15,23,42,0.24)]"
      >
        <header className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
              <BotIcon size={21} />
            </div>
            <div>
              <h2 className="text-base font-bold text-[#1a1f2e]">{agent ? "编辑AI小高智能体" : "创建AI小高智能体"}</h2>
              <p className="mt-1 text-xs text-[#8b95a6]">配置名称、提示词和普通文本知识库。</p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg text-[#64748b] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </header>

        <div className="min-h-0 space-y-4 overflow-y-auto px-5 py-5">
          <label className="grid gap-1.5 text-xs">
            <span className="font-semibold text-[#475569]">智能体名称</span>
            <input
              ref={nameInputRef}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              className="h-10 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="例如：精品车接待顾问"
            />
          </label>

          <label className="grid gap-1.5 text-xs">
            <span className="font-semibold text-[#475569]">智能体提示词</span>
            <textarea
              value={draft.prompt}
              onChange={(event) => setDraft({ ...draft, prompt: event.target.value })}
              className="min-h-[150px] resize-none rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 py-3 text-sm leading-6 text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="描述智能体身份、语气、接待策略和留资引导方式。"
            />
          </label>

          <label className="grid gap-1.5 text-xs">
            <span className="font-semibold text-[#475569]">智能体知识库</span>
            <textarea
              value={draft.knowledge_base_text}
              onChange={(event) => setDraft({ ...draft, knowledge_base_text: event.target.value })}
              className="min-h-[150px] resize-none rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 py-3 text-sm leading-6 text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="录入门店车型、服务、报价说明、检测报告说明等普通文本。"
            />
          </label>

          <section className="grid gap-2 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] p-3 text-xs">
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold text-[#475569]">知识分类</span>
              {categoryLoading ? (
                <span className="inline-flex items-center gap-1 text-[#64748b]">
                  <RefreshCwIcon size={12} className="animate-spin" />
                  加载中
                </span>
              ) : null}
            </div>

            <label className="flex min-h-9 items-center justify-between rounded-lg border border-[#dbe3ee] bg-white px-3 py-2 text-[#475569]">
              <span className="font-medium">基础知识（默认启用）</span>
              <input type="checkbox" checked disabled className="h-4 w-4 accent-[#2563eb]" />
            </label>

            {categoryLoadFailed ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-700">知识分类加载失败，本次可继续保存基础信息。</div>
            ) : bindingLoadFailed ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-700">分类绑定加载失败，本次保存不会更新分类。</div>
            ) : selectableCategories.length > 0 ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {selectableCategories.map((category) => (
                  <label
                    key={category.category_key}
                    className="flex min-h-9 items-center justify-between gap-2 rounded-lg border border-[#dbe3ee] bg-white px-3 py-2 text-[#475569] hover:border-[#bfdbfe]"
                  >
                    <span className="min-w-0 truncate font-medium">{category.name || category.category_key}</span>
                    <input
                      type="checkbox"
                      checked={selectedCategoryKeys.includes(category.category_key)}
                      onChange={() => toggleCategory(category.category_key)}
                      className="h-4 w-4 shrink-0 accent-[#2563eb]"
                    />
                  </label>
                ))}
              </div>
            ) : (
              <div className="rounded-lg border border-[#dbe3ee] bg-white px-3 py-2 text-[#8b95a6]">暂无可选商户分类。</div>
            )}
          </section>
        </div>

        <footer className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button type="button" onClick={onClose} className="h-9 rounded-xl border border-[#dfe5ee] px-4 text-xs font-semibold text-[#475569]">
            取消
          </button>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)] disabled:opacity-60"
          >
            {saving ? <RefreshCwIcon size={14} className="animate-spin" /> : <SaveIcon size={14} />}
            保存
          </button>
        </footer>
      </form>
    </div>
  );
}

function TrainingPanel({ agent }: { agent: AiAgent | null }) {
  const [messages, setMessages] = useState<ChatMessage[]>([welcomeMessage]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setMessages([welcomeMessage]);
    setInput("");
  }, [agent?.agent_id]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!agent) return;
    const text = input.trim();
    if (!text) {
      inputRef.current?.focus();
      return;
    }

    setMessages((current) => [...current, { id: `user-${Date.now()}`, sender: "user", content: text }]);
    setInput("");
    setSending(true);
    try {
      const result = await trainingChat(agent.agent_id, text);
      setMessages((current) => [...current, { id: `ai-${Date.now()}`, sender: "ai", content: result.reply_text }]);
      if (result.warnings?.length) {
        toast.warning(result.warnings.join("；"));
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "训练预览失败");
      setMessages((current) => [...current, { id: `ai-error-${Date.now()}`, sender: "ai", content: "训练预览失败，请稍后重试。" }]);
    } finally {
      setSending(false);
    }
  };

  return (
    <aside className="flex min-h-0 flex-col border-l border-[#e4e8f0] bg-white">
      <div className="border-b border-[#e4e8f0] px-4 py-4">
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <BookOpenIcon size={17} />
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-bold text-[#1a1f2e]">统一知识库训练预览</h2>
            <p className="mt-1 truncate text-[11px] text-[#8b95a6]">{agent ? agent.name : "请选择一个智能体"}</p>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-[#f8fafc] px-4 py-4">
        {messages.map((message) => (
          <div key={message.id} className={`flex ${message.sender === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[86%] rounded-2xl px-4 py-2.5 text-xs leading-6 ${
                message.sender === "user"
                  ? "rounded-br-md bg-[#2563eb] text-white"
                  : "rounded-bl-md bg-white text-[#374151] ring-1 ring-[#e4e8f0]"
              }`}
            >
              {message.content}
            </div>
          </div>
        ))}
      </div>

      <form onSubmit={submit} className="border-t border-[#e4e8f0] p-4">
        <div className="grid grid-cols-[1fr_auto] gap-2 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] p-2 focus-within:border-[#2563eb] focus-within:ring-4 focus-within:ring-blue-500/10">
          <input
            ref={inputRef}
            value={input}
            disabled={!agent || sending}
            onChange={(event) => setInput(event.target.value)}
            className="h-9 bg-transparent px-2 text-sm text-[#1a1f2e] outline-none placeholder:text-[#94a3b8] disabled:cursor-not-allowed"
            placeholder={agent ? "输入训练问题" : "先选择智能体"}
          />
          <button
            type="submit"
            disabled={!agent || sending}
            className="grid h-9 w-9 place-items-center rounded-lg bg-[#2563eb] text-white disabled:opacity-50"
            aria-label="发送训练问题"
          >
            {sending ? <RefreshCwIcon size={15} className="animate-spin" /> : <SendIcon size={15} />}
          </button>
        </div>
      </form>
    </aside>
  );
}

export default function SuperMerchantAgent() {
  const [agents, setAgents] = useState<AiAgent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editorAgent, setEditorAgent] = useState<AiAgent | null | undefined>(undefined);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.agent_id === selectedAgentId) || agents[0] || null,
    [agents, selectedAgentId],
  );

  const loadAgents = async () => {
    setLoading(true);
    try {
      const items = await fetchAiAgents();
      setAgents(items);
      setSelectedAgentId((current) => current && items.some((item) => item.agent_id === current) ? current : items[0]?.agent_id || null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "AI小高智能体加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAgents();
  }, []);

  const saveAgent = async (payload: AiAgentPayload, categoryKeys: string[] | null) => {
    setSaving(true);
    try {
      const saved = editorAgent ? await updateAiAgent(editorAgent.agent_id, payload) : await createAiAgent(payload);
      let categorySaveFailed = false;

      if (categoryKeys !== null) {
        try {
          await updateAgentKnowledgeCategories(saved.agent_id, categoryKeys);
        } catch (error) {
          categorySaveFailed = true;
          toast.warning(
            editorAgent
              ? "智能体已更新，但知识分类保存失败，请稍后重试"
              : "智能体已创建，但知识分类保存失败，请稍后重试",
          );
        }
      }

      if (!categorySaveFailed) {
        toast.success(editorAgent ? "智能体已更新" : "智能体已创建");
      }
      setEditorAgent(undefined);
      await loadAgents();
      setSelectedAgentId(saved.agent_id);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "智能体保存失败");
    } finally {
      setSaving(false);
    }
  };

  const removeAgent = async (agent: AiAgent) => {
    if (!window.confirm(`确认删除“${agent.name}”？`)) return;
    try {
      await deleteAiAgent(agent.agent_id);
      toast.success("智能体已删除");
      await loadAgents();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "智能体删除失败");
    }
  };

  return (
    <section className="grid h-full min-h-0 grid-cols-[minmax(620px,1fr)_420px] overflow-hidden bg-[#f3f6fa]">
      <div className="flex min-h-0 flex-col">
        <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
              <BotIcon size={22} />
            </div>
            <div>
              <h1 className="text-[15px] font-bold text-[#1a1f2e]">AI小高智能体</h1>
              <p className="mt-1 text-xs text-[#8b95a6]">管理智能体名称、提示词和统一知识库训练预览。</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadAgents}
              className="grid h-9 w-9 place-items-center rounded-xl border border-[#dfe5ee] bg-white text-[#64748b] hover:bg-[#f8fafc]"
              aria-label="刷新智能体列表"
            >
              <RefreshCwIcon size={15} />
            </button>
            <button
              onClick={() => setEditorAgent(null)}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
            >
              <PlusIcon size={14} />
              创建智能体
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="grid h-full place-items-center text-sm text-[#64748b]">正在加载AI小高智能体...</div>
          ) : agents.length === 0 ? (
            <div className="grid h-full place-items-center">
              <div className="max-w-[360px] text-center">
                <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-[#eff6ff] text-[#2563eb]">
                  <BotIcon size={28} />
                </div>
                <h2 className="mt-4 text-base font-bold text-[#1a1f2e]">暂无智能体</h2>
                <p className="mt-2 text-sm leading-6 text-[#8b95a6]">创建第一个AI小高智能体后，可以维护提示词和知识库并进行训练预览。</p>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-4 max-[1280px]:grid-cols-2">
              {agents.map((agent) => (
                <article
                  key={agent.agent_id}
                  onClick={() => setSelectedAgentId(agent.agent_id)}
                  className={`flex min-h-[218px] cursor-pointer flex-col rounded-xl border bg-white px-5 py-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-smooth ${
                    selectedAgent?.agent_id === agent.agent_id
                      ? "border-[#2563eb] ring-4 ring-blue-500/10"
                      : "border-[#e4e8f0] hover:border-[#bfdbfe] hover:shadow-[0_14px_32px_rgba(30,83,126,0.10)]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <img src={agentAvatar(agent)} alt={agent.name} className="h-12 w-12 rounded-full bg-[#eff6ff] ring-4 ring-[#f8fafc]" />
                    <span className="rounded-full bg-[#f1f5f9] px-2.5 py-1 text-[11px] font-semibold text-[#64748b]">
                      {agent.status === "active" ? "启用" : "停用"}
                    </span>
                  </div>
                  <h2 className="mt-4 truncate text-sm font-bold text-[#1a1f2e]">{agent.name}</h2>
                  <p className="mt-3 line-clamp-2 min-h-10 text-xs leading-5 text-[#64748b]">{promptPreview(agent.prompt)}</p>
                  <div className="mt-auto flex items-center justify-between gap-3 pt-4">
                    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-[#94a3b8]">
                      <ClockIcon size={13} />
                      <span className="truncate">{formatDateTimeLocal(agent.created_at || null)}</span>
                    </span>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditorAgent(agent);
                        }}
                        className="grid h-8 w-8 place-items-center rounded-lg text-[#64748b] hover:bg-[#eff6ff] hover:text-[#2563eb]"
                        aria-label="编辑智能体"
                      >
                        <PencilIcon size={14} />
                      </button>
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          void removeAgent(agent);
                        }}
                        className="grid h-8 w-8 place-items-center rounded-lg text-[#64748b] hover:bg-red-50 hover:text-red-600"
                        aria-label="删除智能体"
                      >
                        <Trash2Icon size={14} />
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>

      <TrainingPanel agent={selectedAgent} />

      {editorAgent !== undefined ? (
        <AgentEditor
          agent={editorAgent}
          saving={saving}
          onClose={() => setEditorAgent(undefined)}
          onSave={(payload, categoryKeys) => void saveAgent(payload, categoryKeys)}
        />
      ) : null}
    </section>
  );
}
