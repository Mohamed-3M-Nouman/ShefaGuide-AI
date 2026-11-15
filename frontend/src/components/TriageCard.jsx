import { useState, useRef, useEffect } from "react";
import { synthesizeVoice } from "../services/api";
import DoctorPassModal from "./DoctorPassModal";

const urgencyStyles = {
  1: {
    label: "إحالة روتينية",
    classes: "border-green-600 bg-green-50 text-green-950",
    badgeClasses: "bg-green-100 text-green-900 border-green-300",
  },
  2: {
    label: "إحالة عاجلة",
    classes: "border-blue-600 bg-blue-50 text-blue-950",
    badgeClasses: "bg-blue-100 text-blue-900 border-blue-300",
  },
  3: {
    label: "حالة غير واضحة — راجع طبيبًا الآن",
    classes: "border-orange-600 bg-orange-50 text-orange-950",
    badgeClasses: "bg-orange-100 text-orange-900 border-orange-300",
  },
  4: {
    label: "طوارئ",
    classes: "border-red-600 bg-red-50 text-red-950",
    badgeClasses: "bg-red-100 text-red-900 border-red-300",
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

export default function TriageCard({ response, patientComplaint }) {
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [isLoadingAudio, setIsLoadingAudio] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const audioRef = useRef(null);

  // Clean up audio on unmount
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
    ? urgencyStyles[4]
    : urgencyStyles[urgency_level] ?? {
        label: "مستوى غير معروف",
        classes: "border-slate-400 bg-slate-50 text-slate-950",
        badgeClasses: "bg-slate-100 text-slate-800 border-slate-300",
      };

  const finalDisclaimer =
    disclaimer_ar ||
    "تنبيه طبي هام: هذا التقييم مبدئي وإرشادي فقط ولا يغني عن الفحص الطبي المباشر أو استشارة الطبيب المختص. في حالات الطوارئ يرجى التوجه لأقرب مستشفى أو الاتصال بالإسعاف (123) فوراً.";

  // Browser SpeechSynthesis fallback
  function playBrowserSpeechSynthesis(textToSpeak) {
    if (!("speechSynthesis" in window)) {
      alert("خاصية نطق النصوص غير مدعومة في متصفحك حالياً.");
      setIsPlayingAudio(false);
      setIsLoadingAudio(false);
      return;
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(textToSpeak);
    utterance.lang = "ar-SA";
    utterance.rate = 0.95;

    // Pick Arabic voice if available
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

  // Handle Play/Stop Audio
  async function handleAudioPlayback() {
    // If currently playing, stop it
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
      // 1. Try server synthesis
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
          // If audio payload fails to play, fallback to browser speech synthesis
          playBrowserSpeechSynthesis(textToSynthesize);
        };

        await audio.play();
      } else {
        // Fallback to browser speech synthesis
        playBrowserSpeechSynthesis(textToSynthesize);
      }
    } catch {
      // In case of backend synthesis error, seamlessly fallback to browser speech synthesis
      playBrowserSpeechSynthesis(textToSynthesize);
    }
  }

  return (
    <>
      <article
        aria-label={`نتيجة الفرز: ${style.label}`}
        className={`rounded-2xl border-2 p-4 sm:p-5 shadow-sm transition-all ${style.classes}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-current/15 pb-3">
          <span
            className={`inline-block rounded-full border px-3 py-0.5 text-xs font-bold ${style.badgeClasses}`}
          >
            {style.label}
          </span>
          {session_id && (
            <span className="text-xs font-mono opacity-60">
              جلسة: {session_id}
            </span>
          )}
        </div>

        <h2 className={`mt-3 font-bold ${isEmergency ? "text-2xl" : "text-xl"}`}>
          {recommended_specialty}
        </h2>

        <p className="mt-3 leading-8">{rationale_ar}</p>

        {isEmergency && (
          <div className="mt-4 rounded-xl bg-red-100/90 border border-red-300 p-3.5">
            <p className="text-base sm:text-lg font-bold leading-7 text-red-900">
              🚨{" "}
              {escalation_note ||
                "يرجى التوجه فوراً لأقرب قسم طوارئ مستشفى أو الاتصال بالإسعاف (123)."}
            </p>
          </div>
        )}

        {isEmergency && redFlags.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-bold text-red-900">
              علامات الخطر المرصودة (Red Flags):
            </h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {redFlags.map((flag, idx) => (
                <span
                  key={`${idx}-${flag}`}
                  className="inline-flex items-center rounded-full bg-red-200/90 px-3 py-1 text-xs font-bold text-red-900 shadow-xs"
                >
                  ⚠️ {flag}
                </span>
              ))}
            </div>
          </div>
        )}

        {negated_red_flags.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-bold text-slate-800">
              علامات تحذيرية تم التحقق من نفيها:
            </h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {negated_red_flags.map((flag, idx) => (
                <span
                  key={`${idx}-${flag}`}
                  className="inline-flex items-center rounded-lg bg-white/70 px-2.5 py-1 text-xs font-medium text-slate-800 border border-slate-200"
                >
                  ✓ {flag}
                </span>
              ))}
            </div>
          </div>
        )}

        {!isEmergency && clarifying_questions.length > 0 && (
          <div className="mt-4 rounded-xl bg-white/60 p-3.5 border border-current/10">
            <h3 className="font-bold text-sm">أسئلة توضيحية لتقييم أدق:</h3>
            <ul className="mt-2 list-disc space-y-1.5 ps-5 text-sm">
              {clarifying_questions.map((question, index) => (
                <li key={`${index}-${question}`}>{question}</li>
              ))}
            </ul>
          </div>
        )}

        {citations.length > 0 && (
          <div className="mt-4">
            <h3 className="font-bold text-sm">المصادر الطبية المرجعية:</h3>
            <ul className="mt-2 space-y-2">
              {citations.map((citation, index) => {
                const href = getSafeUrl(citation.url);

                return (
                  <li
                    key={`${citation.doc_id || index}-${index}`}
                    className="rounded-lg bg-white/80 p-3 shadow-xs border border-current/10"
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

        {/* Action Buttons: Voice Output & Doctor Pass PDF */}
        <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-current/20 pt-4">
          <button
            type="button"
            onClick={handleAudioPlayback}
            disabled={isLoadingAudio}
            className="flex items-center gap-2 rounded-xl bg-white px-3.5 py-2 text-xs sm:text-sm font-bold text-slate-800 shadow-sm hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-teal-500 transition-colors border border-slate-300 disabled:opacity-50 cursor-pointer"
          >
            {isLoadingAudio ? (
              <>
                <svg
                  className="animate-spin h-4 w-4 text-teal-600"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v8H4z"
                  />
                </svg>
                <span>جاري تحميل الصوت...</span>
              </>
            ) : isPlayingAudio ? (
              <>
                <span className="flex h-2.5 w-2.5 rounded-full bg-red-600 animate-ping" />
                <span>⏹ إيقاف الصوت</span>
              </>
            ) : (
              <>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-4 w-4 text-teal-700"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                  <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07" />
                </svg>
                <span>🔊 سماع التوجيه صوتياً</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={() => setIsModalOpen(true)}
            className="flex items-center gap-2 rounded-xl bg-teal-700 px-3.5 py-2 text-xs sm:text-sm font-bold text-white shadow-sm hover:bg-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-1 transition-colors cursor-pointer"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <span>📄 طباعة / حفظ بطاقة العرض على الطبيب (PDF)</span>
          </button>
        </div>

        <p className="mt-4 border-t border-current/15 pt-3 text-xs leading-6 opacity-80">
          {finalDisclaimer}
        </p>
      </article>

      {/* Doctor Pass Modal for viewing and printing */}
      <DoctorPassModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        triageData={response}
        patientComplaint={patientComplaint}
      />
    </>
  );
}
