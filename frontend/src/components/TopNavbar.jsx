import { NavLink, Link } from "react-router";
import { useApp } from "../context/appContext";
import BrandLogo from "./BrandLogo";

function getNavLinkClass({ isActive }) {
  const base =
    "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs sm:text-sm font-semibold transition-all whitespace-nowrap";
  return `${base} ${
    isActive
      ? "bg-[#0D9488] text-white shadow-xs"
      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
  }`;
}

export default function TopNavbar() {
  const { theme, toggleTheme, savedPasses, authUser } = useApp();

  return (
    <header className="shrink-0 border-b border-slate-200 bg-white/95 backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/95 print:hidden">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        {/* Brand Logo */}
        <div className="flex items-center gap-3">
          <Link to="/" className="flex items-center gap-2.5 group">
            <BrandLogo className="h-10 w-10 shrink-0 drop-shadow-xs group-hover:scale-105 transition-transform" />
            <div className="leading-tight">
              <div className="flex items-center gap-2">
                <span className="text-base font-extrabold text-slate-900 dark:text-white">
                  شفاء جايد
                </span>
                <span className="font-en hidden sm:inline-block rounded-md bg-teal-50 px-1.5 py-0.5 text-[11px] font-semibold text-[#0D9488] dark:bg-teal-950/60 dark:text-teal-300">
                  ShefaGuide AI
                </span>
              </div>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                منصة الفرز الطبي الذكي الآمن
              </p>
            </div>
          </Link>
        </div>

        {/* 7-Screen Primary Navigation */}
        <nav
          aria-label="التنقل الرئيسي"
          className="flex flex-wrap items-center gap-1"
        >
          <NavLink to="/" end className={getNavLinkClass}>
            <span>الرئيسية</span>
          </NavLink>
          <NavLink to="/triage" className={getNavLinkClass}>
            <span>مساحة الفرز</span>
          </NavLink>
          <NavLink to="/profile" className={getNavLinkClass}>
            <span>الخزنة المؤقتة</span>
          </NavLink>
          <NavLink to="/history" className={getNavLinkClass}>
            <span>أرشيف البطاقات</span>
            {savedPasses.length > 0 && (
              <span className="font-en rounded-full bg-indigo-100 px-1.5 py-0.2 text-[10px] font-bold text-[#4F46E5] dark:bg-indigo-950 dark:text-indigo-300">
                {savedPasses.length}
              </span>
            )}
          </NavLink>
          <NavLink to="/dashboard" className={getNavLinkClass}>
            <span>لوحة الطوارئ</span>
          </NavLink>
        </nav>

        {/* Right Controls: Zero-PHI Pill, Auth Pill, Dark Mode Toggle */}
        <div className="flex items-center gap-2">
          <span
            title="لا يتم حفظ أي بيانات طبية على جهازك — كل الجلسة في الذاكرة المؤقتة فقط"
            className="hidden md:inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-bold text-emerald-800 dark:border-emerald-800/60 dark:bg-emerald-950/50 dark:text-emerald-300"
          >
            <span>🔒</span>
            <span>Zero-PHI RAM</span>
          </span>

          <NavLink
            to="/auth"
            className={({ isActive }) =>
              `inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition-colors ${
                isActive
                  ? "border-[#4F46E5] bg-[#4F46E5] text-white"
                  : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              }`
            }
          >
            <span>{authUser.mode === "guest" ? "زائر" : authUser.name}</span>
          </NavLink>

          <button
            type="button"
            onClick={toggleTheme}
            aria-label={
              theme === "dark" ? "التبديل إلى الوضع النهاري" : "التبديل إلى الوضع الليلي"
            }
            title={
              theme === "dark" ? "التبديل إلى الوضع النهاري" : "التبديل إلى الوضع الليلي"
            }
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-base text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-amber-300 dark:hover:bg-slate-700 transition-colors cursor-pointer"
          >
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
        </div>
      </div>
    </header>
  );
}
