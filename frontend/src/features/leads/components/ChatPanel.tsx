import { BotIcon, LoaderIcon, UserIcon } from "lucide-react";
import { useEffect, useRef } from "react";
import { ChatMessage, Contact } from "../../../types";

interface ChatPanelProps {
  contact?: Contact | null;
  messages?: ChatMessage[];
  loading?: boolean;
}

function eventDescription(event?: string | null, sender?: string): string {
  if (event === "im_enter_direct_msg") return "进入私信会话";
  if (event === "im_send_msg") return "我方发送了一条非文本消息";
  if (event === "im_receive_msg") return "客户发送了一条非文本消息";
  return sender === "system" ? "系统事件" : "无文本内容";
}

export default function ChatPanel({ contact = null, messages = [], loading = false }: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, contact?.id]);

  if (!contact) {
    return (
      <section className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f3f6fa]">
        <header className="shrink-0 border-b border-[#e4e8f0] bg-white px-6 py-4">
          <h1 className="text-[15px] font-bold text-[#1a1f2e]">抖音AI小高客服</h1>
          <p className="mt-1 text-xs text-[#8b95a6]">真实事件回调私信会话</p>
        </header>
        <div className="grid min-h-0 flex-1 place-items-center px-8 text-center">
          <p className="max-w-[320px] text-xs leading-6 text-[#8b95a6]">
            暂无真实抖音私信会话，请完成授权并让客户发送私信。
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-[#e4e8f0] bg-white px-6 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="relative">
            <img
              src={contact.avatarUrl || `https://api.dicebear.com/7.x/avataaars/svg?seed=${contact.avatarSeed}&backgroundColor=b6e3f4,c0aede`}
              alt={contact.name}
              className="h-11 w-11 rounded-full bg-[#e0edff]"
            />
            <span
              className="status-dot-pulse absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white"
              style={{ background: contact.isOnline ? "#10b981" : "#d1d5db" }}
            />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-[15px] font-bold text-[#1a1f2e]">{contact.name}</h1>
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-600">
                {contact.isOnline ? "最近活跃" : "历史会话"}
              </span>
            </div>
            <p className="mt-1 truncate text-[11px] text-[#8b95a6]">
              {contact.source} · {contact.eventsCount || 0} 条事件
            </p>
          </div>
        </div>

        <span className="rounded-xl border border-[#e4e8f0] bg-[#f8fafc] px-3 py-2 text-xs font-semibold text-[#64748b]">
          只读展示
        </span>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-7 py-5">
        {loading ? (
          <div className="grid h-full place-items-center text-xs text-[#8b95a6]">
            <span className="inline-flex items-center gap-2">
              <LoaderIcon size={14} className="animate-spin" />
              加载真实消息
            </span>
          </div>
        ) : messages.length === 0 ? (
          <div className="grid h-full place-items-center px-8 text-center text-xs leading-6 text-[#8b95a6]">
            该会话尚未收到已入库的私信事件，请等待客户发送私信。
          </div>
        ) : (
          messages.map((msg) => {
            const isCustomer = msg.sender === "user";
            const isSystem = msg.sender === "system";
            const isAi = msg.sender === "ai";

            if (isSystem) {
              return (
                <div key={msg.id} className="mb-4 flex justify-center">
                  <span className="max-w-[72%] rounded-full bg-[#e8edf5] px-3 py-1 text-center text-[11px] text-[#64748b]">
                    {msg.content || eventDescription(msg.event, msg.sender)}
                  </span>
                </div>
              );
            }

            return (
              <div key={msg.id} className={`mb-4 flex items-start gap-2.5 ${isCustomer ? "" : "flex-row-reverse"}`}>
                {isCustomer ? (
                  <img
                    src={contact.avatarUrl || `https://api.dicebear.com/7.x/avataaars/svg?seed=${contact.avatarSeed}&backgroundColor=b6e3f4`}
                    alt={contact.name}
                    className="mt-0.5 h-8 w-8 shrink-0 rounded-full bg-[#e0edff]"
                  />
                ) : (
                  <div className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full ${isAi ? "bg-[#1a2035]" : "bg-[#2563eb]"} text-white`}>
                    {isAi ? <BotIcon size={14} /> : <UserIcon size={14} />}
                  </div>
                )}

                <div className={`flex max-w-[68%] flex-col ${isCustomer ? "items-start" : "items-end"}`}>
                  <span className="mb-1 text-[10px] text-[#8b95a6]">
                    {isCustomer ? contact.name : msg.senderLabel || "我方"}
                  </span>
                  <div
                    className={`rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed shadow-[0_1px_2px_rgba(15,23,42,0.05)] ${
                      isCustomer
                        ? "rounded-tl bg-white text-[#1a1f2e] ring-1 ring-[#e4e8f0]"
                        : "rounded-tr bg-[#2563eb] text-white shadow-[0_10px_24px_rgba(37,99,235,0.18)]"
                    }`}
                  >
                    {msg.content || eventDescription(msg.event, msg.sender)}
                  </div>
                  <span className="mt-1 text-[10px] text-[#9ca3af]">{msg.time}</span>
                </div>
              </div>
            );
          })
        )}

        <div ref={messagesEndRef} />
      </div>

      <footer className="shrink-0 border-t border-[#e4e8f0] bg-white px-4 py-3">
        <div className="rounded-2xl border border-[#e4e8f0] bg-[#f8fafc] px-4 py-3 text-xs leading-6 text-[#64748b]">
          当前页面只展示系统已收到并保存的私信事件；不主动拉取历史私信，不发送抖音消息，不执行 AI 自动回复。
        </div>
      </footer>
    </section>
  );
}
