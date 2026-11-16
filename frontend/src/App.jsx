import { BrowserRouter, Route, Routes, Link } from "react-router";

import AppProvider from "./context/AppProvider";
import MedicalDisclaimer from "./components/MedicalDisclaimer";
import TopNavbar from "./components/TopNavbar";
import DoctorPassModal from "./components/DoctorPassModal";
import ChatInterface from "./components/ChatInterface";
import LandingPage from "./pages/LandingPage";
import AuthPage from "./pages/AuthPage";
import ProfileVaultPage from "./pages/ProfileVaultPage";
import HistoryArchivePage from "./pages/HistoryArchivePage";
import Dashboard from "./pages/Dashboard";

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <div className="flex h-dvh flex-col overflow-hidden bg-[#F8FAFC] text-slate-900 dark:bg-[#0F172A] dark:text-slate-100 print:h-auto print:overflow-visible print:bg-white">
          <MedicalDisclaimer />
          <TopNavbar />

          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/auth" element={<AuthPage />} />
            <Route path="/profile" element={<ProfileVaultPage />} />
            <Route path="/triage" element={<ChatInterface />} />
            <Route path="/history" element={<HistoryArchivePage />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route
              path="*"
              element={
                <main className="flex flex-1 flex-col items-center justify-center p-8 text-center">
                  <h1 className="text-2xl font-black">الصفحة غير موجودة</h1>
                  <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                    يمكنك الرجوع إلى الصفحة الرئيسية أو بدء الفرز الطبي مباشرة.
                  </p>
                  <Link
                    to="/"
                    className="mt-4 rounded-xl bg-[#0D9488] px-5 py-2.5 text-sm font-bold text-white"
                  >
                    العودة للرئيسية
                  </Link>
                </main>
              }
            />
          </Routes>

          <DoctorPassModal />
        </div>
      </BrowserRouter>
    </AppProvider>
  );
}
