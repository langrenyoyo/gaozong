import { useState } from "react";
import { FileSearchIcon, FilterIcon, QrCodeIcon } from "lucide-react";

import DouyinLiveCheckPage from "../../douyin-cs/pages/DouyinLiveCheckPage";
import LeadsManagement from "./LeadsManagement";
import WebhookEventsPage from "./WebhookEventsPage";

type LeadsModuleTab = "valid-leads" | "raw-events" | "douyin-live-check";

const tabs: Array<{
  id: LeadsModuleTab;
  label: string;
  icon: React.ReactNode;
}> = [
  { id: "valid-leads", label: "有效线索", icon: <FilterIcon size={14} /> },
  { id: "raw-events", label: "原始事件", icon: <FileSearchIcon size={14} /> },
  { id: "douyin-live-check", label: "抖音授权联调", icon: <QrCodeIcon size={14} /> },
];

export default function LeadsModulePage() {
  const [activeTab, setActiveTab] = useState<LeadsModuleTab>("valid-leads");

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <div className="shrink-0 border-b border-[#dbe3ef] bg-white px-5 pt-3">
        <div className="flex items-center gap-2">
          {tabs.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`inline-flex h-9 items-center gap-1.5 border-b-2 px-3 text-xs font-semibold transition-smooth ${
                  active
                    ? "border-[#2563eb] text-[#2563eb]"
                    : "border-transparent text-[#64748b] hover:text-[#1a1f2e]"
                }`}
              >
                {tab.icon}
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab === "valid-leads" ? (
          <LeadsManagement />
        ) : activeTab === "raw-events" ? (
          <WebhookEventsPage />
        ) : (
          <DouyinLiveCheckPage />
        )}
      </div>
    </section>
  );
}
