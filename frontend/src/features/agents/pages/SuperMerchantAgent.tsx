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
  previewAiAgent,
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
  content: "你好，请输入客户问题，我会按当前智能体配置预览回复。",
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
  return (category.scope_type === "merchant" || category.category_key === BASE_CATEGORY_KEY) && category.is_active !== false && category.status !== "disabled";
}

function filterSelectableCategoryKeys(keys: string[], categories: KnowledgeCategory[]): string[] {
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
    setCategories([]);
    setSelectedCategoryKeys([]);
    setCategoryLoading(false);
    setCategoryLoadFailed(false);
    setBindingLoadFailed(false);

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

        if (!agent) {
          setSelectedCategoryKeys([]);
          return;
        }

        try {
          const binding = await getAgentKnowledgeCategories(agent.agent_id);
          if (cancelled) return;
          setSelectedCategoryKeys(filterSelectableCategoryKeys(binding.category_keys, items));
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
    const categoryKeys = categoryLoadFailed || bindingLoadFailed ? null : selectedCategoryKeys;
    onSave({
      ...draft,
      name: draft.name.trim(),
      prompt: draft.prompt || "",
      knowledge_base_text: draft.knowledge_base_text || "",
    }, categoryKeys);
  };

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="agent-editor-title" className="fixed inset-0 z-30 grid place-items-center bg-slate-950/36 p-6 backdrop-blur-sm">
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
              <h2 id="agent-editor-title" className="text-base font-bold text-[#1a1f2e]">{agent ? "编辑AI小高智能体" : "创建AI小高智能体"}</h2>
              <p className="mt-1 text-xs text-[#8b95a6]">配置名称、提示词、知识参考提示词和 AI 客服知识范围。</p>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭智能体编辑弹窗" className="grid h-8 w-8 place-items-center rounded-lg text-[#64748b] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </header>

        <div className="min-h-0 overflow-y-auto px-5 py-5">
          <div className="space-y-4">
          <label className="grid gap-1.5 text-xs">
            <span className="font-semibold text-[#475569]">智能体名称</span>
            <input
              ref={nameInputRef}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              className="h-10 rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 text-sm text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请输入智能体名称，例如精品 BBA 销售顾问"
            />
          </label>

          <label className="grid gap-1.5 text-xs">
            <span className="font-semibold text-[#475569]">智能体提示词</span>
            <textarea
              value={draft.prompt}
              onChange={(event) => setDraft({ ...draft, prompt: event.target.value })}
              className="min-h-[150px] resize-none rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 py-3 text-sm leading-6 text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请填写智能体的人设、语气、角色定位和销售风格，例如你是一名专业二手车销售顾问，语气热情、专业、不过度承诺。"
            />
          </label>

          <label className="grid gap-1.5 text-xs">
            <span className="font-semibold text-[#475569]">知识参考提示词</span>
            <textarea
              value={draft.knowledge_base_text}
              onChange={(event) => setDraft({ ...draft, knowledge_base_text: event.target.value })}
              className="min-h-[120px] resize-none rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 py-3 text-sm leading-6 text-[#1a1f2e] outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请填写该智能体在使用知识和组织答案时需要遵循的规则，例如优先回答车型、价格、车况、门店位置；客户有购车意向时，引导留下手机号或微信；不确定的信息不要编造。"
            />
          </label>

          <section className="rounded-xl border border-[#dfe5ee] bg-[#f8fafc] px-3 py-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-xs font-semibold text-[#475569]">AI 客服知识范围</span>
              {categoryLoading ? <span className="text-[11px] text-[#8b95a6]">加载中...</span> : null}
            </div>
            <p className="mb-3 text-[11px] leading-5 text-[#8b95a6]">
              小高知识库由管理员统一维护。关闭后，AI 将只按人设提示词和当前对话生成回复，不检索知识库。
            </p>
            <div className="flex flex-wrap gap-2">
              {selectableCategories.map((category) => (
                <label
                  key={category.category_key}
                  className="inline-flex h-8 items-center gap-2 rounded-lg border border-[#dfe5ee] bg-white px-3 text-xs font-semibold text-[#475569]"
                >
                  <input
                    type="checkbox"
                    checked={selectedCategoryKeys.includes(category.category_key)}
                    onChange={() => toggleCategory(category.category_key)}
                    className="h-4 w-4 accent-[#2563eb]"
                  />
                  {category.category_key === BASE_CATEGORY_KEY ? "参考小高知识库" : category.name || category.category_key}
                </label>
              ))}
            </div>
            <p className="mt-2 text-[11px] leading-5 text-[#8b95a6]">选择 AI 回复时可参考的知识分类，不会修改知识库内容。</p>
            {!categoryLoadFailed && !bindingLoadFailed && selectedCategoryKeys.length === 0 ? (
              <p className="mt-2 text-[11px] leading-5 text-amber-600">已关闭知识库参考：AI 仍会生成回复，但不会引用小高知识库内容。</p>
            ) : null}
            {categoryLoadFailed || bindingLoadFailed ? (
              <p className="mt-2 text-[11px] text-amber-600">知识范围加载不完整，本次保存会保留已加载的选择。</p>
            ) : null}
          </section>
          </div>
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
  const [categoryKeys, setCategoryKeys] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setMessages([welcomeMessage]);
    setInput("");
    setCategoryKeys([]);
    let cancelled = false;
    async function loadBinding() {
      if (!agent) return;
      try {
        const binding = await getAgentKnowledgeCategories(agent.agent_id);
        if (!cancelled) {
          setCategoryKeys(binding.category_keys || []);
        }
      } catch (error) {
        if (!cancelled) {
          toast.warning("知识范围加载失败，本次预览不参考知识分类");
        }
      }
    }
    void loadBinding();
    return () => {
      cancelled = true;
    };
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
      const result = await previewAiAgent({
        agent_id: agent.agent_id,
        name: agent.name,
        persona_prompt: agent.prompt || "",
        knowledge_prompt: agent.knowledge_base_text || "",
        knowledge_category_keys: categoryKeys,
        message: text,
      });
      setMessages((current) => [...current, { id: `ai-${Date.now()}`, sender: "ai", content: result.reply_text || "暂无回复" }]);
      if (result.warnings?.length) {
        toast.warning(result.warnings.join("；"));
      }
      if (result.error) {
        toast.error(result.error);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "回复预览失败");
      setMessages((current) => [...current, { id: `ai-error-${Date.now()}`, sender: "ai", content: "回复预览失败，请稍后重试。" }]);
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
            <h2 className="truncate text-sm font-bold text-[#1a1f2e]">回复效果预览</h2>
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
            aria-label="输入预览问题"
            className="h-9 bg-transparent px-2 text-sm text-[#1a1f2e] outline-none placeholder:text-[#94a3b8] disabled:cursor-not-allowed"
            placeholder={agent ? "输入客户问题" : "先选择智能体"}
          />
          <button
            type="submit"
            disabled={!agent || sending}
            className="grid h-9 w-9 place-items-center rounded-lg bg-[#2563eb] text-white disabled:opacity-50"
            aria-label="发送预览问题"
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
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [editorAgent, setEditorAgent] = useState<AiAgent | null | undefined>(undefined);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.agent_id === selectedAgentId) || agents[0] || null,
    [agents, selectedAgentId],
  );

  const loadAgents = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const items = await fetchAiAgents();
      setAgents(items);
      setSelectedAgentId((current) => current && items.some((item) => item.agent_id === current) ? current : items[0]?.agent_id || null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "AI小高智能体加载失败");
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
              <p className="mt-1 text-xs text-[#8b95a6]">配置智能体名称、提示词和 AI 客服知识范围。</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadAgents}
              disabled={loading}
              className="grid h-9 w-9 place-items-center rounded-xl border border-[#dfe5ee] bg-white text-[#64748b] hover:bg-[#f8fafc] disabled:opacity-60"
              aria-label="刷新智能体列表"
            >
              <RefreshCwIcon size={15} className={loading ? "animate-spin" : ""} />
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
          {loading && agents.length === 0 ? (
            <div className="grid h-full place-items-center text-sm text-[#64748b]">
              <span className="inline-flex items-center gap-2"><RefreshCwIcon size={16} className="animate-spin" /> 正在加载AI小高智能体...</span>
            </div>
          ) : loadError && agents.length === 0 ? (
            <div className="grid h-full place-items-center">
              <div className="max-w-[360px] text-center">
                <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-red-50 text-red-500">
                  <BotIcon size={28} />
                </div>
                <h2 className="mt-4 text-base font-bold text-[#1a1f2e]">加载失败</h2>
                <p className="mt-2 text-sm leading-6 text-[#8b95a6]">{loadError}</p>
                <button onClick={loadAgents} className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white">
                  <RefreshCwIcon size={14} /> 重试
                </button>
              </div>
            </div>
          ) : agents.length === 0 ? (
            <div className="grid h-full place-items-center">
              <div className="max-w-[360px] text-center">
                <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-[#eff6ff] text-[#2563eb]">
                  <BotIcon size={28} />
                </div>
                <h2 className="mt-4 text-base font-bold text-[#1a1f2e]">暂无智能体</h2>
                <p className="mt-2 text-sm leading-6 text-[#8b95a6]">创建第一个AI小高智能体后，可以配置提示词和回复知识范围。</p>
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
                    <span
                      className={`mt-1 h-2.5 w-2.5 rounded-full ${
                        agent.status === "active" ? "bg-emerald-500" : "bg-slate-300"
                      }`}
                      title={agent.status === "active" ? "当前可用" : "当前不可用"}
                    />
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
