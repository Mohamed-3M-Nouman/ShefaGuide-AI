import { BrowserRouter, NavLink, Route, Routes } from "react-router";

import MedicalDisclaimer from "./components/MedicalDisclaimer";
import ChatInterface from "./components/ChatInterface";
import Dashboard from "./pages/Dashboard";

function getNavClass({ isActive }) {
  const base = "rounded-lg px-4 py-2 text-sm font-semibold transition-colors";

  return `${base} ${
    isActive ? "bg-teal-700 text-white" : "text-slate-600 hover:bg-slate-100"
  }`;
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-dvh flex-col overflow-hidden bg-slate-50">
        <MedicalDisclaimer />

        <nav
          aria-label="التنقل الرئيسي"
          className="shrink-0 border-b border-slate-200 bg-white"
        >
          <div className="mx-auto flex max-w-6xl gap-2 px-4 py-2">
            <NavLink to="/" end className={getNavClass}>
              الشات
            </NavLink>

            <NavLink to="/dashboard" className={getNavClass}>
              الداشبورد التجريبي
            </NavLink>
          </div>
        </nav>

        <Routes>
          <Route path="/" element={<ChatInterface />} />

          <Route path="/dashboard" element={<Dashboard />} />

          <Route
            path="*"
            element={
              <main className="p-8 text-center">
                <h1 className="text-xl font-bold">الصفحة غير موجودة</h1>

                <p className="mt-3 text-slate-600">
                  استخدم روابط التنقل بالأعلى للرجوع.
                </p>
              </main>
            }
          />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
