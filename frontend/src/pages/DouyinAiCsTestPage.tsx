import { useState } from "react";
import {
  ActivityIcon,
  BotIcon,
  DatabaseIcon,
  FilePlusIcon,
  LoaderIcon,
  PlayCircleIcon,
  SearchIcon,
} from "lucide-react";

import {
  createRagDocument,
  getDouyinAiCsHealth,
  getReplySuggestion,
  searchRag,
  trainRag,
  type CreateRagDocumentRequest,
  type ReplySuggestionRequest,
  type SearchRagRequest,
  type TrainRagRequest,
} from "../api/douyinAiCsClient";

const DEFAULT_CONTENT =
  "我们主要做宝马、奔驰、奥迪等精品BBA车型。客户咨询奥迪A6、宝马5系、奔驰E级时，应引导客户留下联系方式，由顾问发送近期车源和价格参考。客户咨询丰田、本田、比亚迪等非主营车型时，应礼貌说明暂不主做该车型。";

type ResultMap = Record<string, unknown>;

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-md border border-slate-200 bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
      {data ? JSON.stringify(data, null, 2) : "暂无返回"}
    </pre>
  );
}

function Field({
  label,
  value,
  onChange,
  textarea = false,
  type = "text",
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  textarea?: boolean;
  type?: string;
}) {
  const baseClass =
    "w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
  return (
    <label className="grid gap-1.5">
      <span className="text-[11px] font-semibold text-slate-500">{label}</span>
      {textarea ? (
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={5}
          className={`${baseClass} resize-y leading-5`}
        />
      ) : (
        <input
          value={value}
          type={type}
          onChange={(event) => onChange(event.target.value)}
          className={baseClass}
        />
      )}
    </label>
  );
}

function ActionButton({
  children,
  loading,
  onClick,
}: {
  children: React.ReactNode;
  loading: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {loading ? <LoaderIcon size={14} className="animate-spin" /> : null}
      {children}
    </button>
  );
}

function Panel({
  title,
  icon,
  children,
  result,
  error,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  result: unknown;
  error?: string | null;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-md bg-blue-50 text-blue-600">{icon}</span>
        <h2 className="text-sm font-bold text-slate-900">{title}</h2>
      </div>
      <div className="grid gap-3">{children}</div>
      {error ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          {error}
        </div>
      ) : null}
      <div className="mt-3">
        <JsonBlock data={result} />
      </div>
    </section>
  );
}

