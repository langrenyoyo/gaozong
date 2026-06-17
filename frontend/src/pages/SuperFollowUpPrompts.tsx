import { MessageCircleMoreIcon } from "lucide-react";

export default function SuperFollowUpPrompts() {
  return (
    <section className="flex h-full flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between border-b border-[#e4e8f0] bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <MessageCircleMoreIcon size={22} />
          </div>
          <div>
            <h1 className="text-[15px] font-bold text-[#1a1f2e]">跟进话术配置</h1>
            <p className="mt-1 text-xs text-[#8b95a6]">平台跟进话术和回复策略</p>
          </div>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 place-items-center p-6">
        <div className="w-full max-w-[520px] rounded-xl border border-dashed border-[#cbd5e1] bg-white px-6 py-8 text-center shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
            <MessageCircleMoreIcon size={24} />
          </div>
          <h2 className="mt-4 text-sm font-bold text-[#1a1f2e]">跟进话术配置真实接口暂未接入</h2>
          <p className="mt-2 text-xs leading-6 text-[#64748b]">
            当前页面不再加载假跟进话术。接入真实配置 API 后再恢复话术新增、编辑、启用和停用操作。
          </p>
        </div>
      </main>
    </section>
  );
}
