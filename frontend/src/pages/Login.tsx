import { BotIcon, EyeIcon, EyeOffIcon, LockIcon, UserIcon } from "lucide-react";
import { useState } from "react";
import { AppUser } from "../App";
import { PERMISSIONS } from "../features/capabilities";

interface LoginProps {
  onLogin: (user: AppUser) => void;
  authError?: string | null;
}

const devPermissions = [
  PERMISSIONS.use,
  PERMISSIONS.douyinAiCs,
  PERMISSIONS.leads,
  PERMISSIONS.agent,
  PERMISSIONS.compute,
  PERMISSIONS.adminComputeConfig,
];

export default function Login({ onLogin, authError }: LoginProps) {
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [account, setAccount] = useState("18578790007");

  const handleLogin = () => {
    const normalized = account.trim();
    const adminUsers: Record<string, AppUser> = {
      admin: { account: "admin", role: "super_admin", roleLabel: "超级管理员", permissions: devPermissions },
      operation01: { account: "operation01", role: "operation_admin", roleLabel: "运营管理员", permissions: devPermissions },
      finance01: { account: "finance01", role: "finance_admin", roleLabel: "财务管理员", permissions: devPermissions },
    };

    onLogin(
      adminUsers[normalized] || {
        account: normalized || "18578790007",
        role: "merchant",
        roleLabel: "商户账号",
        permissions: devPermissions,
      },
    );
  };

  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#070d18] bg-cover bg-center text-[#1a1f2e]"
      style={{
        backgroundImage:
          "linear-gradient(90deg, rgba(3,7,18,0.96) 0%, rgba(10,18,32,0.90) 42%, rgba(38,55,85,0.68) 70%, rgba(7,13,24,0.84) 100%), url('https://cdn.pixabay.com/photo/2020/11/04/17/42/car-5713115_1280.jpg')",
      }}
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_24%_78%,rgba(37,99,235,0.22),transparent_34%),radial-gradient(circle_at_74%_22%,rgba(180,200,230,0.18),transparent_32%)]" />

      <div className="relative grid min-h-screen grid-cols-[minmax(620px,1fr)_minmax(420px,0.72fr)] px-12 py-9 max-[980px]:grid-cols-1 max-[980px]:px-5">
        <section className="flex h-full flex-col text-white max-[980px]:min-h-[46vh]">
          <div className="flex items-center gap-3">
            <div className="grid h-12 w-12 place-items-center rounded-full bg-white text-[#2563eb] shadow-[0_0_30px_rgba(255,255,255,0.28)]">
              <BotIcon size={21} />
            </div>
            <div>
              <div className="text-2xl font-bold">小高AI系统</div>
            </div>
          </div>

          <div className="mt-auto max-w-[520px] pb-12 max-[980px]:mt-12 max-[980px]:pb-6">
            <div className="mb-5 inline-flex rounded-full bg-white/10 px-3 py-1 text-xs font-semibold text-blue-100 ring-1 ring-white/12">
              销售、线索、客服与自动化协同
            </div>
            <h1 className="text-[40px] font-bold leading-tight tracking-normal max-[980px]:text-[30px]">
              让门店客户跟进更快一步
            </h1>
            <p className="mt-4 text-sm leading-7 text-slate-300">
              统一处理抖音企业号会话、AI 托管回复、线索沉淀和微信助手任务。
            </p>
          </div>
        </section>

        <section className="grid place-items-center px-6 py-10 max-[980px]:px-0 max-[980px]:py-6">
          <div className="w-full max-w-[390px]">
            <div className="rounded-[24px] border border-white/70 bg-white/88 p-8 shadow-[0_28px_80px_rgba(15,23,42,0.24)] backdrop-blur-md">
              <div>
                <h2 className="text-[34px] font-extrabold italic leading-none text-[#323845]">
                  <span className="text-[#4b55ff]">W</span>elcome
                </h2>
                <p className="mt-4 text-sm font-bold text-[#64748b]">欢迎使用 小高AI系统</p>
                {authError ? (
                  <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold leading-5 text-red-700">
                    {authError}
                  </p>
                ) : null}
              </div>

              <div className="mt-9 grid gap-5">
                <label className="grid gap-1.5">
                  <span className="text-xs font-semibold text-[#64748b]">账号</span>
                  <div className="grid h-12 grid-cols-[36px_1fr] items-center rounded-xl border border-transparent bg-white px-2 focus-within:border-[#4b55ff] focus-within:ring-4 focus-within:ring-indigo-500/10">
                    <UserIcon size={16} className="justify-self-center text-[#8b95a6]" />
                    <input
                      className="h-full bg-transparent text-sm outline-none placeholder:text-[#9ca3af]"
                      value={account}
                      onChange={(event) => setAccount(event.target.value)}
                      placeholder="请输入手机号或账号"
                    />
                  </div>
                </label>

                <label className="grid gap-1.5">
                  <span className="text-xs font-semibold text-[#64748b]">密码</span>
                  <div className="grid h-12 grid-cols-[36px_1fr_32px] items-center rounded-xl border border-transparent bg-white px-2 focus-within:border-[#4b55ff] focus-within:ring-4 focus-within:ring-indigo-500/10">
                    <LockIcon size={16} className="justify-self-center text-[#8b95a6]" />
                    <input
                      type={showPassword ? "text" : "password"}
                      className="h-full bg-transparent text-sm outline-none placeholder:text-[#9ca3af]"
                      defaultValue="123456"
                      placeholder="请输入密码"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((value) => !value)}
                      className="grid h-8 w-8 place-items-center rounded-lg text-[#8b95a6] hover:bg-[#eef2f7]"
                      aria-label={showPassword ? "隐藏密码" : "显示密码"}
                    >
                      {showPassword ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
                    </button>
                  </div>
                </label>
              </div>

              <div className="mt-4 flex items-center text-xs">
                <button
                  onClick={() => setRemember((value) => !value)}
                  className="inline-flex items-center gap-2 font-semibold text-[#64748b]"
                >
                  <span
                    className={`grid h-4 w-4 place-items-center rounded border ${
                      remember ? "border-[#2563eb] bg-[#2563eb]" : "border-[#cbd5e1] bg-white"
                    }`}
                  >
                    {remember ? <span className="h-1.5 w-1.5 rounded-full bg-white" /> : null}
                  </span>
                  记住账号
                </button>
              </div>

              <button
                onClick={handleLogin}
                className="mt-6 h-12 w-full rounded-xl bg-[#4b55ff] text-sm font-semibold text-white shadow-[0_14px_28px_rgba(75,85,255,0.30)] transition-smooth hover:bg-[#3541ee] active:scale-[0.99]"
              >
                登录
              </button>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
