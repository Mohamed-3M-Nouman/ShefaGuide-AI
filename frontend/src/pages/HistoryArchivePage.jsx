import { useState } from "react";
import { Link } from "react-router";
import { useApp } from "../context/appContext";

const BADGE_MAP = {
  1: {
    label: "المستوى 1 — روتيني",
    cls: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  },
  2: {
    label: "المستوى 2 — عاجل",
    cls: "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200",
  },
  3: {
    label: "المستوى 3 — راجع طبيباً",
    cls: "bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-200",
  },
  4: {
    label: "المستوى 4 — طوارئ",
    cls: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
  },
};

export default function HistoryArchivePage() {
  const { savedPasses, openDoctorPass, loadSamplePasses, wipeAllMemory } =
    useApp();
  const [urgencyFilter, setUrgencyFilter] = useState("all");

  const filteredPasses = savedPasses.filter((item) => {
    if (urgencyFilter === "all") return true;
    return String(item.triageData?.urgency_level) === urgencyFilter;
  });

  return (
    <main className="min-h-0 flex-1 overflow-y-auto bg-[#F8FAFC] dark:bg-[#0F172A] px-4 py-8 sm:px-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 pb-5 dark:border-slate-800">
          <div>
            <h1 className="text-2xl font-black text-slate-900 dark:text-white">
              أرشيف بطاقات العرض على الطبيب (الجلسة الحالية)
            </h1>
            <p className="mt-1 text-xs sm:text-sm text-slate-600 dark:text-slate-400">
              جميع البطاقات محفوظة مؤقتاً في ذاكرة التشغيل (RAM) فقط وتُمحى تلقائياً عند إغلاق التبويب.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={loadSamplePasses}
              className="rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 cursor-pointer"
            >
              ✨ تحميل نماذج استرشادية للمعاينة
            </button>
            {savedPasses.length > 0 && (
              <button
                type="button"
                onClick={wipeAllMemory}
                className="rounded-xl border border-rose-300 bg-rose-50 px-3.5 py-2 text-xs font-bold text-rose-700 hover:bg-rose-100 dark:border-rose-800 dark:bg-rose-950/50 dark:text-rose-200 cursor-pointer"
              >
                🗑️ مسح الأرشيف فوراً
              </button>
            )}
          </div>
        </header>

        {/* Urgency Filter Pills */}
        <div className="flex flex-wrap items-center gap-2">
          {[
            { id: "all", label: `الكل (${savedPasses.length})` },
            { id: "4", label: "طوارئ (4)" },
            { id: "2", label: "عاجلة (2)" },
            { id: "3", label: "غير واضحة (3)" },
            { id: "1", label: "روتينية (1)" },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setUrgencyFilter(tab.id)}
              className={`rounded-full px-3.5 py-1.5 text-xs font-bold transition-colors cursor-pointer ${
                urgencyFilter === tab.id
                  ? "bg-[#0D9488] text-white"
                  : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-300 dark:border-slate-800"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Empty State */}
        {filteredPasses.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-slate-300 bg-white p-10 text-center dark:border-slate-700 dark:bg-slate-900">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-teal-50 text-2xl dark:bg-teal-950/60">
              📄
            </div>
            <h2 className="text-lg font-extrabold text-slate-900 dark:text-white">
              لا توجد بطاقات فرز في الذاكرة الحالية بعد
            </h2>
            <p className="mx-auto mt-1.5 max-w-md text-xs sm:text-sm text-slate-500 dark:text-slate-400">
              ابدأ محادثة فرز جديدة وسيتم تجميع كل بطاقات العرض على الطبيب هنا لفتحها أو طباعتها بضغطة واحدة.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-3">
              <Link
                to="/triage"
                className="rounded-xl bg-[#0D9488] px-5 py-2.5 text-xs sm:text-sm font-bold text-white hover:bg-teal-700"
              >
                الانتقال لمساحة الفرز ←
              </Link>
              <button
                type="button"
                onClick={loadSamplePasses}
                className="rounded-xl border border-slate-300 px-5 py-2.5 text-xs sm:text-sm font-bold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 cursor-pointer"
              >
                عرض 4 بطاقات نموذجية
              </button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {filteredPasses.map((item) => {
              const urg = item.triageData?.urgency_level || 1;
              const badge = BADGE_MAP[urg] || BADGE_MAP[1];
              return (
                <article
                  key={item.passId}
                  className="flex flex-col justify-between rounded-2xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900"
                >
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${badge.cls}`}
                      >
                        {badge.label}
                      </span>
                      <span className="font-en text-[11px] text-slate-400" dir="ltr">
                        {item.sessionId}
                      </span>
                    </div>

                    <h2 className="mt-3 text-base font-extrabold text-slate-900 dark:text-white">
                      {item.triageData?.recommended_specialty}
                    </h2>

                    <p className="mt-2 rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-700 line-clamp-2 dark:bg-slate-800/70 dark:text-slate-300">
                      {item.patientComplaint}
                    </p>

                    <p className="mt-2 text-xs leading-5 text-slate-500 line-clamp-2 dark:text-slate-400">
                      {item.triageData?.rationale_ar}
                    </p>
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 dark:border-slate-800">
                    <span className="text-[11px] text-slate-400">
                      {new Date(item.createdAt).toLocaleTimeString("ar-EG", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        openDoctorPass(
                          item.triageData,
                          item.patientComplaint,
                          item.patientVaultSnapshot
                        )
                      }
                      className="rounded-xl bg-[#0D9488] px-3.5 py-1.5 text-xs font-bold text-white hover:bg-teal-700 transition-colors cursor-pointer"
                    >
                      📄 معاينة وطباعة (PDF)
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}
