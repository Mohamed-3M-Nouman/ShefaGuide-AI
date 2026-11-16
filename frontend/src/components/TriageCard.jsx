import { useState, useRef, useEffect } from "react";
import { synthesizeVoice } from "../services/api";
import { useApp } from "../context/appContext";

const URGENCY_STYLES = {
  1: {
    label: "المستوى 1 — إحالة روتينية",
    classes:
      "border-[#16A34A] bg-emerald-50/90 text-emerald-950 dark:bg-emerald-950/35 dark:text-emerald-50",
    badgeClasses:
      "bg-emerald-100 text-emerald-900 border-emerald-300 dark:bg-emerald-900/70 dark:text-emerald-200 dark:border-emerald-700",
  },
  2: {
    label: "المستوى 2 — إحالة عاجلة",
    classes:
      "border-[#0284C7] bg-sky-50/90 text-sky-950 dark:bg-sky-950/35 dark:text-sky-50",
    badgeClasses:
      "bg-sky-100 text-sky-900 border-sky-300 dark:bg-sky-900/70 dark:text-sky-200 dark:border-sky-700",
  },
  3: {
    label: "المستوى 3 — حالة غير واضحة — راجع طبيباً الآن",
    classes:
      "border-[#EA580C] bg-orange-50/90 text-orange-950 dark:bg-orange-950/35 dark:text-orange-50",
    badgeClasses:
      "bg-orange-100 text-orange-900 border-orange-300 dark:bg-orange-900/70 dark:text-orange-200 dark:border-orange-700",
  },
  4: {
    label: "المستوى 4 — طوارئ قصوى",
    classes:
      "border-[#DC2626] bg-red-50/95 text-red-950 dark:bg-red-950/40 dark:text-red-50",
    badgeClasses:
      "bg-red-100 text-red-900 border-red-300 dark:bg-red-900/80 dark:text-red-100 dark:border-red-700",
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

export default function TriageCard({
  response,
  patientComplaint,
  onSelectClarifyingQuestion,
}) {
  const { openDoctorPass } = useApp();
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [isLoadingAudio, setIsLoadingAudio] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  if (!response) return null;

  const {
    session_id,
    urgency_level,
    recommended_specialty,
    rationale_ar,
    clarifying_questions = [],
    negated_red_flags = [],
    citations = [],
    disclaimer_ar,
    escalation_triggered,
    escalation_note,
  } = response;

  const redFlags =
    response.detected_red_flags || response.red_flags_detected || [];

  const isEmergency = urgency_level === 4 || escalation_triggered === true;

  const style = isEmergency
    ? URGENCY_STYLES[4]
    : URGENCY_STYLES[urgency_level] ?? {
        label: "توجيه مبدئي",
        classes:
          "border-slate-400 bg-white text-slate-950 dark:bg-slate-900 dark:text-slate-100",
        badgeClasses:
          "bg-slate-100 text-slate-800 border-slate-300 dark:bg-slate-800 dark:text-slate-200",
      };

  const finalDisclaimer =
    disclaimer_ar ||
    "تنبيه طبي هام: هذا التقييم مبدئي وإرشادي فقط ولا يغني عن الفحص الطبي المباشر أو استشارة الطبيب المختص. في حالات الطوارئ يرجى التوجه لأقرب مستشفى أو الاتصال بالإسعاف (123) فوراً.";

  function playBrowserSpeechSynthesis(textToSpeak) {
    if (!("speechSynthesis" in window)) {
      setIsPlayingAudio(false);
      setIsLoadingAudio(false);
      return;
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(textToSpeak);
    utterance.lang = "ar-EG";
    utterance.rate = 0.95;

    const voices = window.speechSynthesis.getVoices();
    const arabicVoice = voices.find((v) => v.lang.startsWith("ar"));
    if (arabicVoice) {
      utterance.voice = arabicVoice;
    }

    utterance.onstart = () => {
      setIsPlayingAudio(true);
      setIsLoadingAudio(false);
    };
    utterance.onend = () => {
      setIsPlayingAudio(false);
      setIsLoadingAudio(false);
    };
    utterance.onerror = () => {
      setIsPlayingAudio(false);
      setIsLoadingAudio(false);
    };

    window.speechSynthesis.speak(utterance);
  }

  async function handleAudioPlayback() {
    if (isPlayingAudio) {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
      }
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      setIsPlayingAudio(false);
      return;
    }

    setIsLoadingAudio(true);
    const textToSynthesize = `${rationale_ar || ""}\n\n${finalDisclaimer}`.trim();

    try {
      const synthResult = await synthesizeVoice({
        session_id: session_id || "client-voice",
        text: rationale_ar || "إرشادات الفرز الطبي المبدئي",
        include_disclaimer: true,
      });

      if (synthResult?.audio_base64) {
        const audioMime = synthResult.mime_type || "audio/wav";
        const audioSrc = `data:${audioMime};base64,${synthResult.audio_base64}`;
        if (audioRef.current) {
          audioRef.current.pause();
        }
        const audio = new Audio(audioSrc);
        audioRef.current = audio;

        audio.onplay = () => {
          setIsPlayingAudio(true);
          setIsLoadingAudio(false);
        };
        audio.onended = () => {
          setIsPlayingAudio(false);
          setIsLoadingAudio(false);
        };
        audio.onerror = () => {
          playBrowserSpeechSynthesis(textToSynthesize);
        };
        await audio.play();
      } else {
        playBrowserSpeechSynthesis(textToSynthesize);
      }
    } catch {
      playBrowserSpeechSynthesis(textToSynthesize);
    }
  }

  return (
    <article
      aria-label={`نتيجة الفرز: ${style.label}`}
      className={`rounded-3xl border-2 p-5 sm:p-6 shadow-sm transition-all ${style.classes}`}
    >
      {/* Top Badge + Session ID */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-current/15 pb-3">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-0.5 text-xs font-extrabold ${style.badgeClasses}`}
        >
          {isEmergency ? "🚨" : "🩺"}
          <span>{style.label}</span>
        </span>
        {session_id && (
          <span className="font-en text-xs opacity-70" dir="ltr">
            {session_id}
          </span>
        )}
      </div>

      {/* Specialty & Rationale */}
      <h2 className={`mt-3 font-black ${isEmergency ? "text-2xl" : "text-xl"}`}>
        {recommended_specialty}
      </h2>
      <p className="mt-2.5 text-sm sm:text-base leading-8">{rationale_ar}</p>

      {/* Level 4 Emergency Callout with clickable tel:123 */}
      {isEmergency && (
        <div className="mt-4 rounded-2xl border border-red-300 bg-red-100/90 p-4 text-red-950 dark:border-red-800 dark:bg-red-900/50 dark:text-red-50">
          <p className="text-sm sm:text-base font-extrabold leading-7">
            🚨{" "}
            {escalation_note ||
              "يرجى التوجه فوراً لأقرب قسم طوارئ مستشفى أو الاتصال بالإسعاف فوراً:"}{" "}
            <a
              href="tel:123"
              className="font-en inline-flex items-center gap-1 rounded-lg bg-red-700 px-2.5 py-0.5 text-sm font-black text-white underline-offset-2 hover:bg-red-800"
            >
              📞 123
            </a>
          </p>
        </div>
      )}

      {/* Detected Red Flags */}
      {isEmergency && redFlags.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs sm:text-sm font-extrabold text-red-900 dark:text-red-200">
            علامات الخطر المرصودة (Red Flags):
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {redFlags.map((flag, idx) => (
              <span
                key={`${idx}-${flag}`}
                className="inline-flex items-center rounded-full bg-red-200/90 px-3 py-1 text-xs font-bold text-red-950 dark:bg-red-900/80 dark:text-red-100"
              >
                ⚠️ {flag}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Negated Red Flags */}
      {negated_red_flags.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs sm:text-sm font-bold opacity-85">
            علامات تحذيرية تم نفيها:
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {negated_red_flags.map((flag, idx) => (
              <span
                key={`${idx}-${flag}`}
                className="inline-flex items-center rounded-lg border border-current/15 bg-white/75 px-2.5 py-1 text-xs font-semibold text-slate-800 dark:bg-slate-900/70 dark:text-slate-200"
              >
                ✓ {flag}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Clarifying Questions */}
      {!isEmergency && clarifying_questions.length > 0 && (
        <div className="mt-4 rounded-2xl border border-current/15 bg-white/70 p-4 dark:bg-slate-900/60">
          <h3 className="font-extrabold text-xs sm:text-sm">
            أسئلة توضيحية لتقييم أدق (اضغط للإجابة السريعة):
          </h3>
          <ul className="mt-2.5 space-y-1.5 text-xs sm:text-sm">
            {clarifying_questions.map((question, index) => (
              <li key={`${index}-${question}`}>
                {onSelectClarifyingQuestion ? (
                  <button
                    type="button"
                    onClick={() => onSelectClarifyingQuestion(question)}
                    className="text-start font-medium hover:underline cursor-pointer"
                  >
                    • {question}
                  </button>
                ) : (
                  <span>• {question}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Evidence-Based Citations */}
      {citations.length > 0 && (
        <div className="mt-4">
          <h3 className="font-extrabold text-xs sm:text-sm">
            المصادر الطبية المرجعية:
          </h3>
          <ul className="mt-2 space-y-2">
            {citations.map((citation, index) => {
              const href = getSafeUrl(citation.url);
              return (
                <li
                  key={`${citation.doc_id || index}-${index}`}
                  className="rounded-xl border border-current/10 bg-white/85 p-3 shadow-xs dark:bg-slate-900/75"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-en text-xs sm:text-sm font-bold underline underline-offset-4 hover:no-underline text-[#0284C7] dark:text-sky-300"
                      >
                        <bdi>{citation.title}</bdi>
                      </a>
                    ) : (
                      <span className="font-en text-xs sm:text-sm font-bold">
                        <bdi>{citation.title}</bdi>
                      </span>
                    )}
                    <span className="font-en inline-block rounded-md bg-slate-200 px-2 py-0.5 text-[11px] font-bold text-slate-800 dark:bg-slate-800 dark:text-slate-200">
                      {citation.source}
                    </span>
                  </div>
                  {citation.snippet && (
                    <p className="font-en mt-1.5 text-xs leading-5 opacity-80">
                      <bdi>{citation.snippet}</bdi>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Action Buttons */}
      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-current/15 pt-4">
        <button
          type="button"
          onClick={handleAudioPlayback}
          disabled={isLoadingAudio}
          className="inline-flex items-center gap-2 rounded-xl border border-indigo-200 bg-white px-4 py-2 text-xs sm:text-sm font-bold text-[#4F46E5] shadow-xs hover:bg-indigo-50 disabled:opacity-50 dark:border-indigo-800 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-950/60 transition-colors cursor-pointer"
        >
          {isLoadingAudio ? (
            <span>جاري توليد الصوت...</span>
          ) : isPlayingAudio ? (
            <>
              <span className="h-2.5 w-2.5 rounded-full bg-red-600 animate-ping" />
              <span>⏹ إيقاف الصوت</span>
            </>
          ) : (
            <span>🔊 سماع التوجيه صوتياً</span>
          )}
        </button>

        <button
          type="button"
          onClick={() => openDoctorPass(response, patientComplaint)}
          className="inline-flex items-center gap-2 rounded-xl bg-[#0D9488] px-4 py-2 text-xs sm:text-sm font-bold text-white shadow-xs hover:bg-teal-700 transition-colors cursor-pointer"
        >
          <span>📄 بطاقة العرض على الطبيب (PDF)</span>
        </button>
      </div>

      {/* Persistent Per-Card Medical Disclaimer */}
      <p className="mt-4 border-t border-current/15 pt-3 text-xs leading-6 opacity-85">
        {finalDisclaimer}
      </p>
    </article>
  );
}
