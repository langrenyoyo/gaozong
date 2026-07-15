import { useCallback, useEffect, useState } from "react";
import { Loader2Icon } from "lucide-react";
import { toast } from "sonner";
import {
  getReturnVisitPrompts,
  updateReturnVisitPrompt,
  listReturnVisitRuns,
  getReturnVisitRunsStats,
  getReturnVisitRun,
  type ReturnVisitPrompt,
  type ReturnVisitRunListItem,
  type ReturnVisitRunDetail,
  type ReturnVisitRunsStats,
} from "../api/adminReturnVisits";

// Phase 9 Task 9：超管回访配置与只读运行页。
// 两个 tab：提示词配置（可编辑）/ 运行记录（只读）。
// 不提供任何发送类操作命令——本阶段只做配置留痕与审计只读查看。

// ---- 稳定中文映射（未知值回显原码）----

const STATUS_LABELS: Record<string, string> = {
  pending_judgement: "待判定",
  processing: "处理中",
  send_authorized: "已授权待发",
  sent: "已发送",
  send_unknown: "发送未知",
  failed: "失败",
  blocked: "已阻断",
  confidence_low: "置信度低",
  prompt_disabled: "提示词禁用",
  rate_limited: "限频",
  not_needed: "无需回访",
};

const SCENE_LABELS: Record<string, string> = {
  retain_contact_conversion: "留资转化",
  finance_plan_followup: "金融方案跟进",
  silent_customer_wakeup: "沉默客户唤醒",
};

const SOURCE_LABELS: Record<string, string> = {
  llm: "大模型",
  keyword_fallback: "关键词兜底",
  precheck: "预检",
};

const RISK_LABELS: Record<string, string> = {
  prompt_injection: "提示词注入",
  sensitive_info: "敏感信息",
  off_topic: "偏题",
  duplicate: "重复",
  policy_violation: "违规",
  model_refusal: "模型拒答",
};

function labelOf(map: Record<string, string>, value: string | null | undefined): string {
  if (!value) return "-";
  return map[value] || value;
}

function resolveError(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "请求失败，请稍后再试";
}

// ---- 通用展示组件 ----

