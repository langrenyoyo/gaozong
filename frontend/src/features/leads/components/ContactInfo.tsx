import { Contact } from "../../../types";

interface ContactInfoProps {
  contact?: Contact | null;
}

const tagStyles = {
  "高意向": "bg-emerald-100 text-emerald-700",
  "需人工": "bg-amber-100 text-amber-700",
  "已留资": "bg-violet-100 text-violet-700",
  "待回访": "bg-red-100 text-red-700",
};

function valueOrUnknown(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "未知";
  return String(value);
}

function statusLabel(value?: string | null): string {
  if (!value) return "待跟进";
  const labels: Record<string, string> = {
    new: "待跟进",
    pending: "待跟进",
    assigned: "已分配",
    contacted: "已联系",
    converted: "已转化",
    closed: "已关闭",
    created: "已生成线索",
  };
  return labels[value] || value;
}

export default function ContactInfo({ contact = null }: ContactInfoProps) {
  if (!contact) {
    return (
      <aside className="flex h-full min-h-0 flex-col overflow-hidden border-l border-[#e4e8f0] bg-white">
        <div className="shrink-0 border-b border-[#e4e8f0] px-4 py-5">
          <h2 className="text-sm font-bold text-[#1a1f2e]">客户画像</h2>
          <p className="mt-1 text-[11px] text-[#8b95a6]">暂无真实会话</p>
        </div>
      </aside>
    );
  }

  const businessRows = [
    { label: "客户名称", value: contact.name },
    { label: "联系方式", value: contact.customerContact },
    { label: "手机号", value: contact.phone },
    { label: "微信号", value: contact.wechat },
    { label: "提取状态", value: contact.contactExtractStatus },
    { label: "线索状态", value: statusLabel(contact.leadStatus) },
    { label: "来源渠道", value: contact.source },
    { label: "最近消息", value: contact.lastMessage },
    { label: "线索内容", value: contact.leadContent || contact.originalMessageText },
    { label: "lead_id", value: contact.leadId },
  ];
  const debugRows = [
    { label: "open_id", value: contact.customerOpenId },
    { label: "conversation_short_id", value: contact.conversationShortId || (contact.isFallbackConversation ? contact.id : null) },
    { label: "fallback 会话", value: contact.isFallbackConversation ? "是" : "否" },
    { label: "from_user_id", value: contact.fromUserId },
    { label: "to_user_id", value: contact.toUserId },
  ];

  return (
    <aside className="flex h-full min-h-0 flex-col overflow-hidden border-l border-[#e4e8f0] bg-white">
      <div className="shrink-0 border-b border-[#e4e8f0] px-4 py-5">
        <h2 className="text-sm font-bold text-[#1a1f2e]">客户画像</h2>
        <p className="mt-1 text-[11px] text-[#8b95a6]">来自已入库 webhook-events</p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        <div className="flex flex-col gap-4">
        <div className="flex flex-col items-center border-b border-[#f0f2f7] pb-5">
          <img
            src={contact.avatarUrl || `https://api.dicebear.com/7.x/avataaars/svg?seed=${contact.avatarSeed}&backgroundColor=b6e3f4,c0aede`}
            alt={contact.name}
            className="h-16 w-16 rounded-full bg-[#e0edff]"
          />
          <strong className="mt-2 max-w-full break-all text-center text-sm text-[#1a1f2e]">{contact.name}</strong>
          <span className={`mt-2 rounded-full px-3 py-0.5 text-xs font-semibold ${tagStyles[contact.tag]}`}>
            {contact.tag}
          </span>
        </div>

          {businessRows.map((row) => (
            <div key={row.label}>
              <span className="text-[10px] text-[#9ca3af]">{row.label}</span>
              <p className="mt-0.5 break-all text-xs font-semibold text-[#374151]">{valueOrUnknown(row.value)}</p>
            </div>
          ))}

          <details className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 py-2">
            <summary className="cursor-pointer text-[11px] font-semibold text-[#64748b]">调试信息</summary>
            <div className="mt-3 space-y-3">
              {debugRows.map((row) => (
                <div key={row.label}>
                  <span className="text-[10px] text-[#9ca3af]">{row.label}</span>
                  <p className="mt-0.5 break-all text-xs font-semibold text-[#374151]">{valueOrUnknown(row.value)}</p>
                </div>
              ))}
            </div>
          </details>
        </div>
      </div>

      <div className="shrink-0 border-t border-[#f0f2f7] px-4 py-4 text-[11px] leading-5 text-[#8b95a6]">
        车系、年款、预算等字段第一版不做推断；无真实字段时统一显示“未知”。
      </div>
    </aside>
  );
}
