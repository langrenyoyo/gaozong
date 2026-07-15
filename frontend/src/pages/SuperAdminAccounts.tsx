import {
  KeyRoundIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  ShieldCheckIcon,
  ShieldOffIcon,
  UserCogIcon,
  XIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

type AdminStatus = "启用" | "禁用";
type AdminRole = "超级管理员" | "运营管理员" | "财务管理员";

interface AdminAccount {
  id: string;
  account: string;
  name: string;
  role: AdminRole;
  phone: string;
  status: AdminStatus;
  lastLogin: string;
  createdAt: string;
}

const adminAccounts: AdminAccount[] = [
  {
    id: "admin-1",
    account: "admin",
    name: "平台超管",
    role: "超级管理员",
    phone: "18578790007",
    status: "启用",
    lastLogin: "2026-06-02 09:18:26",
    createdAt: "2026-01-01 12:12:12",
  },
  {
    id: "admin-2",
    account: "operation01",
    name: "运营一号",
    role: "运营管理员",
    phone: "18600001111",
    status: "启用",
    lastLogin: "2026-06-01 18:42:10",
    createdAt: "2026-01-03 10:22:12",
  },
  {
    id: "admin-3",
    account: "finance01",
    name: "财务一号",
    role: "财务管理员",
    phone: "18700002222",
    status: "禁用",
    lastLogin: "2026-05-28 14:36:55",
    createdAt: "2026-01-05 15:08:42",
  },
];

const roleOptions: Array<AdminRole | "全部角色"> = ["全部角色", "超级管理员", "运营管理员", "财务管理员"];
const statusOptions: Array<AdminStatus | "全部状态"> = ["全部状态", "启用", "禁用"];

const roleClass: Record<AdminRole, string> = {
  超级管理员: "bg-blue-100 text-blue-700",
  运营管理员: "bg-emerald-100 text-emerald-700",
  财务管理员: "bg-amber-100 text-amber-700",
};

function AddAdminModal({ onClose }: { onClose: () => void }) {
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="add-admin-title" className="fixed inset-0 z-30 grid place-items-center bg-[#0f172a]/28 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[500px] rounded-2xl border border-[#e4e8f0] bg-white shadow-[0_24px_80px_rgba(15,23,42,0.20)]">
        <div className="flex items-center justify-between border-b border-[#e4e8f0] px-5 py-4">
          <div>
            <h2 id="add-admin-title" className="text-base font-bold text-[#1a1f2e]">新增管理员</h2>
            <p className="mt-1 text-xs text-[#8b95a6]">创建超管后台管理员账号并分配角色</p>
          </div>
          <button onClick={onClose} aria-label="关闭" className="grid h-8 w-8 place-items-center rounded-xl text-[#8b95a6] hover:bg-[#f4f6f8]">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid gap-3 px-5 py-5 text-xs">
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">登录账号</span>
              <input className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10" placeholder="请输入账号" />
            </label>
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">管理员姓名</span>
              <input className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10" placeholder="请输入姓名" />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">手机号</span>
              <input className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10" placeholder="请输入手机号" />
            </label>
            <label className="grid gap-1.5">
              <span className="font-semibold text-[#64748b]">角色</span>
              <select className="h-10 rounded-xl border border-[#e4e8f0] bg-white px-3 outline-none focus:border-[#2563eb] focus:ring-4 focus:ring-blue-500/10">
                <option>运营管理员</option>
                <option>财务管理员</option>
                <option>超级管理员</option>
              </select>
            </label>
          </div>
          <label className="grid gap-1.5">
            <span className="font-semibold text-[#64748b]">初始密码</span>
            <input className="h-10 rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10" placeholder="请输入初始密码" />
          </label>
        </div>

        <div className="flex justify-end gap-2 border-t border-[#e4e8f0] px-5 py-4">
          <button onClick={onClose} className="h-9 rounded-xl border border-[#e4e8f0] bg-white px-4 text-xs font-semibold text-[#374151]">
            取消
          </button>
          <button onClick={onClose} className="h-9 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]">
            新增管理员
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SuperAdminAccounts() {
  const [keyword, setKeyword] = useState("");
  const [role, setRole] = useState<AdminRole | "全部角色">("全部角色");
  const [status, setStatus] = useState<AdminStatus | "全部状态">("全部状态");
  const [showModal, setShowModal] = useState(false);

  const filtered = useMemo(
    () =>
      adminAccounts.filter((account) => {
        const matchKeyword =
          !keyword.trim() ||
          account.account.includes(keyword.trim()) ||
          account.name.includes(keyword.trim()) ||
          account.phone.includes(keyword.trim());
        const matchRole = role === "全部角色" || account.role === role;
        const matchStatus = status === "全部状态" || account.status === status;
        return matchKeyword && matchRole && matchStatus;
      }),
    [keyword, role, status],
  );

  const stats = [
    { label: "管理员总数", value: adminAccounts.length },
    { label: "启用账号", value: adminAccounts.filter((item) => item.status === "启用").length },
    { label: "禁用账号", value: adminAccounts.filter((item) => item.status === "禁用").length },
    { label: "超级管理员", value: adminAccounts.filter((item) => item.role === "超级管理员").length },
  ];

  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <UserCogIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">管理员账号</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">管理超管后台账号、角色权限和账号状态</p>
          </div>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2563eb] px-4 text-xs font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.22)]"
        >
          <PlusIcon size={14} />
          新增管理员
        </button>
      </header>

      <div className="grid shrink-0 grid-cols-4 gap-0 border-b border-[#e4e8f0] bg-white">
        {stats.map((stat) => (
          <div key={stat.label} className="border-r border-[#f0f2f7] px-5 py-4 last:border-r-0">
            <div className="text-xs font-semibold text-[#667085]">{stat.label}</div>
            <div className="mt-1 text-2xl font-bold leading-none text-[#1a1f2e]">{stat.value}</div>
          </div>
        ))}
      </div>

      <div className="shrink-0 border-b border-[#e4e8f0] bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <SearchIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8b95a6]" />
            <input
              aria-label="搜索账号、姓名、手机号"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              className="h-9 w-[220px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] pl-8 pr-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              placeholder="搜索账号、姓名、手机号"
            />
          </label>
          <select
            aria-label="筛选角色"
            value={role}
            onChange={(event) => setRole(event.target.value as AdminRole | "全部角色")}
            className="h-9 w-[140px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          >
            {roleOptions.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <select
            aria-label="筛选状态"
            value={status}
            onChange={(event) => setStatus(event.target.value as AdminStatus | "全部状态")}
            className="h-9 w-[140px] rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 text-xs outline-none focus:border-[#2563eb] focus:bg-white focus:ring-4 focus:ring-blue-500/10"
          >
            {statusOptions.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <button
            onClick={() => {
              setKeyword("");
              setRole("全部角色");
              setStatus("全部状态");
            }}
            className="ml-auto h-9 rounded-xl border border-[#e4e8f0] bg-white px-3 text-xs font-semibold text-[#374151] hover:bg-[#f8fafc]"
          >
            重置
          </button>
          <span className="text-xs font-semibold text-[#64748b]">
            共 <b className="text-[#2563eb]">{filtered.length}</b> 个账号
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="overflow-hidden rounded-xl border border-[#e4e8f0] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-[#f8fafc] text-[#64748b]">
              <tr>
                <th className="w-[150px] px-4 py-3 font-semibold">账号</th>
                <th className="w-[130px] px-4 py-3 font-semibold">姓名</th>
                <th className="w-[130px] px-4 py-3 font-semibold">角色</th>
                <th className="w-[140px] px-4 py-3 font-semibold">手机号</th>
                <th className="w-[90px] px-4 py-3 font-semibold">状态</th>
                <th className="w-[160px] px-4 py-3 font-semibold">最近登录</th>
                <th className="w-[160px] px-4 py-3 font-semibold">创建时间</th>
                <th className="w-[210px] px-4 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#eef2f6]">
              {filtered.map((account) => (
                <tr key={account.id} className="hover:bg-[#f8fafc]">
                  <td className="px-4 py-3 font-bold text-[#1a1f2e]">{account.account}</td>
                  <td className="px-4 py-3 text-[#374151]">{account.name}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${roleClass[account.role]}`}>
                      {account.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[#374151]">{account.phone}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                        account.status === "启用" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {account.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[#64748b]">{account.lastLogin}</td>
                  <td className="px-4 py-3 text-[#64748b]">{account.createdAt}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <button className="inline-flex h-7 items-center gap-1 rounded-lg bg-[#eff6ff] px-2 text-[11px] font-semibold text-[#2563eb]">
                        <PencilIcon size={12} />
                        编辑
                      </button>
                      <button
                        onClick={() => toast.success(account.status === "启用" ? "已禁用管理员" : "已启用管理员")}
                        className="inline-flex h-7 items-center gap-1 rounded-lg bg-[#f4f6f8] px-2 text-[11px] font-semibold text-[#374151]"
                      >
                        {account.status === "启用" ? <ShieldOffIcon size={12} /> : <ShieldCheckIcon size={12} />}
                        {account.status === "启用" ? "禁用" : "启用"}
                      </button>
                      <button
                        onClick={() => toast.success("已重置密码")}
                        className="inline-flex h-7 items-center gap-1 rounded-lg bg-amber-50 px-2 text-[11px] font-semibold text-amber-700"
                      >
                        <KeyRoundIcon size={12} />
                        重置密码
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {showModal ? <AddAdminModal onClose={() => setShowModal(false)} /> : null}
    </section>
  );
}
