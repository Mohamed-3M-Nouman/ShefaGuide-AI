import { useEffect } from "react";
import { useApp } from "../context/appContext";
import BrandLogo from "./BrandLogo";

const URGENCY_CONFIG = {
  1: {
    label: "المستوى 1 — إحالة روتينية (Routine Specialist)",
    badgeClass: "bg-emerald-100 text-emerald-900 border-emerald-300",
    borderClass: "border-[#16A34A]",
  },
  2: {
    label: "المستوى 2 — إحالة عاجلة (Urgent Specialist)",
    badgeClass: "bg-sky-100 text-sky-900 border-sky-300",
    borderClass: "border-[#0284C7]",
  },
  3: {
    label: "المستوى 3 — حالة غير واضحة (راجع طبيباً الآن)",
    badgeClass: "bg-orange-100 text-orange-900 border-orange-300",
    borderClass: "border-[#EA580C]",
  },
  4: {
    label: "المستوى 4 — طوارئ قصوى (Emergency Escalation)",
    badgeClass: "bg-red-100 text-red-900 border-red-300",
    borderClass: "border-[#DC2626]",
  },
};

export default function DoctorPassModal(props) {
  const { modalState, closeDoctorPass, patientVault } = useApp();

  const isOpen = props.isOpen !== undefined ? props.isOpen : modalState.isOpen;
  const onClose = props.onClose || closeDoctorPass;
  const triageData = props.triageData || modalState.triageData;
  const patientComplaint =
    props.patientComplaint !== undefined
      ? props.patientComplaint
      : modalState.patientComplaint;
  const vaultContext = props.patientContext || modalState.patientContext || patientVault;

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

  const detectedRedFlags =
    triageData.detected_red_flags || triageData.red_flags_detected || [];

  const config = URGENCY_CONFIG[urgency_level] || URGENCY_CONFIG[1];
  const currentDate = new Date().toLocaleDateString("ar-EG", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  const hasVaultContext = Boolean(
    vaultContext &&
      (vaultContext.age ||
        vaultContext.gender ||
        vaultContext.governorate ||
        (vaultContext.chronicConditions && vaultContext.chronicConditions.length > 0) ||
        vaultContext.allergies)
  );

  function handlePrint() {
    window.print();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-900/70 p-4 backdrop-blur-xs print:static print:p-0 print:bg-transparent"
    >
      <div className="relative my-8 w-full max-w-3xl rounded-2xl bg-white shadow-2xl ring-1 ring-slate-900/10 dark:bg-slate-900 dark:ring-slate-700 print:my-0 print:max-w-none print:rounded-none print:shadow-none print:ring-0">
        {/* Modal Action Bar (Hidden on print) */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-6 py-4 dark:border-slate-700 print:hidden">
          <div className="flex items-center gap-2">
            <span className="flex h-3 w-3 rounded-full bg-[#0D9488] animate-pulse" />
            <h2
              id="modal-title"
              className="text-base sm:text-lg font-bold text-slate-800 dark:text-slate-100"
            >
              بطاقة العرض الذكية على الطبيب (Pre-Visit Triage Pass)
            </h2>
          </div>
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={handlePrint}
              className="flex items-center gap-2 rounded-xl bg-[#0D9488] px-4 py-2 text-sm font-bold text-white shadow-sm hover:bg-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-500 transition-colors cursor-pointer"
            >
              <span>🖨️ طباعة / حفظ كـ PDF</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-slate-300 px-3.5 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800 transition-colors cursor-pointer"
            >
              إغلاق
            </button>
          </div>
        </div>

        {/* Printable Pass Body */}
        <div
          id="printable-doctor-pass"
          className="p-6 sm:p-8 space-y-5 text-slate-800 bg-white rounded-b-2xl print:p-6"
        >
          {/* Header */}
          <div className="flex flex-wrap items-start justify-between gap-4 border-b-2 border-[#0D9488] pb-4">
            <div className="flex items-center gap-3">
              <BrandLogo className="h-11 w-11 shrink-0" />
              <div>
                <h1 className="text-xl sm:text-2xl font-black text-slate-900">
                  شفاء جايد —{" "}
                  <span className="font-en text-[#0D9488]">ShefaGuide AI</span>
                </h1>
                <p className="text-xs text-slate-500 font-medium">
                  بطاقة العرض السريري المبدئي ما قبل الكشف (Pre-Visit Pass)
                </p>
              </div>
            </div>
            <div className="text-start sm:text-end">
              <span className="font-en inline-block rounded-md bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">
                Session: {session_id || "N/A"}
              </span>
              <p className="mt-1 text-xs text-slate-500">{currentDate}</p>
            </div>
          </div>

          {/* Urgency & Specialty Callout */}
          <div className={`rounded-xl border-2 p-4 sm:p-5 ${config.borderClass} bg-slate-50`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <span className="text-xs font-bold text-slate-500">
                  التخصص الطبي الموصى بالعرض عليه:
                </span>
                <h3 className="mt-1 text-xl sm:text-2xl font-extrabold text-slate-900">
                  {recommended_specialty}
                </h3>
              </div>
              <span
                className={`rounded-full border px-3.5 py-1.5 text-xs font-bold ${config.badgeClass}`}
              >
                {config.label}
              </span>
            </div>
            {urgency_level === 4 && (
              <p className="mt-3 rounded-lg bg-red-100 px-3 py-2 text-xs font-bold text-red-900">
                🚨 تنبيه طوارئ قصوى: التوجه الفوري لأقرب قسم طوارئ أو الاتصال بالإسعاف (
                <a href="tel:123" className="font-en underline">
                  123
                </a>
                ).
              </p>
            )}
          </div>

          {/* Optional Ephemeral Context from RAM Vault */}
          {hasVaultContext && (
            <div className="rounded-xl border border-teal-200 bg-teal-50/50 p-4">
              <h4 className="text-xs font-bold text-teal-900 mb-2">
                سياق طبي مختصر (من الخزنة المؤقتة للجلسة فقط — Zero-PHI):
              </h4>
              <div className="flex flex-wrap gap-3 text-xs text-slate-700">
                {vaultContext.age && (
                  <span className="rounded-md bg-white px-2.5 py-1 border border-teal-200">
                    العمر: <strong>{vaultContext.age}</strong>
                  </span>
                )}
                {vaultContext.gender && (
                  <span className="rounded-md bg-white px-2.5 py-1 border border-teal-200">
                    النوع: <strong>{vaultContext.gender}</strong>
                  </span>
                )}
                {vaultContext.governorate && (
                  <span className="rounded-md bg-white px-2.5 py-1 border border-teal-200">
                    المحافظة: <strong>{vaultContext.governorate}</strong>
                  </span>
                )}
                {vaultContext.chronicConditions?.length > 0 && (
                  <span className="rounded-md bg-white px-2.5 py-1 border border-teal-200">
                    أمراض مزمنة:{" "}
                    <strong>{vaultContext.chronicConditions.join("، ")}</strong>
                  </span>
                )}
                {vaultContext.allergies && (
                  <span className="rounded-md bg-white px-2.5 py-1 border border-teal-200">
                    حساسية: <strong>{vaultContext.allergies}</strong>
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Patient Complaint */}
          {patientComplaint && (
            <div className="rounded-xl bg-slate-100 p-4">
              <h4 className="text-xs font-bold text-slate-500 mb-1">
                ملخص الشكوى الموصوفة (بدون بيانات تعريف شخصية):
              </h4>
              <p className="text-sm font-medium text-slate-800 leading-relaxed">
                {patientComplaint}
              </p>
            </div>
          )}

          {/* Rationale */}
          <div>
            <h4 className="text-xs font-bold text-slate-500 mb-1.5">
              التفسير السريري والتوجيه الأولي:
            </h4>
            <p className="text-sm leading-7 text-slate-700 rounded-xl border border-slate-200 bg-white p-4">
              {rationale_ar}
            </p>
          </div>

          {/* Detected Red Flags */}
          {detectedRedFlags.length > 0 && (
            <div>
              <h4 className="text-xs font-bold text-red-700 mb-2">
                علامات الخطر المرصودة (Detected Red Flags):
              </h4>
              <div className="flex flex-wrap gap-2">
                {detectedRedFlags.map((flag, idx) => (
                  <span
                    key={`${idx}-${flag}`}
                    className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-3 py-1 text-xs font-bold text-red-900"
                  >
                    ⚠️ {flag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Negated Red Flags */}
          {negated_red_flags.length > 0 && (
            <div>
              <h4 className="text-xs font-bold text-slate-500 mb-2">
                علامات تحذيرية تم نفيها عند الفرز (Negated Red Flags):
              </h4>
              <div className="flex flex-wrap gap-2">
                {negated_red_flags.map((flag, idx) => (
                  <span
                    key={`${idx}-${flag}`}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-800"
                  >
                    ✓ {flag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Clinical Citations */}
          {citations.length > 0 && (
            <div>
              <h4 className="text-xs font-bold text-slate-500 mb-2">
                المصادر الطبية المرجعية المعتمدة:
              </h4>
              <ul className="space-y-2 text-xs">
                {citations.map((cite, idx) => (
                  <li
                    key={`${cite.doc_id || idx}-${idx}`}
                    className="rounded-lg border border-slate-200 bg-slate-50 p-3"
                  >
                    <div className="flex items-center justify-between gap-2 font-semibold text-slate-800">
                      <bdi className="font-en">{cite.title}</bdi>
                      <span className="font-en shrink-0 rounded bg-teal-100 px-2 py-0.5 text-teal-800">
                        {cite.source}
                      </span>
                    </div>
                    {cite.snippet && (
                      <p className="mt-1 text-slate-600 leading-relaxed font-en">
                        <bdi>{cite.snippet}</bdi>
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Physician Notes Section */}
          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/50 p-4">
            <h4 className="text-xs font-bold text-slate-600 mb-2">
              خانة خاصة بالطبيب المعالج (ملاحظات الفحص السريري والتوقيع):
            </h4>
            <div className="h-14 border-b border-slate-300" />
            <div className="mt-3 flex flex-wrap justify-between gap-2 text-xs text-slate-500">
              <span>اسم الطبيب المعالج: .......................................</span>
              <span>توقيع الطبيب وخاتم العيادة: .......................................</span>
            </div>
          </div>

          {/* Disclaimer Footer */}
          <div className="border-t border-slate-200 pt-3 text-center">
            <p className="text-xs leading-5 text-slate-600">
              {disclaimer_ar ||
                "تنبيه طبي هام: هذا التقييم مبدئي وإرشادي فقط ولا يغني عن الفحص الطبي المباشر أو استشارة الطبيب المختص. في حالات الطوارئ يرجى التوجه لأقرب مستشفى أو الاتصال بالإسعاف (123) فوراً."}
            </p>
            <p className="mt-1.5 text-[10px] text-slate-400">
              نظام شفاء جايد — بطاقة مؤقتة خالية من أي بيانات تعريف شخصية (Zero-PHI Compliant)
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
