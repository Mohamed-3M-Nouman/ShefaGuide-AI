import { useState } from "react";
import { useNavigate } from "react-router";
import { useApp } from "../context/appContext";

const CHRONIC_OPTIONS = [
  "السكري",
  "ضغط الدم المرتفع",
  "الربو / حساسية الصدر",
  "أمراض القلب",
  "اضطرابات الغدة الدرقية",
  "أمراض الكلى",
];

const GOVERNORATES = [
  "",
  "القاهرة",
  "الجيزة",
  "الإسكندرية",
  "الدقهلية",
  "الشرقية",
  "القليوبية",
  "المنوفية",
  "الغربية",
  "أسيوط",
  "المنيا",
  "سوهاج",
  "أخرى",
];

export default function ProfileVaultPage() {
  const navigate = useNavigate();
  const { patientVault, updatePatientVault, clearPatientVault } = useApp();
  const [savedNotice, setSavedNotice] = useState(false);

  function toggleCondition(condition) {
    const exists = patientVault.chronicConditions.includes(condition);
    const next = exists
      ? patientVault.chronicConditions.filter((c) => c !== condition)
      : [...patientVault.chronicConditions, condition];
    updatePatientVault({ chronicConditions: next });
    setSavedNotice(false);
  }

  function handleWipeVault() {
    clearPatientVault();
    setSavedNotice(false);
  }

  function handleSaveAndProceed(event) {
    event.preventDefault();
    setSavedNotice(true);
    navigate("/triage");
  }

  return (
    <main className="min-h-0 flex-1 overflow-y-auto bg-[#F8FAFC] dark:bg-[#0F172A] px-4 py-8">
      <div className="mx-auto max-w-3xl space-y-6">
        {/* Prominent Green Zero-PHI In-Memory Vault Banner */}
        <section className="rounded-3xl border-2 border-emerald-400 bg-emerald-50 p-5 sm:p-6 text-emerald-950 shadow-xs dark:border-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-100">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-emerald-600 text-white text-xl shadow-xs">
                🛡️
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-lg sm:text-xl font-black">
                    الخزنة الصحية المؤقتة (Zero-PHI In-Memory Vault)
                  </h1>
                  <span className="rounded-full bg-emerald-200 px-2.5 py-0.5 text-[11px] font-bold text-emerald-900 dark:bg-emerald-900 dark:text-emerald-200">
                    RAM فقط
                  </span>
                </div>
                <p className="mt-1.5 text-xs sm:text-sm leading-6 opacity-90">
                  هذه البيانات الاختيارية تبقى حصراً في ذاكرة التشغيل المؤقتة
                  (RAM) للجلسة الحالية لمساعدتك في عرض سياق مختصر على بطاقة
                  الطبيب. <strong>لا تُحفظ على الخوادم ولا في ذاكرة المتصفح الدائمة</strong>{" "}
                  وتُمسح تلقائياً فور تحديث أو إغلاق التبويب.
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={handleWipeVault}
              className="shrink-0 rounded-xl border border-rose-300 bg-white px-4 py-2 text-xs font-extrabold text-rose-700 shadow-xs hover:bg-rose-50 dark:border-rose-700 dark:bg-slate-900 dark:text-rose-300 dark:hover:bg-rose-950/60 transition-colors cursor-pointer"
            >
              🗑️ مسح بياناتي فوراً
            </button>
          </div>
        </section>

        {/* Optional Non-Identifying Context Form */}
        <form
          onSubmit={handleSaveAndProceed}
          className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs space-y-6 dark:border-slate-800 dark:bg-slate-900"
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label
                htmlFor="vault-age"
                className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300"
              >
                الفئة العمرية / العمر
              </label>
              <input
                id="vault-age"
                type="text"
                value={patientVault.age}
                onChange={(e) => updatePatientVault({ age: e.target.value })}
                placeholder="مثال: 34 سنة"
                autoComplete="off"
                className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none focus:border-[#0D9488] focus:ring-2 focus:ring-teal-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            </div>

            <div>
              <label
                htmlFor="vault-gender"
                className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300"
              >
                النوع
              </label>
              <select
                id="vault-gender"
                value={patientVault.gender}
                onChange={(e) => updatePatientVault({ gender: e.target.value })}
                className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none focus:border-[#0D9488] focus:ring-2 focus:ring-teal-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              >
                <option value="">غير محدد</option>
                <option value="ذكر">ذكر</option>
                <option value="أنثى">أنثى</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="vault-gov"
                className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300"
              >
                المحافظة (اختياري)
              </label>
              <select
                id="vault-gov"
                value={patientVault.governorate}
                onChange={(e) =>
                  updatePatientVault({ governorate: e.target.value })
                }
                className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none focus:border-[#0D9488] focus:ring-2 focus:ring-teal-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              >
                {GOVERNORATES.map((g) => (
                  <option key={g || "none"} value={g}>
                    {g || "غير محدد"}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Chronic Conditions Chips */}
          <div>
            <span className="mb-2 block text-xs font-bold text-slate-700 dark:text-slate-300">
              حالات مزمنة (تظهر فقط في بطاقة العرض على الطبيب أثناء الجلسة):
            </span>
            <div className="flex flex-wrap gap-2">
              {CHRONIC_OPTIONS.map((item) => {
                const selected = patientVault.chronicConditions.includes(item);
                return (
                  <button
                    key={item}
                    type="button"
                    onClick={() => toggleCondition(item)}
                    className={`rounded-full border px-3.5 py-1.5 text-xs font-bold transition-colors cursor-pointer ${
                      selected
                        ? "border-[#0D9488] bg-[#0D9488] text-white shadow-xs"
                        : "border-slate-300 bg-slate-50 text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                    }`}
                  >
                    {selected ? `✓ ${item}` : item}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Allergies */}
          <div>
            <label
              htmlFor="vault-allergies"
              className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300"
            >
              حساسية معروفة (أدوية أو أطعمة — اختياري)
            </label>
            <input
              id="vault-allergies"
              type="text"
              value={patientVault.allergies}
              onChange={(e) =>
                updatePatientVault({ allergies: e.target.value })
              }
              placeholder="مثال: حساسية من البنسلين أو المأكولات البحرية"
              autoComplete="off"
              className="w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none focus:border-[#0D9488] focus:ring-2 focus:ring-teal-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
            />
          </div>

          {savedNotice && (
            <p className="rounded-xl bg-emerald-50 px-4 py-2 text-xs font-bold text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-200">
              ✓ تم تحديث الذاكرة المؤقتة للجلسة بنجاح.
            </p>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 dark:border-slate-800">
            <button
              type="button"
              onClick={handleWipeVault}
              className="rounded-xl border border-slate-300 px-4 py-2.5 text-xs sm:text-sm font-bold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800 cursor-pointer"
            >
              مسح بياناتي فوراً
            </button>
            <button
              type="submit"
              className="rounded-2xl bg-[#0D9488] px-6 py-3 text-xs sm:text-sm font-extrabold text-white shadow-sm hover:bg-teal-700 transition-colors cursor-pointer"
            >
              حفظ في الذاكرة المؤقتة والانتقال للفرز ←
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}
