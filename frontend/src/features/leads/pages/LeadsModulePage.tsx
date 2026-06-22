import { FilterIcon } from "lucide-react";

import LeadsManagement from "./LeadsManagement";

export default function LeadsModulePage() {
  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <div className="shrink-0 border-b border-[#dbe3ef] bg-white px-5 pt-3">
        <div className="flex items-center gap-2">
          <button className="inline-flex h-9 items-center gap-1.5 border-b-2 border-[#2563eb] px-3 text-xs font-semibold text-[#2563eb]">
            <FilterIcon size={14} />
            有效线索
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        <LeadsManagement />
      </div>
    </section>
  );
}