function StatusPill({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex rounded-md px-2 py-0.5 text-[11px] font-semibold ${
        active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"
      }`}
    >
      {children}
    </span>
  );
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block">
      <div className="text-xs font-semibold text-[#475467]">{label}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-[#8b95a6]">{hint}</div> : null}
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

// 右侧滑入抽屉（自写轻量 panel，避免引入手势库复杂度）
function SlidePanel({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="return-visit-panel-title" className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="关闭"
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      <aside className="relative flex h-full w-full max-w-[480px] flex-col bg-white shadow-[ -8px_0_30px_rgba(15,23,42,0.12)]">
        <header className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <h3 id="return-visit-panel-title" className="text-sm font-bold text-[#1a1f2e]">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-xs font-semibold text-[#8b95a6] hover:bg-slate-100"
          >
            关闭
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <footer className="border-t border-[#e4e8f0] px-5 py-3">{footer}</footer> : null}
      </aside>
    </div>
  );
}

// ---- 主页面 ----

type TabKey = "prompts" | "runs";

const THRESHOLD_MIN = 0.5;
const THRESHOLD_MAX = 1.0;
const TEXT_LIMIT = 500;

export default function AdminReturnVisitsPage() {
  const [tab, setTab] = useState<TabKey>("prompts");
  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="border-b border-[#e4e8f0] bg-white px-6 py-4">
        <h1 className="text-base font-bold text-[#1a1f2e]">回访配置与运行记录</h1>
        <p className="mt-1 text-[11px] text-[#8b95a6]">
          超管维护回访话术模板与置信阈值；运行记录为只读审计视图。
        </p>
        <div className="mt-3 inline-flex rounded-lg border border-[#e4e8f0] bg-[#f8fafc] p-0.5 text-xs font-semibold">
          {(
            [
              { key: "prompts" as const, label: "提示词配置" },
              { key: "runs" as const, label: "运行记录" },
            ]
          ).map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setTab(item.key)}
              className={`rounded-md px-4 py-1.5 transition ${
                tab === item.key ? "bg-white text-[#2563eb] shadow-sm" : "text-[#8b95a6] hover:text-[#475467]"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {tab === "prompts" ? <PromptsTab /> : <RunsTab />}
      </div>
    </section>
  );
}

// ---- 提示词配置 tab ----

interface PromptFormState {
  template_text: string;
  fallback_message: string;
  confidence_threshold: string;
  enabled: boolean;
  reason: string;
}

function emptyFormFromPrompt(prompt: ReturnVisitPrompt): PromptFormState {
  return {
    template_text: prompt.template_text || "",
    fallback_message: prompt.fallback_message || "",
    confidence_threshold: String(prompt.confidence_threshold ?? THRESHOLD_MIN),
    enabled: !!prompt.enabled,
    reason: "",
  };
}

function PromptsTab() {
  const [prompts, setPrompts] = useState<ReturnVisitPrompt[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ReturnVisitPrompt | null>(null);
  const [form, setForm] = useState<PromptFormState | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await getReturnVisitPrompts();
      setPrompts(resp.data.items);
    } catch (err) {
      setError(resolveError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openEdit = (prompt: ReturnVisitPrompt) => {
    setEditing(prompt);
    setForm(emptyFormFromPrompt(prompt));
    setFormError(null);
  };

  const closeEdit = () => {
    setEditing(null);
    setForm(null);
    setFormError(null);
  };

  const submit = async () => {
    if (!editing || !form) return;
    const template = form.template_text.trim();
    const fallback = form.fallback_message.trim();
    const reason = form.reason.trim();
    const threshold = Number(form.confidence_threshold);

    if (!template || template.length > TEXT_LIMIT) {
      setFormError("模板话术必填，且不超过 500 字");
      return;
    }
    if (!fallback || fallback.length > TEXT_LIMIT) {
      setFormError("兜底文案必填，且不超过 500 字");
      return;
    }
    if (!Number.isFinite(threshold) || threshold < THRESHOLD_MIN || threshold > THRESHOLD_MAX) {
      setFormError(`置信阈值必须在 ${THRESHOLD_MIN} ~ ${THRESHOLD_MAX} 之间`);
      return;
    }
    if (!reason) {
      setFormError("变更原因必填");
      return;
    }

    setSaving(true);
    setFormError(null);
    try {
      const resp = await updateReturnVisitPrompt(editing.prompt_key, {
        template_text: template,
        fallback_message: fallback,
        confidence_threshold: threshold,
        enabled: form.enabled,
        reason,
      });
      setPrompts((prev) => prev.map((p) => (p.prompt_key === resp.data.prompt_key ? resp.data : p)));
      toast.success("提示词已保存");
      closeEdit();
    } catch (err) {
      setFormError(resolveError(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading && prompts.length === 0) {
    return <div className="flex items-center gap-2 text-xs text-[#8b95a6]"><Loader2Icon size={14} className="animate-spin" /> 加载中…</div>;
  }
  if (!loading && prompts.length === 0 && !error) {
    return <div className="text-xs text-[#8b95a6]">暂无提示词配置</div>;
  }
  if (error) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
        {error}
        <button type="button" onClick={load} className="ml-3 underline">
          重新加载
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-hidden rounded-xl border border-[#e4e8f0] bg-white">
        <table className="w-full text-left text-xs">
          <thead className="bg-[#f8fafc] text-[11px] font-semibold text-[#8b95a6]">
            <tr>
              <th className="px-4 py-2.5">场景</th>
              <th className="px-4 py-2.5">状态</th>
              <th className="px-4 py-2.5">模板话术</th>
              <th className="px-4 py-2.5">兜底文案</th>
              <th className="px-4 py-2.5">置信阈值</th>
              <th className="px-4 py-2.5 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {prompts.map((p) => (
              <tr key={p.prompt_key} className="border-t border-[#eef1f6] align-top">
                <td className="px-4 py-3 font-semibold text-[#1a1f2e]">
                  {labelOf(SCENE_LABELS, p.prompt_key)}
                  <div className="mt-0.5 text-[10px] font-normal text-[#8b95a6]">{p.prompt_key}</div>
                </td>
                <td className="px-4 py-3">
                  <StatusPill active={p.enabled}>{p.enabled ? "启用" : "停用"}</StatusPill>
                </td>
                <td className="max-w-[280px] px-4 py-3 text-[#475467]">
                  <div className="break-words whitespace-pre-wrap line-clamp-3">{p.template_text}</div>
                </td>
                <td className="max-w-[240px] px-4 py-3 text-[#475467]">
                  <div className="break-words whitespace-pre-wrap line-clamp-2">{p.fallback_message}</div>
                </td>
                <td className="px-4 py-3 text-[#475467]">{p.confidence_threshold?.toFixed(2) ?? "-"}</td>
                <td className="px-4 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => openEdit(p)}
                    className="rounded-md border border-[#e4e8f0] px-3 py-1 text-xs font-semibold text-[#2563eb] hover:bg-[#eff4ff]"
                  >
                    编辑
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SlidePanel
        open={!!editing && !!form}
        title={editing ? `编辑 · ${labelOf(SCENE_LABELS, editing.prompt_key)}` : ""}
        onClose={closeEdit}
        footer={
          form ? (
            <div className="flex items-center justify-between gap-3">
              <span className="text-[11px] text-rose-600">{formError}</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={closeEdit}
                  className="rounded-md border border-[#e4e8f0] px-4 py-1.5 text-xs font-semibold text-[#475467] hover:bg-slate-50"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={submit}
                  disabled={saving}
                  className="rounded-md bg-[#2563eb] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#1d4ed8] disabled:opacity-60"
                >
                  {saving ? "保存中…" : "保存"}
                </button>
              </div>
            </div>
          ) : null
        }
      >
        {form ? (
          <div className="space-y-4">
            <Field label="模板话术" hint={`1 ~ ${TEXT_LIMIT} 字，保存管理员原文（命中违禁词仅告警不替换）`}>
              <textarea
                value={form.template_text}
                onChange={(e) => setForm({ ...form, template_text: e.target.value })}
                maxLength={TEXT_LIMIT}
                rows={4}
                className="w-full resize-y rounded-md border border-[#e4e8f0] px-3 py-2 text-xs text-[#1a1f2e] focus:border-[#2563eb] focus:outline-none"
              />
              <div className="mt-1 text-right text-[10px] text-[#8b95a6]">
                {form.template_text.length}/{TEXT_LIMIT}
              </div>
            </Field>
            <Field label="兜底文案" hint={`1 ~ ${TEXT_LIMIT} 字`}>
              <textarea
                value={form.fallback_message}
                onChange={(e) => setForm({ ...form, fallback_message: e.target.value })}
                maxLength={TEXT_LIMIT}
                rows={3}
                className="w-full resize-y rounded-md border border-[#e4e8f0] px-3 py-2 text-xs text-[#1a1f2e] focus:border-[#2563eb] focus:outline-none"
              />
              <div className="mt-1 text-right text-[10px] text-[#8b95a6]">
                {form.fallback_message.length}/{TEXT_LIMIT}
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="置信阈值" hint={`范围 ${THRESHOLD_MIN} ~ ${THRESHOLD_MAX}，步进 0.01`}>
                <input
                  type="number"
                  step={0.01}
                  min={THRESHOLD_MIN}
                  max={THRESHOLD_MAX}
                  value={form.confidence_threshold}
                  onChange={(e) => setForm({ ...form, confidence_threshold: e.target.value })}
                  className="w-full rounded-md border border-[#e4e8f0] px-3 py-2 text-xs text-[#1a1f2e] focus:border-[#2563eb] focus:outline-none"
                />
              </Field>
              <Field label="启用状态">
                <label className="mt-1 flex items-center gap-2 text-xs font-semibold text-[#475467]">
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                    className="h-4 w-4 rounded border-[#cbd5e1] text-[#2563eb]"
                  />
                  {form.enabled ? "启用该提示词" : "停用该提示词"}
                </label>
              </Field>
            </div>
            <Field label="变更原因" hint="必填，将写入管理员审计日志">
              <input
                type="text"
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                placeholder="如：调整留资转化话术"
                className="w-full rounded-md border border-[#e4e8f0] px-3 py-2 text-xs text-[#1a1f2e] focus:border-[#2563eb] focus:outline-none"
              />
            </Field>
          </div>
        ) : null}
      </SlidePanel>
    </div>
  );
}

// ---- 运行记录 tab（只读）----

function RunsTab() {
  const [runs, setRuns] = useState<ReturnVisitRunListItem[]>([]);
  const [stats, setStats] = useState<ReturnVisitRunsStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState({ send_status: "", prompt_key: "", judgement_source: "" });
  const [detail, setDetail] = useState<ReturnVisitRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (filter.send_status) params.send_status = filter.send_status;
      if (filter.prompt_key) params.prompt_key = filter.prompt_key;
      if (filter.judgement_source) params.judgement_source = filter.judgement_source;
      const [runsResp, statsResp] = await Promise.all([
        listReturnVisitRuns(params),
        getReturnVisitRunsStats(),
      ]);
      setRuns(runsResp.data.items);
      setStats(statsResp.data);
    } catch (err) {
      setError(resolveError(err));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (runId: number) => {
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    try {
      const resp = await getReturnVisitRun(runId);
      setDetail(resp.data);
    } catch (err) {
      setDetailError(resolveError(err));
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* 统计 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="运行总数" value={stats?.total ?? "-"} />
        <StatCard label="近 24 小时" value={stats?.recent_24h ?? "-"} />
        <StatCard label="已发送" value={stats?.by_send_status?.sent ?? 0} />
        <StatCard label="已阻断" value={stats?.by_send_status?.blocked ?? 0} />
      </div>

      {/* 过滤器 */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[#e4e8f0] bg-white px-4 py-3">
        <FilterSelect
          label="状态"
          value={filter.send_status}
          options={Object.entries(STATUS_LABELS)}
          onChange={(v) => setFilter({ ...filter, send_status: v })}
        />
        <FilterSelect
          label="场景"
          value={filter.prompt_key}
          options={Object.entries(SCENE_LABELS)}
          onChange={(v) => setFilter({ ...filter, prompt_key: v })}
        />
        <FilterSelect
          label="判定来源"
          value={filter.judgement_source}
          options={Object.entries(SOURCE_LABELS)}
          onChange={(v) => setFilter({ ...filter, judgement_source: v })}
        />
        <button
          type="button"
          onClick={load}
          className="rounded-md border border-[#e4e8f0] px-3 py-1.5 text-xs font-semibold text-[#475467] hover:bg-slate-50"
        >
          刷新
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">{error} <button type="button" onClick={load} className="ml-2 font-semibold text-[#2563eb] underline">重新加载</button></div>
      ) : null}

      {/* 运行表格 */}
      <div className="overflow-auto rounded-xl border border-[#e4e8f0] bg-white">
        <table className="w-full min-w-[920px] text-left text-xs">
          <thead className="bg-[#f8fafc] text-[11px] font-semibold text-[#8b95a6]">
            <tr>
              <th className="px-4 py-2.5">ID</th>
              <th className="px-4 py-2.5">场景</th>
              <th className="px-4 py-2.5">状态</th>
              <th className="px-4 py-2.5">判定来源</th>
              <th className="px-4 py-2.5">置信度</th>
              <th className="px-4 py-2.5">失败码</th>
              <th className="px-4 py-2.5">创建时间</th>
              <th className="px-4 py-2.5 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading && runs.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-6 text-center text-[#8b95a6]">
                  <span className="inline-flex items-center gap-2"><Loader2Icon size={14} className="animate-spin" /> 加载中…</span>
                </td>
              </tr>
            ) : runs.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-6 text-center text-[#8b95a6]">
                  暂无运行记录，系统尚未产生回访运行记录
                </td>
              </tr>
            ) : (
              runs.map((r) => (
                <tr key={r.run_id} className="border-t border-[#eef1f6]">
                  <td className="px-4 py-2.5 font-mono text-[11px] text-[#475467]">{r.run_id}</td>
                  <td className="px-4 py-2.5 text-[#1a1f2e]">{labelOf(SCENE_LABELS, r.prompt_key)}</td>
                  <td className="px-4 py-2.5">{labelOf(STATUS_LABELS, r.send_status)}</td>
                  <td className="px-4 py-2.5 text-[#475467]">{labelOf(SOURCE_LABELS, r.judgement_source)}</td>
                  <td className="px-4 py-2.5 text-[#475467]">
                    {r.confidence != null ? Number(r.confidence).toFixed(2) : "-"}
                  </td>
                  <td className="max-w-[180px] px-4 py-2.5 break-words font-mono text-[11px] text-[#8b95a6]">
                    {r.last_failure_stage || "-"}
                  </td>
                  <td className="px-4 py-2.5 text-[11px] text-[#8b95a6]">{r.created_at || "-"}</td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => openDetail(r.run_id)}
                      className="rounded-md border border-[#e4e8f0] px-3 py-1 text-xs font-semibold text-[#2563eb] hover:bg-[#eff4ff]"
                    >
                      详情
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 详情抽屉（只读）*/}
      <SlidePanel
        open={!!detail || detailLoading || !!detailError}
        title={`运行记录 #${detail?.run_id ?? ""}`}
        onClose={() => {
          setDetail(null);
          setDetailError(null);
        }}
      >
        {detailLoading ? (
          <div className="flex items-center gap-2 text-xs text-[#8b95a6]"><Loader2Icon size={14} className="animate-spin" /> 加载中…</div>
        ) : detailError ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
            {detailError}
          </div>
        ) : detail ? (
          <div className="space-y-4 text-xs">
            <DetailGrid
              rows={[
                ["场景", labelOf(SCENE_LABELS, detail.prompt_key)],
                ["状态", labelOf(STATUS_LABELS, detail.send_status)],
                ["判定来源", labelOf(SOURCE_LABELS, detail.judgement_source)],
                ["触发指纹", detail.trigger_message_fp || "-"],
                ["判定结果", detail.judgement_result || "-"],
                ["置信度", detail.confidence != null ? Number(detail.confidence).toFixed(2) : "-"],
                ["模型", detail.model || "-"],
                ["失败码", detail.last_failure_stage || "-"],
                ["上游消息 ID", detail.send_id || "-"],
                ["商户", detail.merchant_id || "-"],
                ["线索 ID", detail.lead_id ?? "-"],
                ["销售 ID", detail.staff_id ?? "-"],
                ["企业号(掩码)", detail.account_open_id_masked || "-"],
                ["会话(掩码)", detail.conversation_short_id_masked || "-"],
                ["客户(掩码)", detail.customer_open_id_masked || "-"],
                ["人工接管", detail.manual_takeover ? "是" : "否"],
                ["尝试次数", detail.attempt_count ?? "-"],
                ["创建时间", detail.created_at || "-"],
                ["更新时间", detail.updated_at || "-"],
              ]}
            />

            <div>
              <div className="text-xs font-semibold text-[#475467]">风险码</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {detail.risk_flags.length === 0 ? (
                  <span className="text-[11px] text-[#8b95a6]">无</span>
                ) : (
                  detail.risk_flags.map((flag) => (
                    <span
                      key={flag}
                      className="rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700"
                    >
                      {labelOf(RISK_LABELS, flag)}
                    </span>
                  ))
                )}
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-[#475467]">生成话术摘要</div>
              <div className="mt-1.5 break-words whitespace-pre-wrap rounded-md bg-[#f8fafc] px-3 py-2 text-[#475467]">
                {detail.generated_content_summary || "—"}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold text-[#475467]">最终话术摘要</div>
              <div className="mt-1.5 break-words whitespace-pre-wrap rounded-md bg-[#f8fafc] px-3 py-2 text-[#475467]">
                {detail.final_content_summary || "—"}
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-[#475467]">门禁结果</div>
              <div className="mt-1.5 overflow-hidden rounded-md border border-[#e4e8f0]">
                <table className="w-full text-left text-[11px]">
                  <tbody>
                    {Object.keys(detail.gate_results).length === 0 ? (
                      <tr>
                        <td className="px-3 py-2 text-[#8b95a6]">无</td>
                      </tr>
                    ) : (
                      Object.entries(detail.gate_results).map(([gate, value]) => (
                        <tr key={gate} className="border-t border-[#eef1f6]">
                          <td className="px-3 py-1.5 font-mono text-[#475467]">{gate}</td>
                          <td className="px-3 py-1.5 text-[#8b95a6]">{String(value)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) : null}
      </SlidePanel>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-[#e4e8f0] bg-white px-3 py-3">
      <div className="text-[11px] font-semibold text-[#8b95a6]">{label}</div>
      <div className="mt-1 text-xl font-bold text-[#1a1f2e]">{value}</div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] font-semibold text-[#475467]">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-[#e4e8f0] bg-white px-2 py-1 text-xs text-[#1a1f2e] focus:border-[#2563eb] focus:outline-none"
      >
        <option value="">全部</option>
        {options.map(([code, text]) => (
          <option key={code} value={code}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

function DetailGrid({ rows }: { rows: [string, string | number][] }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-start justify-between gap-2 border-b border-[#eef1f6] pb-1.5">
          <span className="text-[11px] text-[#8b95a6]">{label}</span>
          <span className="break-words text-right text-[11px] font-semibold text-[#1a1f2e]">{value}</span>
        </div>
      ))}
    </div>
  );
}
