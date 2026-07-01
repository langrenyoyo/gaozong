import LeadsManagement from "./LeadsManagement";

export default function LeadsModulePage() {
  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-[#f3f6fa]">
      <div className="min-h-0 flex-1 overflow-hidden">
        <LeadsManagement />
      </div>
    </section>
  );
}
