import { useState } from "react";
import { useNavigate } from "react-router";
import { useApp } from "../context/appContext";

export default function AuthPage() {
  const navigate = useNavigate();
  const { authUser, loginAsPersonal, continueAsGuest } = useApp();

  const [activeTab, setActiveTab] = useState("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [formNotice, setFormNotice] = useState("");

  function handleGuestStart() {
    continueAsGuest();
    navigate("/triage");
  }

  function handlePersonalSubmit(event) {
    event.preventDefault();
    if (!email.trim()) {
      setFormNotice("يرجى إدخال البريد الإلكتروني أو المتابعة كزائر مباشرة.");
      return;
    }
    loginAsPersonal({
      name: name.trim() || email.split("@")[0] || "حساب شخصي مؤقت",
      email: email.trim(),
    });
    setFormNotice("");
    navigate("/profile");
  }

  return (
    <main className="min-h-0 flex-1 overflow-y-auto bg-[#F8FAFC] dark:bg-[#0F172A] px-4 py-8 sm:py-12">
      <div className="mx-auto max-w-4xl grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* Prominent Zero-PHI Guest Mode Card */}
        <section className="lg:col-span-2 flex flex-col justify-between rounded-3xl border-2 border-[#0D9488] bg-gradient-to-b from-teal-50 to-white p-6 shadow-sm dark:from-teal-950/50 dark:to-slate-900">
          <div className="space-y-4">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
              <span>🔒</span>
              <span>موصى به للخصوصية (Zero-PHI)</span>
            </span>

            <h1 className="text-2xl font-black text-slate-900 dark:text-white">
              وضع الزائر السريع بدون تسجيل
            </h1>

            <p className="text-sm leading-7 text-slate-600 dark:text-slate-300">
              ابدأ الفرز الطبي الفوري دون إدخال اسم أو رقم هاتف أو إنشاء حساب.
              تُدار الجلسة بالكامل داخل ذاكرة التبويب المؤقتة وتُمحى فور الإغلاق.
            </p>

            <ul className="space-y-2 text-xs text-slate-700 dark:text-slate-300">
              <li className="flex items-center gap-2">
                <span className="text-[#0D9488] font-bold">✓</span>
                <span>إدخال نصي وصوتي كامل باللهجة المصرية</span>
              </li>
              <li className="flex items-center gap-2">
                <span className="text-[#0D9488] font-bold">✓</span>
                <span>بطاقة عرض للطبيب جاهزة للطباعة كـ PDF</span>
              </li>
              <li className="flex items-center gap-2">
                <span className="text-[#0D9488] font-bold">✓</span>
                <span>لا يستخدم التخزين المحلي للمتصفح نهائياً</span>
              </li>
            </ul>
          </div>

          <div className="mt-6 space-y-3">
            <button
              type="button"
              onClick={handleGuestStart}
              className="w-full rounded-2xl bg-[#0D9488] px-5 py-3.5 text-sm font-extrabold text-white shadow-md shadow-teal-600/20 hover:bg-teal-700 transition-colors cursor-pointer"
            >
              المتابعة كزائر بدون بيانات (Zero-PHI Guest Mode)
            </button>
            <p className="text-center text-[11px] text-slate-500 dark:text-slate-400">
              الوضع الحالي:{" "}
              <strong className="text-slate-800 dark:text-slate-200">
                {authUser.name}
              </strong>
            </p>
          </div>
        </section>

        {/* Login / Sign-Up Ephemeral Session Tabs */}
        <section className="lg:col-span-3 rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center gap-2 rounded-2xl bg-slate-100 p-1.5 dark:bg-slate-800">
            <button
              type="button"
              onClick={() => {
                setActiveTab("login");
                setFormNotice("");
              }}
              className={`flex-1 rounded-xl py-2.5 text-sm font-bold transition-all cursor-pointer ${
                activeTab === "login"
                  ? "bg-white text-slate-900 shadow-xs dark:bg-slate-900 dark:text-white"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-300"
              }`}
            >
              تسجيل الدخول
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTab("signup");
                setFormNotice("");
              }}
              className={`flex-1 rounded-xl py-2.5 text-sm font-bold transition-all cursor-pointer ${
                activeTab === "signup"
                  ? "bg-white text-slate-900 shadow-xs dark:bg-slate-900 dark:text-white"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-300"
              }`}
            >
              إنشاء حساب شخصي
            </button>
          </div>

          <div className="mt-5 rounded-xl border border-indigo-200 bg-indigo-50/70 px-4 py-3 text-xs text-indigo-950 dark:border-indigo-900/60 dark:bg-indigo-950/40 dark:text-indigo-200">
            <strong>ملاحظة الخصوصية:</strong> الحساب الشخصي هنا يعمل في ذاكرة
            الجلسة المؤقتة (RAM) فقط لتنظيم تفضيلات العرض دون كتابة أي بيانات
            صحية على القرص.
          </div>

          <form onSubmit={handlePersonalSubmit} className="mt-5 space-y-4">
            {activeTab === "signup" && (
              <div>
                <label
                  htmlFor="auth-name"
                  className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300"
                >
                  الاسم المعروض في الجلسة (اختياري أو اسم مستعار)
                </label>
                <input
                  id="auth-name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="مثال: زائر رقم 1"
                  autoComplete="off"
                  className="w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-indigo-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                />
              </div>
            )}

            <div>
              <label
                htmlFor="auth-email"
                className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300"
              >
                البريد الإلكتروني (لجلسة العرض المؤقتة)
              </label>
              <input
                id="auth-email"
                type="email"
                dir="ltr"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="patient@example.com"
                autoComplete="off"
                className="font-en w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-indigo-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            </div>

            <div>
              <label
                htmlFor="auth-password"
                className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300"
              >
                كلمة المرور
              </label>
              <input
                id="auth-password"
                type="password"
                dir="ltr"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="off"
                className="font-en w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-indigo-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            </div>

            {formNotice && (
              <p
                role="alert"
                className="rounded-xl bg-rose-50 px-3 py-2 text-xs font-bold text-rose-800 dark:bg-rose-950/60 dark:text-rose-200"
              >
                {formNotice}
              </p>
            )}

            <button
              type="submit"
              className="w-full rounded-2xl bg-[#4F46E5] px-5 py-3 text-sm font-bold text-white shadow-sm hover:bg-indigo-700 transition-colors cursor-pointer"
            >
              {activeTab === "login"
                ? "دخول وتجهيز الخزنة المؤقتة"
                : "إنشاء جلسة شخصية والانتقال للخزنة"}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