export default function DouyinAiCsTestPage() {
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [results, setResults] = useState<ResultMap>({});
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [documentForm, setDocumentForm] = useState<CreateRagDocumentRequest>({
    tenant_id: "demo_tenant",
    merchant_id: "demo_bba",
    douyin_account_id: 1,
    title: "精品BBA话术",
    category: "sales_script",
    content: DEFAULT_CONTENT,
  });
  const [trainForm, setTrainForm] = useState<TrainRagRequest>({
    tenant_id: "demo_tenant",
    merchant_id: "demo_bba",
    douyin_account_id: 1,
  });
  const [searchForm, setSearchForm] = useState<SearchRagRequest>({
    tenant_id: "demo_tenant",
    merchant_id: "demo_bba",
    douyin_account_id: 1,
    query: "客户问奥迪A6怎么回复",
    top_k: 5,
  });
  const [conversationId, setConversationId] = useState("1");
  const [replyForm, setReplyForm] = useState<ReplySuggestionRequest>({
    tenant_id: "demo_tenant",
    merchant_id: "demo_bba",
    account_id: 1,
    latest_message: "你们有奥迪A6吗？",
  });

  async function runAction<T>(key: string, action: () => Promise<T>) {
    setLoadingKey(key);
    setErrors((current) => ({ ...current, [key]: null }));
    try {
      const data = await action();
      setResults((current) => ({ ...current, [key]: data as unknown }));
    } catch (error) {
      setErrors((current) => ({
        ...current,
        [key]: error instanceof Error ? error.message : "请求失败",
      }));
    } finally {
      setLoadingKey(null);
    }
  }

  const replyResult = results.reply as Partial<{
    reply_text: string;
    manual_required: boolean;
    llm_used: boolean;
    rag_used: boolean;
    auto_send: boolean;
    warnings: string[];
    source_chunks: unknown[];
  }> | null;

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-slate-100">
      <header className="shrink-0 border-b border-slate-200 bg-white px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-base font-bold text-slate-950">抖音AI客服测试</h1>
            <p className="mt-1 text-xs text-slate-500">
              内部调试面板，只验证 9100 RAG 与回复建议链路，不会自动发送私信。
            </p>
          </div>
          <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-[11px] font-semibold text-amber-700">
            auto_send 固定由后端控制为 false
          </span>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-5">
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel
            title="服务状态"
            icon={<ActivityIcon size={16} />}
            result={results.health}
            error={errors.health}
          >
            <ActionButton
              loading={loadingKey === "health"}
              onClick={() => runAction("health", getDouyinAiCsHealth)}
            >
              检查 9100 状态
            </ActionButton>
          </Panel>

          <Panel
            title="创建知识"
            icon={<FilePlusIcon size={16} />}
            result={results.document}
            error={errors.document}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="tenant_id" value={documentForm.tenant_id} onChange={(value) => setDocumentForm({ ...documentForm, tenant_id: value })} />
              <Field label="merchant_id" value={documentForm.merchant_id} onChange={(value) => setDocumentForm({ ...documentForm, merchant_id: value })} />
              <Field
                label="douyin_account_id"
                type="number"
                value={documentForm.douyin_account_id}
                onChange={(value) => setDocumentForm({ ...documentForm, douyin_account_id: Number(value) || 0 })}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="title" value={documentForm.title} onChange={(value) => setDocumentForm({ ...documentForm, title: value })} />
              <Field label="category" value={documentForm.category || ""} onChange={(value) => setDocumentForm({ ...documentForm, category: value })} />
            </div>
            <Field
              label="content"
              value={documentForm.content}
              textarea
              onChange={(value) => setDocumentForm({ ...documentForm, content: value })}
            />
            <ActionButton
              loading={loadingKey === "document"}
              onClick={() => runAction("document", () => createRagDocument(documentForm))}
            >
              创建知识文档
            </ActionButton>
          </Panel>

          <Panel
            title="训练知识库"
            icon={<DatabaseIcon size={16} />}
            result={results.train}
            error={errors.train}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="tenant_id" value={trainForm.tenant_id} onChange={(value) => setTrainForm({ ...trainForm, tenant_id: value })} />
              <Field label="merchant_id" value={trainForm.merchant_id} onChange={(value) => setTrainForm({ ...trainForm, merchant_id: value })} />
              <Field
                label="douyin_account_id"
                type="number"
                value={trainForm.douyin_account_id}
                onChange={(value) => setTrainForm({ ...trainForm, douyin_account_id: Number(value) || 0 })}
              />
            </div>
            <ActionButton
              loading={loadingKey === "train"}
              onClick={() => runAction("train", () => trainRag(trainForm))}
            >
              训练知识库
            </ActionButton>
          </Panel>

          <Panel
            title="搜索知识库"
            icon={<SearchIcon size={16} />}
            result={results.search}
            error={errors.search}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="tenant_id" value={searchForm.tenant_id} onChange={(value) => setSearchForm({ ...searchForm, tenant_id: value })} />
              <Field label="merchant_id" value={searchForm.merchant_id} onChange={(value) => setSearchForm({ ...searchForm, merchant_id: value })} />
              <Field
                label="douyin_account_id"
                type="number"
                value={searchForm.douyin_account_id}
                onChange={(value) => setSearchForm({ ...searchForm, douyin_account_id: Number(value) || 0 })}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-[1fr_120px]">
              <Field label="query" value={searchForm.query} onChange={(value) => setSearchForm({ ...searchForm, query: value })} />
              <Field
                label="top_k"
                type="number"
                value={searchForm.top_k || 5}
                onChange={(value) => setSearchForm({ ...searchForm, top_k: Number(value) || 5 })}
              />
            </div>
            <ActionButton
              loading={loadingKey === "search"}
              onClick={() => runAction("search", () => searchRag(searchForm))}
            >
              搜索知识库
            </ActionButton>
          </Panel>

          <Panel
            title="智能回复建议"
            icon={<BotIcon size={16} />}
            result={results.reply}
            error={errors.reply}
          >
            <div className="grid gap-3 sm:grid-cols-4">
              <Field label="conversation_id" value={conversationId} onChange={setConversationId} />
              <Field label="tenant_id" value={replyForm.tenant_id} onChange={(value) => setReplyForm({ ...replyForm, tenant_id: value })} />
              <Field label="merchant_id" value={replyForm.merchant_id || ""} onChange={(value) => setReplyForm({ ...replyForm, merchant_id: value })} />
              <Field
                label="account_id"
                type="number"
                value={replyForm.account_id}
                onChange={(value) => setReplyForm({ ...replyForm, account_id: Number(value) || 0 })}
              />
            </div>
            <Field
              label="latest_message"
              value={replyForm.latest_message}
              textarea
              onChange={(value) => setReplyForm({ ...replyForm, latest_message: value })}
            />
            <ActionButton
              loading={loadingKey === "reply"}
              onClick={() => runAction("reply", () => getReplySuggestion(conversationId, replyForm))}
            >
              生成回复建议
            </ActionButton>
            {replyResult ? (
              <div className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                <div>
                  <span className="font-semibold text-slate-500">reply_text：</span>
                  {replyResult.reply_text || "-"}
                </div>
                <div className="grid gap-2 sm:grid-cols-4">
                  <span>manual_required：{String(replyResult.manual_required)}</span>
                  <span>llm_used：{String(replyResult.llm_used)}</span>
                  <span>rag_used：{String(replyResult.rag_used)}</span>
                  <span>auto_send：{String(replyResult.auto_send)}</span>
                </div>
                <div>warnings：{(replyResult.warnings || []).join(", ") || "-"}</div>
                <div>source_chunks：{replyResult.source_chunks?.length || 0}</div>
              </div>
            ) : null}
          </Panel>
        </div>
      </div>
    </section>
  );
}
