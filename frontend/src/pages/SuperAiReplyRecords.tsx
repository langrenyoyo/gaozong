import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  Clock3Icon,
  EyeIcon,
  MessageSquareTextIcon,
  RefreshCwIcon,
  SearchIcon,
  ShieldCheckIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

type ReplyReviewStatus = "未审核" | "正常回复" | "垃圾回复";
type LeadFilter = "全部留资" | "已触发" | "未触发";

interface ReplyRecord {
  id: string;
  merchant: string;
  category: string;
  customerQuestion: string;
  content: string;
  triggeredLead: boolean;
  status: ReplyReviewStatus;
  riskReason: string;
  reviewer?: string;
  time: string;
}

const initialRecords: ReplyRecord[] = [
  {
    id: "r1",
    merchant: "高新精品二手车",
    category: "精品代步车",
    customerQuestion: "这台轩逸还有现车吗？价格还能不能谈？",
    content: "您好，这台车我先帮您确认库存和车况，您主要关注价格还是检测报告？",
    triggeredLead: true,
    status: "正常回复",
    riskReason: "无风险",
    reviewer: "admin",
    time: "2026-01-01 12:12:12",
  },
  {
    id: "r2",
    merchant: "城南优选车行",
    category: "金融方案助手",
    customerQuestion: "首付一万可以买吗？",
    content: "可以先看首付和月供方案，您方便说一下预算范围吗？",
    triggeredLead: false,
    status: "未审核",
    riskReason: "待人工复核金融回复表述",
    time: "2026-01-01 12:20:18",
  },
  {
    id: "r3",
    merchant: "星河二手车",
    category: "检测报告讲解",
    customerQuestion: "检测报告怎么看，事故车能查出来吗？",
    content: "检测报告可以到店查看，建议您重点看结构件和发动机舱。",
    triggeredLead: true,
    status: "正常回复",
    riskReason: "无风险",
    reviewer: "admin",
    time: "2026-01-01 13:05:26",
  },
  {
    id: "r4",
    merchant: "鼎盛名车",
    category: "精品代步车",
    customerQuestion: "这台车是不是最低价？",
    content: "这台车绝对最低价，今天不买明天就没有了。",
    triggeredLead: false,
    status: "垃圾回复",
    riskReason: "包含绝对化承诺和强迫式催促表达",
    reviewer: "admin",
    time: "2026-01-01 13:16:42",
  },
  {
    id: "r5",
    merchant: "东区车管家",
    category: "金融方案助手",
    customerQuestion: "我想分期，月供大概多少？",
    content: "如果您关注分期，我可以先帮您估算一个月供区间。",
    triggeredLead: true,
    status: "未审核",
    riskReason: "待确认是否触发金融方案合规词",
    time: "2026-01-01 14:02:09",
  },
  {
    id: "r6",
    merchant: "北城认证二手车",
    category: "检测报告讲解",
    customerQuestion: "车况有没有问题？",
    content: "车况信息建议结合完整检测报告一起看，我可以先发重点摘要。",
    triggeredLead: false,
    status: "正常回复",
    riskReason: "无风险",
    reviewer: "admin",
    time: "2026-01-01 14:35:51",
  },
  {
    id: "r7",
    merchant: "高新精品二手车",
    category: "精品代步车",
    customerQuestion: "我下午能过去看车吗？",
    content: "欢迎到店看车，现场可以安排试驾和检测报告讲解。",
    triggeredLead: true,
    status: "正常回复",
    riskReason: "无风险",
    reviewer: "admin",
    time: "2026-01-01 15:18:33",
  },
  {
    id: "r8",
    merchant: "星河二手车",
    category: "金融方案助手",
    customerQuestion: "征信不好能不能分期？",
    content: "保证放款，资料不全也能办。",
    triggeredLead: false,
    status: "垃圾回复",
    riskReason: "包含金融审批保证类表达",
    reviewer: "admin",
    time: "2026-01-01 15:42:10",
  },
  {
    id: "r9",
    merchant: "城南优选车行",
    category: "精品代步车",
    customerQuestion: "有没有同价位的 SUV？",
    content: "有的，我可以按您的预算筛选几台同价位 SUV，您更看重空间还是油耗？",
    triggeredLead: true,
    status: "正常回复",
    riskReason: "无风险",
    reviewer: "admin",
    time: "2026-01-02 10:08:49",
  },
  {
    id: "r10",
    merchant: "鼎盛名车",
    category: "检测报告讲解",
    customerQuestion: "泡水车能不能保证没有？",
    content: "平台检测会覆盖泡水、火烧、重大事故等关键项，建议以完整检测报告为准。",
    triggeredLead: false,
    status: "未审核",
    riskReason: "待确认车况承诺边界",
    time: "2026-01-02 11:24:12",
  },
  {
    id: "r11",
    merchant: "东区车管家",
    category: "精品代步车",
    customerQuestion: "今天看车有优惠吗？",
    content: "到店后可以结合车况和付款方式沟通价格，我先帮您预约看车时段。",
    triggeredLead: true,
    status: "正常回复",
    riskReason: "无风险",
    reviewer: "admin",
    time: "2026-01-02 16:36:27",
  },
  {
    id: "r12",
    merchant: "北城认证二手车",
    category: "金融方案助手",
    customerQuestion: "零首付可以开走吗？",
    content: "具体首付方案需要结合车型、资质和金融机构规则评估，我可以先帮您记录需求。",
    triggeredLead: false,
    status: "未审核",
    riskReason: "金融方案回复待复核",
    time: "2026-01-03 09:12:45",
  },
];

