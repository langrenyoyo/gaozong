import { useLocation, useNavigate } from "react-router-dom";

export interface ModuleTabItem {
  label: string;
  path: string;
}

export default function ModuleTabs({ items }: { items: ModuleTabItem[] }) {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <nav aria-label="模块切换" className="mt-3 inline-flex rounded-lg border border-[#e4e8f0] bg-[#f8fafc] p-0.5 text-xs font-semibold">
      {items.map((item) => {
        const active = location.pathname === item.path;
        return (
          <button
            key={item.path}
            type="button"
            aria-current={active ? "page" : undefined}
            onClick={() => navigate(item.path)}
            className={`rounded-md px-4 py-1.5 transition ${
              active ? "bg-white text-[#2563eb] shadow-sm" : "text-[#8b95a6] hover:text-[#475467]"
            }`}
          >
            {item.label}
          </button>
        );
      })}
    </nav>
  );
}
