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

function splitSpeechChunks(text, maxLength = 220) {
  const normalized = (text || "").replace(/\s+/g, " ").trim();
  if (!normalized) return [];
  if (normalized.length <= maxLength) return [normalized];

  const sentences = normalized.split(/(?<=[.!؟?\n])\s+/);
  const chunks = [];
  let current = "";

  for (const sentence of sentences) {
    if (!sentence) continue;
    if (sentence.length > maxLength) {
      if (current) {
        chunks.push(current.trim());
        current = "";
      }
      for (let i = 0; i < sentence.length; i += maxLength) {
        chunks.push(sentence.slice(i, i + maxLength).trim());
      }
      continue;
    }

    const candidate = current ? `${current} ${sentence}` : sentence;
    if (candidate.length <= maxLength) {
      current = candidate;
    } else {
      if (current) chunks.push(current.trim());
      current = sentence;
    }
  }

  if (current.trim()) {
    chunks.push(current.trim());
  }
  return chunks;
}

function base64ToBlobUrl(base64, mimeType) {
  const binaryString = window.atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i += 1) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: mimeType || "audio/mpeg" });
  return URL.createObjectURL(blob);
}

export default function TriageCard({
  response,
  patientComplaint,
  onSelectClarifyingQuestion,
}) {
  const { openDoctorPass } = useApp();
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [isLoadingAudio, setIsLoadingAudio] = useState(false);
  const [audioError, setAudioError] = useState(null);
  const [showFullDetailsEarly, setShowFullDetailsEarly] = useState(false);
  const audioRef = useRef(null);
  const objectUrlRef = useRef(null);
  const abortControllerRef = useRef(null);
  const speechSessionRef = useRef(0);

  function cleanupAudioResources() {
    speechSessionRef.current += 1;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
  }

  useEffect(() => {
    return () => {
      cleanupAudioResources();
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
  const isGreetingTurn =
    Boolean(recommended_specialty) &&
    recommended_specialty.includes("مساعد الفرز الطبي المبدئي");
  const isConversing =
    !isEmergency &&
    !response.is_offline_fallback &&
    clarifying_questions.length > 0 &&
    !showFullDetailsEarly;

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

  function buildSpokenBodyText() {
    const parts = [];
    if (rationale_ar) {
      parts.push(rationale_ar);
    }
    if (!isEmergency && clarifying_questions.length > 0) {
      parts.push(`الأسئلة التوضيحية: ${clarifying_questions.join("، ")}`);
    }
    return parts.join("\n\n").trim() || "إرشادات الفرز الطبي المبدئي";
  }

  function resolveArabicVoice() {
    const voices = window.speechSynthesis.getVoices();
    return (
      voices.find((v) => v.lang.toLowerCase() === "ar-eg") ||
      voices.find((v) => v.lang.toLowerCase().startsWith("ar")) ||
      null
    );
  }

  function playBrowserSpeechSynthesis(textToSpeak) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      setIsPlayingAudio(false);
      setIsLoadingAudio(false);
      setAudioError("المتصفح الحالي لا يدعم تشغيل الصوت تلقائياً.");
      return;
    }

    const chunks = splitSpeechChunks(textToSpeak);
    if (chunks.length === 0) {
      setIsPlayingAudio(false);
      setIsLoadingAudio(false);
      return;
    }

    const sessionToken = ++speechSessionRef.current;
    window.speechSynthesis.cancel();

    const startSpeaking = () => {
      if (speechSessionRef.current !== sessionToken) return;
      const arabicVoice = resolveArabicVoice();

      const speakChunk = (index) => {
        if (speechSessionRef.current !== sessionToken) return;
        if (index >= chunks.length) {
          setIsPlayingAudio(false);
          setIsLoadingAudio(false);
          return;
        }

        const utterance = new SpeechSynthesisUtterance(chunks[index]);
        utterance.lang = arabicVoice?.lang || "ar-EG";
        utterance.rate = 0.95;
        if (arabicVoice) {
          utterance.voice = arabicVoice;
        }

        utterance.onstart = () => {
          if (speechSessionRef.current !== sessionToken) return;
          setIsPlayingAudio(true);
          setIsLoadingAudio(false);
        };
        utterance.onend = () => {
          if (speechSessionRef.current !== sessionToken) return;
          speakChunk(index + 1);
        };
        utterance.onerror = () => {
          if (speechSessionRef.current !== sessionToken) return;
          setIsPlayingAudio(false);
          setIsLoadingAudio(false);
          setAudioError("تعذر تشغيل الصوت عبر المتصفح؛ يرجى قراءة الإرشادات نصياً.");
        };

        window.speechSynthesis.speak(utterance);
      };

      speakChunk(0);
    };

    const existingVoices = window.speechSynthesis.getVoices();
    if (existingVoices.length > 0) {
      startSpeaking();
      return;
    }

    let started = false;
    const triggerOnce = () => {
      if (started) return;
      started = true;
      window.speechSynthesis.removeEventListener?.("voiceschanged", triggerOnce);
      startSpeaking();
    };
    window.speechSynthesis.addEventListener?.("voiceschanged", triggerOnce);
    setTimeout(triggerOnce, 150);
  }

  async function handleAudioPlayback() {
    if (isPlayingAudio || isLoadingAudio) {
      cleanupAudioResources();
      setIsPlayingAudio(false);
      setIsLoadingAudio(false);
      return;
    }

    setAudioError(null);
    setIsLoadingAudio(true);

    const bodyText = buildSpokenBodyText();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const audio = new Audio();
    audio.preload = "auto";
    audioRef.current = audio;
    try {
      const synthResult = await synthesizeVoice({ session_id: session_id || "client-voice", text: bodyText, include_disclaimer: false, signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!synthResult?.success || !synthResult?.audio_base64) throw new Error(synthResult?.error_reason_ar || "فشل توليد الصوت");
      const audioUrl = base64ToBlobUrl(synthResult.audio_base64, synthResult.mime_type || "audio/mpeg");
      objectUrlRef.current = audioUrl;
      audio.src = audioUrl;
      const cleanupObjectUrl = () => { if (objectUrlRef.current === audioUrl) { URL.revokeObjectURL(audioUrl); objectUrlRef.current = null; } };
      audio.onplay = () => { setIsPlayingAudio(true); setIsLoadingAudio(false); };
      audio.onended = () => { cleanupObjectUrl(); setIsPlayingAudio(false); setIsLoadingAudio(false); };
      audio.onerror = () => { cleanupObjectUrl(); setIsPlayingAudio(false); setIsLoadingAudio(false); setAudioError("تعذر تشغيل ملف الصوت في المتصفح."); };
      await audio.play();
    } catch (err) {
      if (err?.name === "AbortError" || controller.signal.aborted) { setIsLoadingAudio(false); setIsPlayingAudio(false); return; }
      setIsPlayingAudio(false);
      setIsLoadingAudio(false);
      setAudioError(err?.message || "المتصفح منع تشغيل الصوت التلقائي؛ اضغط مرة أخرى.");
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  }

  if (isConversing) {
    return (
      <article
        aria-label="محاورة الفرز الطبي — أسئلة متابعة"
        className="rounded-3xl border border-teal-200 bg-white p-5 shadow-xs dark:border-teal-800/70 dark:bg-slate-900"
      >
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-3 py-1 text-xs font-extrabold text-[#0D9488] dark:bg-teal-950/70 dark:text-teal-300">
              {isGreetingTurn
                ? "👋 أهلاً بك في شفاء جايد"
                : "💬 جاري الاستفسار قبل التصنيف النهائي"}
            </span>
            {recommended_specialty && !isGreetingTurn && (
              <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                (توجه مبدئي: {recommended_specialty})
              </span>
            )}
          </div>
          {!isGreetingTurn && (
            <button
              type="button"
              onClick={() => setShowFullDetailsEarly(true)}
              className="text-xs font-bold text-[#4F46E5] hover:underline dark:text-indigo-300 cursor-pointer"
            >
              عرض البطاقة والمصادر الآن
            </button>
          )}
        </div>

        <p className="mt-3 text-sm sm:text-base leading-8 text-slate-800 dark:text-slate-100">
          {rationale_ar}
        </p>

        <div className="mt-4 rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4 dark:border-indigo-900/60 dark:bg-indigo-950/30">
          <h3 className="text-xs sm:text-sm font-extrabold text-indigo-950 dark:text-indigo-200">
            من فضلك جاوب على الأسئلة دي عشان أحدد التخصص بدقة:
          </h3>
          <div className="mt-2.5 flex flex-col gap-2">
            {clarifying_questions.map((question, index) => (
              <div key={`${index}-${question}`}>
                {onSelectClarifyingQuestion ? (
                  <button
                    type="button"
                    onClick={() => onSelectClarifyingQuestion(question)}
                    className="w-full rounded-xl border border-indigo-200/80 bg-white px-3.5 py-2 text-start text-xs sm:text-sm font-semibold text-slate-800 transition-colors hover:border-[#0D9488] hover:bg-teal-50/50 dark:border-indigo-800/70 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-teal-600 cursor-pointer"
                  >
                    • {question}
                  </button>
                ) : (
                  <span className="text-xs sm:text-sm">• {question}</span>
                )}
              </div>
            ))}
          </div>
          <p className="mt-2.5 text-[11px] text-slate-500 dark:text-slate-400">
            اكتب إجابتك مباشرة في الخانة بالأسفل أو اضغط على أي سؤال للرد السريع.
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            onClick={handleAudioPlayback}
            className="inline-flex items-center gap-2 rounded-xl border border-indigo-200 bg-white px-3.5 py-1.5 text-xs font-bold text-[#4F46E5] hover:bg-indigo-50 dark:border-indigo-800 dark:bg-slate-900 dark:text-indigo-300 cursor-pointer"
          >
            {isLoadingAudio
              ? "⏹ جاري توليد الصوت... (اضغط للإلغاء)"
              : isPlayingAudio
              ? "⏹ إيقاف الصوت"
              : "🔊 سماع الأسئلة صوتياً"}
          </button>
          <span className="text-[11px] text-slate-400">
            تقييم مبدئي لا يغني عن الكشف الطبي المباشر
          </span>
        </div>
        {audioError && (
          <p className="mt-2 text-xs font-medium text-amber-700 dark:text-amber-300" role="alert">
            {audioError}
          </p>
        )}
      </article>
    );
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
          className="inline-flex items-center gap-2 rounded-xl border border-indigo-200 bg-white px-4 py-2 text-xs sm:text-sm font-bold text-[#4F46E5] shadow-xs hover:bg-indigo-50 dark:border-indigo-800 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-950/60 transition-colors cursor-pointer"
        >
          {isLoadingAudio ? (
            <span>⏹ جاري توليد الصوت... (اضغط للإلغاء)</span>
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
      {audioError && (
        <p className="mt-2 text-xs font-medium text-amber-700 dark:text-amber-300" role="alert">
          {audioError}
        </p>
      )}

      {/* Persistent Per-Card Medical Disclaimer */}
      <p className="mt-4 border-t border-current/15 pt-3 text-xs leading-6 opacity-85">
        {finalDisclaimer}
      </p>
    </article>
  );
}