const categoryOptions = ["全部分类", "精品代步车", "金融方案助手", "检测报告讲解"];
const statusOptions: Array<ReplyReviewStatus | "全部状态"> = ["全部状态", "未审核", "正常回复", "垃圾回复"];
const leadOptions: LeadFilter[] = ["全部留资", "已触发", "未触发"];
const pageSizeOptions = [10, 20, 50];

const statusClass: Record<ReplyReviewStatus, string> = {
  未审核: "bg-amber-100 text-amber-700",
  正常回复: "bg-emerald-100 text-emerald-700",
  垃圾回复: "bg-red-100 text-red-700",
};

function getStatusToast(status: ReplyReviewStatus) {
  if (status === "正常回复") return "已标记为正常回复";
  if (status === "垃圾回复") return "已标记为垃圾回复";
  return "已恢复为未审核";
}

export default function SuperAiReplyRecords() {
  const [recordList, setRecordList] = useState<ReplyRecord[]>(initialRecords);
  const [merchantKeyword, setMerchantKeyword] = useState("");
  const [contentKeyword, setContentKeyword] = useState("");
  const [category, setCategory] = useState("全部分类");
  const [status, setStatus] = useState<ReplyReviewStatus | "全部状态">("全部状态");
  const [leadFilter, setLeadFilter] = useState<LeadFilter>("全部留资");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [detailRecord, setDetailRecord] = useState<ReplyRecord | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const filtered = useMemo(
    () =>
      recordList.filter((record) => {
        const keyword = contentKeyword.trim();
        const recordDate = record.time.slice(0, 10);
        const matchMerchant = !merchantKeyword.trim() || record.merchant.includes(merchantKeyword.trim());
        const matchContent = !keyword || `${record.customerQuestion}${record.content}${record.riskReason}`.includes(keyword);
        const matchCategory = category === "全部分类" || record.category === category;
        const matchStatus = status === "全部状态" || record.status === status;
        const matchLead =
          leadFilter === "全部留资" ||
          (leadFilter === "已触发" && record.triggeredLead) ||
          (leadFilter === "未触发" && !record.triggeredLead);
        const matchStart = !startDate || recordDate >= startDate;
        const matchEnd = !endDate || recordDate <= endDate;
        return matchMerchant && matchContent && matchCategory && matchStatus && matchLead && matchStart && matchEnd;
      }),
    [category, contentKeyword, endDate, leadFilter, merchantKeyword, recordList, startDate, status],
  );

  const stats = useMemo(
    () => [
      {
        label: "累计回复",
        value: recordList.length.toLocaleString(),
        icon: <MessageSquareTextIcon size={18} />,
        tone: "bg-blue-100 text-blue-700 ring-blue-200",
      },
      {
        label: "未审核",
        value: recordList.filter((item) => item.status === "未审核").length.toString(),
        icon: <Clock3Icon size={18} />,
        tone: "bg-amber-100 text-amber-700 ring-amber-200",
      },
      {
        label: "正常回复",
        value: recordList.filter((item) => item.status === "正常回复").length.toString(),
        icon: <CheckCircle2Icon size={18} />,
        tone: "bg-emerald-100 text-emerald-700 ring-emerald-200",
      },
      {
        label: "垃圾回复",
        value: recordList.filter((item) => item.status === "垃圾回复").length.toString(),
        icon: <AlertTriangleIcon size={18} />,
        tone: "bg-red-100 text-red-700 ring-red-200",
      },
    ],
    [recordList],
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageItems = useMemo(() => filtered.slice((page - 1) * pageSize, page * pageSize), [filtered, page, pageSize]);
  const visibleIds = pageItems.map((record) => record.id);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));

  useEffect(() => {
    setPage(1);
    setSelectedIds([]);
  }, [category, contentKeyword, endDate, leadFilter, merchantKeyword, pageSize, startDate, status]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  useEffect(() => {
    if (!detailRecord) return;
    const latestRecord = recordList.find((record) => record.id === detailRecord.id);
    setDetailRecord(latestRecord || null);
  }, [detailRecord?.id, recordList]);

  const resetFilters = () => {
    setMerchantKeyword("");
    setContentKeyword("");
    setCategory("全部分类");
    setStatus("全部状态");
    setLeadFilter("全部留资");
    setStartDate("");
    setEndDate("");
  };

  const updateRecordStatus = (recordId: string, nextStatus: ReplyReviewStatus) => {
    setRecordList((current) =>
      current.map((record) =>
        record.id === recordId
          ? {
              ...record,
              status: nextStatus,
              reviewer: "admin",
              riskReason:
                nextStatus === "垃圾回复" && record.riskReason === "无风险" ? "人工标记为垃圾回复" : record.riskReason,
            }
          : record,
      ),
    );
    toast.success(getStatusToast(nextStatus));
  };

  const batchUpdateStatus = (nextStatus: ReplyReviewStatus) => {
    if (!selectedIds.length) {
      toast.error("请选择需要处理的记录");
      return;
    }
    setRecordList((current) =>
      current.map((record) =>
        selectedIds.includes(record.id)
          ? {
              ...record,
              status: nextStatus,
              reviewer: "admin",
              riskReason:
                nextStatus === "垃圾回复" && record.riskReason === "无风险" ? "批量标记为垃圾回复" : record.riskReason,
            }
          : record,
      ),
    );
    toast.success(`已批量处理 ${selectedIds.length} 条记录`);
    setSelectedIds([]);
  };

  const toggleRecordSelection = (recordId: string) => {
    setSelectedIds((current) => (current.includes(recordId) ? current.filter((id) => id !== recordId) : [...current, recordId]));
  };

  const toggleVisibleSelection = () => {
    setSelectedIds((current) => {
      if (allVisibleSelected) return current.filter((id) => !visibleIds.includes(id));
      return Array.from(new Set([...current, ...visibleIds]));
    });
  };

  const renderReviewActions = (record: ReplyRecord, mode: "table" | "modal" = "table") => {
    const baseClass =
      mode === "table"
        ? "inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-lg px-2 text-[11px] font-semibold"
        : "inline-flex h-9 items-center gap-1.5 whitespace-nowrap rounded-xl px-3 text-xs font-semibold";

    if (record.status === "未审核") {
      return (
        <>
          <button
            onClick={() => updateRecordStatus(record.id, "正常回复")}
            className={`${baseClass} bg-emerald-50 text-emerald-700`}
          >
            <ShieldCheckIcon size={12} />
            标记正常
          </button>
          <button onClick={() => updateRecordStatus(record.id, "垃圾回复")} className={`${baseClass} bg-red-50 text-red-600`}>
            <Trash2Icon size={12} />
            标记垃圾
          </button>
        </>
      );
    }

    if (record.status === "正常回复") {
      return (
        <button onClick={() => updateRecordStatus(record.id, "垃圾回复")} className={`${baseClass} bg-red-50 text-red-600`}>
          <Trash2Icon size={12} />
          标记垃圾
        </button>
      );
    }

    return (
      <button onClick={() => updateRecordStatus(record.id, "正常回复")} className={`${baseClass} bg-emerald-50 text-emerald-700`}>
        <ShieldCheckIcon size={12} />
        恢复正常
      </button>
    );
  };

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <MessageSquareTextIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">AI回复记录</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">查看商户智能体回复质量、留资触发和垃圾回复标记</p>
          </div>
        </div>
      </header>

      <div className="grid shrink-0 grid-cols-4 gap-0 border-b border-[#e4e8f0] bg-white">
        {stats.map((stat) => (
          <div key={stat.label} className="flex min-h-[76px] items-center gap-3 border-r border-[#f0f2f7] px-5 py-3 last:border-r-0">
            <div className={`grid h-10 w-10 place-items-center rounded-xl ring-1 ${stat.tone}`}>{stat.icon}</div>
            <div>
              <div className="text-xs font-semibold text-[#667085]">{stat.label}</div>
              <div className="mt-1 text-2xl font-bold leading-none text-[#1a1f2e]">{stat.value}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
            <input
              value={merchantKeyword}
              onChange={(event) => setMerchantKeyword(event.target.value)}
              className="h-9 w-[180px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="请输入商户名称"
            />
          </label>
          <input
            value={contentKeyword}
            onChange={(event) => setContentKeyword(event.target.value)}
            className="h-9 w-[220px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
            placeholder="搜索问题、回复或风险"
          />
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="h-9 w-[150px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          >
            {categoryOptions.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as ReplyReviewStatus | "全部状态")}
            className="h-9 w-[130px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          >
            {statusOptions.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <select
            value={leadFilter}
            onChange={(event) => setLeadFilter(event.target.value as LeadFilter)}
            className="h-9 w-[130px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          >
            {leadOptions.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <input
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
            className="h-9 w-[138px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          />
          <input
            type="date"
            value={endDate}
            onChange={(event) => setEndDate(event.target.value)}
            className="h-9 w-[138px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          />
          <button
            onClick={resetFilters}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151] hover:bg-[#f8fafc]"
          >
            <RefreshCwIcon size={14} />
            重置
          </button>
          <span className="ml-auto text-xs font-semibold text-[#64748b]">
            共 <b className="text-[#2563eb]">{filtered.length}</b> 条
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {selectedIds.length ? (
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#e4e8f0] bg-white px-4 py-3 text-xs shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <span className="font-semibold text-[#64748b]">
              已选择 <b className="text-[#2563eb]">{selectedIds.length}</b> 条回复记录
            </span>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => batchUpdateStatus("正常回复")}
                className="inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-xl bg-emerald-50 px-3 text-xs font-semibold text-emerald-700"
              >
                <ShieldCheckIcon size={13} />
                批量正常
              </button>
              <button
                onClick={() => batchUpdateStatus("垃圾回复")}
                className="inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-xl bg-red-50 px-3 text-xs font-semibold text-red-600"
              >
                <Trash2Icon size={13} />
                批量垃圾
              </button>
              <button
                onClick={() => setSelectedIds([])}
                className="inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-xl bg-[#f4f6f8] px-3 text-xs font-semibold text-[#374151]"
              >
                取消选择
              </button>
            </div>
          </div>
        ) : null}

        <div className="overflow-x-auto rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <table className="min-w-[1180px] w-full table-fixed text-left text-xs">
            <thead className="bg-[#f8fafc] text-[#64748b]">
              <tr>
                <th className="w-[44px] px-4 py-3 font-semibold">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleVisibleSelection}
                    className="h-4 w-4 rounded border-[#d0d5dd] text-[#2563eb] focus:ring-[#2563eb]"
                  />
                </th>
                <th className="w-[170px] px-4 py-3 font-semibold">商户</th>
                <th className="w-[150px] px-4 py-3 font-semibold">智能体分类</th>
                <th className="px-4 py-3 font-semibold">客户问题 / AI回复</th>
                <th className="w-[120px] px-4 py-3 font-semibold">是否触发留资</th>
                <th className="w-[110px] px-4 py-3 font-semibold">状态</th>
                <th className="w-[150px] px-4 py-3 font-semibold">时间</th>
                <th className="w-[250px] px-4 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#eef2f6]">
              {pageItems.map((record) => (
                <tr key={record.id} className="hover:bg-[#f8fafc]">
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(record.id)}
                      onChange={() => toggleRecordSelection(record.id)}
                      className="h-4 w-4 rounded border-[#d0d5dd] text-[#2563eb] focus:ring-[#2563eb]"
                    />
                  </td>
                  <td className="px-4 py-3 font-bold text-[#1a1f2e]">{record.merchant}</td>
                  <td className="px-4 py-3 text-[#374151]">{record.category}</td>
                  <td className="px-4 py-3 text-[#374151]">
                    <div className="line-clamp-1 font-semibold leading-6 text-[#1a1f2e]">{record.customerQuestion}</div>
                    <div className="line-clamp-2 leading-6 text-[#64748b]">{record.content}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                        record.triggeredLead ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {record.triggeredLead ? "是" : "否"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${statusClass[record.status]}`}>
                      {record.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[#64748b]">{record.time}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-nowrap gap-1.5">
                      <button
                        onClick={() => setDetailRecord(record)}
                        className="inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-lg bg-[#eff6ff] px-2 text-[11px] font-semibold text-[#2563eb]"
                      >
                        <EyeIcon size={12} />
                        详情
                      </button>
                      {renderReviewActions(record)}
                    </div>
                  </td>
                </tr>
              ))}
              {!pageItems.length ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-xs font-semibold text-[#98a2b3]">
                    暂无匹配的 AI 回复记录
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs font-semibold text-[#64748b]">
            第 <b className="text-[#1a1f2e]">{page}</b> / {totalPages} 页
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={pageSize}
              onChange={(event) => setPageSize(Number(event.target.value))}
              className="h-8 rounded-lg border border-[#e4e8f0] bg-white px-2 text-xs font-semibold text-[#64748b] outline-none focus:border-[#2563eb]"
            >
              {pageSizeOptions.map((size) => (
                <option key={size} value={size}>
                  {size} 条/页
                </option>
              ))}
            </select>
            <button
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              className="h-8 min-w-8 rounded-lg bg-white px-3 text-xs font-semibold text-[#64748b] ring-1 ring-[#e4e8f0] disabled:cursor-not-allowed disabled:opacity-50"
            >
              上一页
            </button>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              className="h-8 min-w-8 rounded-lg bg-white px-3 text-xs font-semibold text-[#64748b] ring-1 ring-[#e4e8f0] disabled:cursor-not-allowed disabled:opacity-50"
            >
              下一页
            </button>
          </div>
        </div>
      </div>

      {detailRecord ? (
        <div className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
          <div className="w-full max-w-[720px] overflow-hidden rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
            <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
              <div>
                <h2 className="text-base font-bold text-[#1a1f2e]">回复详情</h2>
                <p className="mt-1 text-xs text-[#8b95a6]">
                  {detailRecord.merchant} · {detailRecord.category}
                </p>
              </div>
              <button onClick={() => setDetailRecord(null)} className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
                <XIcon size={16} />
              </button>
            </div>

            <div className="grid gap-4 px-5 py-5 text-xs">
              <div className="grid grid-cols-4 gap-3">
                <div className="rounded-xl bg-[#f8fafc] px-3 py-3 ring-1 ring-[#e4e8f0]">
                  <div className="font-semibold text-[#98a2b3]">状态</div>
                  <span className={`mt-2 inline-flex rounded-md px-2 py-0.5 text-[11px] font-semibold ${statusClass[detailRecord.status]}`}>
                    {detailRecord.status}
                  </span>
                </div>
                <div className="rounded-xl bg-[#f8fafc] px-3 py-3 ring-1 ring-[#e4e8f0]">
                  <div className="font-semibold text-[#98a2b3]">留资触发</div>
                  <div className="mt-2 font-bold text-[#1a1f2e]">{detailRecord.triggeredLead ? "已触发" : "未触发"}</div>
                </div>
                <div className="rounded-xl bg-[#f8fafc] px-3 py-3 ring-1 ring-[#e4e8f0]">
                  <div className="font-semibold text-[#98a2b3]">审核人</div>
                  <div className="mt-2 font-bold text-[#1a1f2e]">{detailRecord.reviewer || "未审核"}</div>
                </div>
                <div className="rounded-xl bg-[#f8fafc] px-3 py-3 ring-1 ring-[#e4e8f0]">
                  <div className="font-semibold text-[#98a2b3]">回复时间</div>
                  <div className="mt-2 font-bold text-[#1a1f2e]">{detailRecord.time}</div>
                </div>
              </div>

              <div className="grid gap-1.5">
                <span className="font-semibold text-[#64748b]">客户问题</span>
                <div className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 py-3 leading-6 text-[#1a1f2e]">
                  {detailRecord.customerQuestion}
                </div>
              </div>
              <div className="grid gap-1.5">
                <span className="font-semibold text-[#64748b]">AI回复内容</span>
                <div className="rounded-xl border border-[#e4e8f0] bg-white px-3 py-3 leading-6 text-[#374151]">
                  {detailRecord.content}
                </div>
              </div>
              <div className="grid gap-1.5">
                <span className="font-semibold text-[#64748b]">风险说明</span>
                <div className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 py-3 leading-6 text-[#64748b]">
                  {detailRecord.riskReason}
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
              <button
                onClick={() => setDetailRecord(null)}
                className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]"
              >
                关闭
              </button>
              {renderReviewActions(detailRecord, "modal")}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
