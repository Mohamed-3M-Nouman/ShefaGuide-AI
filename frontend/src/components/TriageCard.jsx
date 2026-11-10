const urgencyStyles = {
  1: {
    label: "إحالة روتينية",
    classes: "border-green-600 bg-green-50 text-green-950",
  },
  2: {
    label: "إحالة عاجلة",
    classes: "border-blue-600 bg-blue-50 text-blue-950",
  },
  3: {
    label: "حالة غير واضحة — راجع طبيبًا الآن",
    classes: "border-orange-600 bg-orange-50 text-orange-950",
  },
  4: {
    label: "طوارئ",
    classes: "border-red-600 bg-red-50 text-red-950",
  },
};

function getSafeUrl(value) {
  try {
    const url = new URL(value);

    if (url.protocol === "https:" || url.protocol === "http:") {
      return url.href;
    }
  } catch {
    return null;
  }

  return null;
}

export default function TriageCard({ response }) {
  if (!response) return null;

  const {
    urgency_level,
    recommended_specialty,
    rationale_ar,
    clarifying_questions = [],
    citations = [],
    disclaimer_ar,
    escalation_triggered,
    escalation_note,
  } = response;

  const redFlags =
    response.detected_red_flags || response.red_flags_detected || [];

  const isEmergency = urgency_level === 4 || escalation_triggered === true;

  const style = isEmergency
    ? urgencyStyles[4]
    : (urgencyStyles[urgency_level] ?? {
        label: "مستوى غير معروف",
        classes: "border-slate-400 bg-slate-50 text-slate-950",
      });

  return (
    <article
      aria-label={`نتيجة الفرز: ${style.label}`}
      className={`rounded-2xl border-2 p-4 sm:p-5 ${style.classes}`}
    >
      <p className="text-sm font-bold">{style.label}</p>

      <h2 className={`mt-2 font-bold ${isEmergency ? "text-2xl" : "text-xl"}`}>
        {recommended_specialty}
      </h2>

      <p className="mt-3 leading-8">{rationale_ar}</p>

      {isEmergency && (
        <p className="mt-4 text-lg font-bold leading-8 text-red-900">
          {escalation_note ||
            "يرجى التوجه فوراً لأقرب قسم طوارئ مستشفى أو الاتصال بالإسعاف (123)."}
        </p>
      )}

      {isEmergency && redFlags.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-bold text-red-900">
            علامات الخطر المرصودة:
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {redFlags.map((flag, idx) => (
              <span
                key={`${idx}-${flag}`}
                className="inline-flex items-center rounded-full bg-red-200 px-3 py-1 text-xs font-bold text-red-900"
              >
                {flag}
              </span>
            ))}
          </div>
        </div>
      )}

      {!isEmergency && clarifying_questions.length > 0 && (
        <div className="mt-4">
          <h3 className="font-bold">أسئلة توضيحية</h3>

          <ul className="mt-2 list-disc space-y-2 ps-5">
            {clarifying_questions.map((question, index) => (
              <li key={`${index}-${question}`}>{question}</li>
            ))}
          </ul>
        </div>
      )}

      {citations.length > 0 && (
        <div className="mt-4">
          <h3 className="font-bold">المصادر الطبية</h3>

          <ul className="mt-2 space-y-2">
            {citations.map((citation, index) => {
              const href = getSafeUrl(citation.url);

              return (
                <li
                  key={`${citation.doc_id || index}-${index}`}
                  className="rounded-lg bg-white/60 p-2.5"
                >
                  <div>
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="rounded font-medium underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2"
                      >
                        <bdi>{citation.title}</bdi>
                        {" — "}
                        <span className="inline-block rounded bg-slate-200 px-1.5 py-0.5 text-xs font-semibold text-slate-800">
                          {citation.source}
                        </span>
                      </a>
                    ) : (
                      <span className="font-medium">
                        <bdi>{citation.title}</bdi>
                        {" — "}
                        <span className="inline-block rounded bg-slate-200 px-1.5 py-0.5 text-xs font-semibold text-slate-800">
                          {citation.source}
                        </span>
                      </span>
                    )}
                  </div>
                  {citation.snippet && (
                    <p className="mt-1 text-xs leading-5 text-slate-600">
                      <bdi>{citation.snippet}</bdi>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <p className="mt-5 border-t border-current/20 pt-3 text-sm leading-7">
        {disclaimer_ar ||
          "تنبيه طبي: هذا التوجيه إرشادي فقط ولا يغني عن الفحص الطبي المباشر."}
      </p>
    </article>
  );
}
