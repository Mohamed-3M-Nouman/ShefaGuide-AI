import { useEffect } from "react";

const urgencyConfig = {
  1: {
    label: "المستوى 1 — إحالة روتينية (Routine Specialist)",
    badgeClass: "bg-emerald-100 text-emerald-800 border-emerald-300",
    borderClass: "border-emerald-500",
  },
  2: {
    label: "المستوى 2 — إحالة عاجلة (Urgent Specialist)",
    badgeClass: "bg-blue-100 text-blue-800 border-blue-300",
    borderClass: "border-blue-500",
  },
  3: {
    label: "المستوى 3 — حالة غير واضحة (Ambiguous / See Doctor)",
    badgeClass: "bg-amber-100 text-amber-800 border-amber-300",
    borderClass: "border-amber-500",
  },
  4: {
    label: "المستوى 4 — طوارئ قصوى (Emergency Escalation)",
    badgeClass: "bg-rose-100 text-rose-800 border-rose-300",
    borderClass: "border-rose-500",
  },
};

export default function DoctorPassModal({ isOpen, onClose, triageData, patientComplaint }) {
  useEffect(() => {
    function handleKeyDown(event) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !triageData) return null;

  const {
    session_id,
    urgency_level = 1,
    recommended_specialty,
    rationale_ar,
    negated_red_flags = [],
    citations = [],
    disclaimer_ar,
  } = triageData;

  const config = urgencyConfig[urgency_level] || urgencyConfig[1];
  const currentDate = new Date().toLocaleDateString("ar-EG", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  function handlePrint() {
    window.print();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-900/60 p-4 backdrop-blur-xs print:static print:p-0 print:bg-transparent"
    >
      <div className="relative my-8 w-full max-w-3xl rounded-2xl bg-white shadow-2xl ring-1 ring-slate-900/10 print:my-0 print:max-w-none print:rounded-none print:shadow-none print:ring-0">
        {/* Modal Action Bar (Hidden when printing) */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 print:hidden">
          <div className="flex items-center gap-2">
            <span className="flex h-3 w-3 rounded-full bg-teal-600 animate-pulse" />
            <h2 id="modal-title" className="text-lg font-bold text-slate-800">
              معاينة بطاقة العرض على الطبيب (Pre-Visit Pass)
            </h2>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handlePrint}
              className="flex items-center gap-2 rounded-xl bg-teal-700 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 transition-colors cursor-pointer"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"
                />
              </svg>
              <span>طباعة / حفظ كـ PDF</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 focus:outline-none transition-colors cursor-pointer"
            >
              إغلاق
            </button>
          </div>
        </div>

        {/* Printable Pass Body */}
        <div id="printable-doctor-pass" className="p-6 sm:p-8 space-y-6 text-slate-800 print:p-8">
          {/* Header */}
          <div className="flex items-start justify-between border-b-2 border-teal-700 pb-5">
            <div>
              <div className="flex items-center gap-2">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-700 text-white font-black text-xl">
                  شفاء
                </div>
                <div>
                  <h1 className="text-2xl font-black text-teal-900 tracking-tight">
                    ShefaGuide AI — شفاء جايد
                  </h1>
                  <p className="text-xs text-slate-500 font-medium">
                    بطاقة العرض المبدئي والتوجيه السريري (Clinical Pre-Visit Pass)
                  </p>
                </div>
              </div>
            </div>
            <div className="text-start sm:text-end">
              <span className="inline-block rounded-md bg-slate-100 px-2.5 py-1 text-xs font-mono text-slate-600">
                كود الجلسة: {session_id || "غير متوفر"}
              </span>
              <p className="mt-1 text-xs text-slate-500">{currentDate}</p>
            </div>
          </div>

          {/* Urgency & Specialty Callout */}
          <div className={`rounded-xl border-2 p-5 ${config.borderClass} bg-slate-50/50`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <span className="text-xs font-bold text-slate-500">التخصص الطبي الموصى بالعرض عليه:</span>
                <h3 className="mt-1 text-xl sm:text-2xl font-bold text-slate-900">
                  {recommended_specialty}
                </h3>
              </div>
              <span className={`rounded-full border px-3.5 py-1.5 text-xs font-bold ${config.badgeClass}`}>
                {config.label}
              </span>
            </div>
          </div>

          {/* Patient Complaint */}
          {patientComplaint && (
            <div className="rounded-xl bg-slate-100 p-4">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">
                ملخص شكوى المريض المسجلة:
              </h4>
              <p className="text-sm font-medium text-slate-800 leading-relaxed">
                {patientComplaint}
              </p>
            </div>
          )}

          {/* Rationale */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
              التفسير الطبي والتوجيه السريري الأولي:
            </h4>
            <p className="text-sm leading-7 text-slate-700 bg-white rounded-lg border border-slate-200 p-4">
              {rationale_ar}
            </p>
          </div>

          {/* Negated Red Flags */}
          {negated_red_flags.length > 0 && (
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                العلامات التحذيرية المنفية عند الفرز (Negated Red Flags):
              </h4>
              <div className="flex flex-wrap gap-2">
                {negated_red_flags.map((flag, idx) => (
                  <span
                    key={`${idx}-${flag}`}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-1 text-xs font-medium text-emerald-800"
                  >
                    <svg
                      className="h-3.5 w-3.5 text-emerald-600"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2.5}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    {flag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Clinical Citations */}
          {citations.length > 0 && (
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                الأدلة والمصادر الطبية المرجعية المعتمدة:
              </h4>
              <ul className="space-y-2 text-xs">
                {citations.map((cite, idx) => (
                  <li key={idx} className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
                    <div className="flex items-center justify-between font-semibold text-slate-800">
                      <span>{cite.title}</span>
                      <span className="rounded bg-teal-100 px-2 py-0.5 text-teal-800">
                        {cite.source}
                      </span>
                    </div>
                    {cite.snippet && (
                      <p className="mt-1 text-slate-600 leading-relaxed font-normal">
                        {cite.snippet}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Physician Notes Section for Physical Review */}
          <div className="rounded-xl border border-dashed border-slate-300 p-4 bg-slate-50/40">
            <h4 className="text-xs font-bold text-slate-600 mb-2">
              خانة خاصة بالطبيب المعالج (ملاحظات الفحص السريري والتوقيع):
            </h4>
            <div className="h-16 border-b border-slate-300" />
            <div className="mt-3 flex justify-between text-xs text-slate-500">
              <span>اسم الطبيب المعالج: .......................................</span>
              <span>توقيع الطبيب وخاتم العيادة: .......................................</span>
            </div>
          </div>

          {/* Disclaimer Footer */}
          <div className="border-t border-slate-200 pt-4 text-center">
            <p className="text-xs leading-5 text-slate-500">
              {disclaimer_ar ||
                "تنبيه طبي هام: هذا التقييم مبدئي وإرشادي فقط ولا يغني عن الفحص الطبي المباشر أو استشارة الطبيب المختص. في حالات الطوارئ يرجى التوجه لأقرب مستشفى أو الاتصال بالإسعاف (123) فوراً."}
            </p>
            <p className="mt-2 text-[10px] text-slate-400">
              نظام شفاء جايد مدعوم ببروتوكولات الفرز الذكي الآمن — صفر بيانات شخصية محفوظة (Zero-PHI Compliant)
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
