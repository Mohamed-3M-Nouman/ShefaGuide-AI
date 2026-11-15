import { useState, useRef, useEffect } from "react";
import TriageCard from "./TriageCard";
import { mockResponses } from "../data/mockResponses";
import {
  sendTriageRequest,
  sendVoiceTriage,
  SAFE_FALLBACK_RESPONSE,
} from "../services/api";

export default function ChatInterface() {
  // In-memory Zero-PHI state (strictly wiped on refresh/exit)
  const [sessionId, setSessionId] = useState(
    () => "sess-" + crypto.randomUUID().slice(0, 10)
  );
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [networkError, setNetworkError] = useState(null);

  // Audio recording state
  const [isRecording, setIsRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [audioError, setAudioError] = useState(null);

  // Demo Mock preview toggle
  const [isDemoMode, setIsDemoMode] = useState(false);
  const [selectedCase, setSelectedCase] = useState("0");

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const recognitionRef = useRef(null);
  const liveTranscriptRef = useRef("");
  const recordingTimerRef = useRef(null);
  const chatScrollAnchorRef = useRef(null);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    chatScrollAnchorRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // Clean up recording timers and streams on unmount
  useEffect(() => {
    return () => {
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };
  }, []);

  // Reset conversation and generate a fresh session ID in memory
  function handleNewSession() {
    setSessionId("sess-" + crypto.randomUUID().slice(0, 10));
    setMessages([]);
    setInput("");
    setNetworkError(null);
    setAudioError(null);
  }

  // Handle Text Submission
  async function handleSubmit(event) {
    event?.preventDefault();
    const text = input.trim();
    if (!text || isLoading) return;

    setNetworkError(null);
    setAudioError(null);

    const userMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text,
      time: new Date().toLocaleTimeString("ar-EG", { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      const response = await sendTriageRequest({
        session_id: sessionId,
        user_input: text,
        input_mode: "text",
      });

      const assistantMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        data: response,
        originalInput: text,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      console.warn("Triage live connection error:", err);
      setNetworkError(
        "تعذر الاتصال بالخادم حالياً — يرجى التوجه لطبيب مختص لتقييم حالتك مباشرة."
      );

      // Safe Fallback Card according to medical guidelines
      const fallbackData = {
        ...SAFE_FALLBACK_RESPONSE,
        session_id: sessionId,
      };

      const fallbackMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        data: fallbackData,
        isFallback: true,
        originalInput: text,
      };

      setMessages((prev) => [...prev, fallbackMessage]);
    } finally {
      setIsLoading(false);
    }
  }

  // Start Audio Recording (MediaRecorder + optional SpeechRecognition fallback)
  async function startRecording() {
    setAudioError(null);
    audioChunksRef.current = [];
    liveTranscriptRef.current = "";

    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("المتصفح لا يدعم تسجيل الصوت.");
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm",
      });

      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        // Stop all audio tracks to release microphone
        stream.getTracks().forEach((track) => track.stop());

        const audioBlob = new Blob(audioChunksRef.current, {
          type: "audio/webm",
        });

        if (audioBlob.size > 0) {
          await processRecordedAudio(audioBlob, liveTranscriptRef.current);
        } else {
          setAudioError("لم يتم التقاط أي صوت، يرجى المحاولة مرة أخرى.");
        }
      };

      // Optional browser live transcription for immediate fallback text
      const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SpeechRecognition) {
        try {
          const recognition = new SpeechRecognition();
          recognition.lang = "ar-EG";
          recognition.continuous = true;
          recognition.interimResults = true;
          recognition.onresult = (e) => {
            const transcript = Array.from(e.results)
              .map((r) => r[0].transcript)
              .join(" ");
            liveTranscriptRef.current = transcript;
          };
          recognition.onerror = () => {};
          recognition.start();
          recognitionRef.current = recognition;
        } catch {
          // Non-critical if recognition fails
        }
      }

      mediaRecorder.start(250);
      setIsRecording(true);
      setRecordingSeconds(0);

      recordingTimerRef.current = setInterval(() => {
        setRecordingSeconds((sec) => sec + 1);
      }, 1000);
    } catch (err) {
      console.warn("Microphone access error:", err);
      setAudioError(
        "تعذر الوصول إلى الميكروفون. يرجى التأكد من إعطاء الإذن للمتصفح أو كتابة الأعراض نصياً."
      );
      setIsRecording(false);
    }
  }

  // Stop Audio Recording
  function stopRecording() {
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch (err) {
        console.debug("Recognition stop error:", err);
      }
      recognitionRef.current = null;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }

    setIsRecording(false);
  }

  // Convert blob to Base64 and send to /api/v1/voice/triage
  async function processRecordedAudio(audioBlob, fallbackText) {
    setIsLoading(true);
    setNetworkError(null);

    // Read blob as Base64 in memory
    const reader = new FileReader();
    reader.onloadend = async () => {
      const base64Data = reader.result;
      const cleanFallback = fallbackText.trim();

      const userText = cleanFallback || "🎙️ [تسجيل صوتي للمريض]";
      const userMessage = {
        id: crypto.randomUUID(),
        role: "user",
        text: userText,
        isVoice: true,
        time: new Date().toLocaleTimeString("ar-EG", { hour: "2-digit", minute: "2-digit" }),
      };

      setMessages((prev) => [...prev, userMessage]);

      try {
        const result = await sendVoiceTriage({
          session_id: sessionId,
          audio_base64: base64Data,
          filename: "patient_voice.webm",
          fallback_text: cleanFallback || null,
        });

        // The voice triage response contains { triage, transcription, synthesis }
        const triageData = result.triage || result;

        const assistantMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          data: triageData,
          originalInput: cleanFallback || "تسجيل صوتي",
        };

        setMessages((prev) => [...prev, assistantMessage]);
      } catch (err) {
        console.warn("Voice triage connection error:", err);
        setNetworkError(
          "تعذر الاتصال بخدمة معالجة الصوت حالياً — تم تفعيل التوجيه الآمن."
        );

        const fallbackData = {
          ...SAFE_FALLBACK_RESPONSE,
          session_id: sessionId,
        };

        const fallbackMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          data: fallbackData,
          isFallback: true,
          originalInput: cleanFallback || "تسجيل صوتي",
        };

        setMessages((prev) => [...prev, fallbackMessage]);
      } finally {
        setIsLoading(false);
      }
    };

    reader.onerror = () => {
      setAudioError("حدث خطأ أثناء قراءة التسجيل الصوتي.");
      setIsLoading(false);
    };

    reader.readAsDataURL(audioBlob);
  }

  return (
    <main className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col">
      {/* Header with App Info and Session Reset */}
      <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal-700 text-white font-black text-sm">
              شفاء
            </div>
            <div>
              <h1 className="text-xl font-bold text-teal-900">شفاء جايد — ShefaGuide AI</h1>
              <p className="text-xs text-slate-500">
                فرز سريري مبدئي ذكي وموجه للتخصصات الطبية (Zero-PHI)
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleNewSession}
              title="بدء جلسة فرز جديدة ومسح الذاكرة الحالية"
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
            >
              🔄 جلسة جديدة
            </button>
            <button
              type="button"
              onClick={() => setIsDemoMode((v) => !v)}
              className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
                isDemoMode
                  ? "bg-amber-100 text-amber-900 border border-amber-300"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {isDemoMode ? "إخفاء الـ Mock" : "معاينة Mock"}
            </button>
          </div>
        </div>

        {/* Demo Case Preview Bar (Collapsible) */}
        {isDemoMode && (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50/70 p-3">
            <label
              htmlFor="demo-case"
              className="mb-1.5 block text-xs font-bold text-amber-900"
            >
              معاينة كارت تجريبي ثابت (لا يؤثر على الشات الحي):
            </label>
            <select
              id="demo-case"
              value={selectedCase}
              onChange={(e) => setSelectedCase(e.target.value)}
              className="w-full rounded-lg border border-amber-300 bg-white p-2 text-xs font-medium text-slate-800 focus:outline-teal-600"
            >
              <option value="0">المستوى 4 — طوارئ قصوى (Emergency Escalation)</option>
              <option value="1">المستوى 2 — إحالة عاجلة (Urgent Specialist)</option>
              <option value="2">المستوى 3 — حالة غير واضحة راجع طبيباً (Ambiguous)</option>
              <option value="3">المستوى 1 — إحالة روتينية (Routine Specialist)</option>
            </select>
          </div>
        )}
      </header>

      {/* Network / Offline Alert Banner */}
      {networkError && (
        <aside
          role="alert"
          className="shrink-0 bg-rose-50 border-b border-rose-200 px-4 py-2.5 text-xs sm:text-sm font-semibold text-rose-800 flex items-center justify-between"
        >
          <div className="flex items-center gap-2">
            <span>⚠️</span>
            <span>{networkError}</span>
          </div>
          <button
            type="button"
            onClick={() => setNetworkError(null)}
            className="text-rose-600 hover:text-rose-900 text-base leading-none font-bold cursor-pointer"
          >
            ×
          </button>
        </aside>
      )}

      {/* Audio Recording Error Alert */}
      {audioError && (
        <aside
          role="alert"
          className="shrink-0 bg-amber-50 border-b border-amber-200 px-4 py-2 text-xs font-semibold text-amber-800 flex items-center justify-between"
        >
          <span>🎙️ {audioError}</span>
          <button
            type="button"
            onClick={() => setAudioError(null)}
            className="text-amber-600 hover:text-amber-900 font-bold"
          >
            ×
          </button>
        </aside>
      )}

      {/* Messages Scroll Area */}
      <section
        role="log"
        aria-label="رسائل المحادثة"
        aria-live="polite"
        className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4 sm:p-6"
      >
        {/* If demo mode is active, show the selected mock card at top */}
        {isDemoMode && (
          <div className="rounded-2xl border-2 border-dashed border-amber-300 bg-amber-50/40 p-4">
            <span className="mb-2 inline-block rounded-md bg-amber-200 px-2 py-0.5 text-[10px] font-bold text-amber-900">
              معاينة تجريبية ثابتة
            </span>
            <TriageCard
              response={mockResponses[Number(selectedCase)]}
              patientComplaint="حالة تجريبية منتقاة للمعاينة"
            />
          </div>
        )}

        {messages.length === 0 && !isDemoMode && (
          <div className="py-14 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-teal-50 text-teal-700 text-2xl shadow-xs">
              🩺
            </div>
            <h2 className="text-lg font-bold text-slate-800">أهلاً بك في شفاء جايد</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
              صف ما تشعر به من أعراض بالعامية المصرية أو الفصحى (مثلاً: &quot;عندي وجع جامد في صدري ومسمع في كتفي الشمال&quot; أو &quot;عندي سخونية وكحة بقالها أسبوع&quot;) وسيقوم النظام بتوجيهك للتخصص الطبي الأنسب.
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
                🔒 صفر بيانات شخصية محفوظة
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
                🎙️ إدخال صوتي مدعوم
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
                📄 بطاقة للطبيب
              </span>
            </div>
          </div>
        )}

        {/* Message stream */}
        {messages.map((message) => {
          if (message.role === "user") {
            return (
              <div key={message.id} className="flex flex-col items-end">
                <div className="w-fit max-w-[90%] rounded-2xl bg-teal-700 px-4 py-3 text-white shadow-xs sm:max-w-[80%]">
                  <div className="flex items-center justify-between gap-3 mb-1 text-[11px] font-bold text-teal-200">
                    <span>{message.isVoice ? "أنت (صوتياً 🎙️)" : "أنت"}</span>
                    <span>{message.time}</span>
                  </div>
                  <p className="whitespace-pre-wrap leading-7 [overflow-wrap:anywhere]">
                    {message.text}
                  </p>
                </div>
              </div>
            );
          }

          if (message.role === "assistant") {
            return (
              <div key={message.id} className="w-full">
                <TriageCard
                  response={message.data}
                  patientComplaint={message.originalInput}
                />
              </div>
            );
          }

          return null;
        })}

        {/* Loading Spinner / Analyzing symptoms */}
        {isLoading && (
          <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-3 rounded-2xl border border-teal-200 bg-teal-50/80 p-4 shadow-xs"
          >
            <div className="flex h-5 w-5 shrink-0 items-center justify-center">
              <svg
                className="animate-spin h-5 w-5 text-teal-700"
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
            </div>
            <div>
              <p className="text-sm font-bold text-teal-900">
                جاري تحليل الأعراض ومراجعة المصادر الطبية...
              </p>
              <p className="text-xs text-teal-700 mt-0.5">
                يتم فحص علامات الخطورة والتصنيف السريري للتخصص الأنسب
              </p>
            </div>
          </div>
        )}

        {/* Scroll anchor */}
        <div ref={chatScrollAnchorRef} />
      </section>

      {/* Input Form with Text + Microphone Button */}
      <footer className="shrink-0 border-t border-slate-200 bg-white p-4">
        {/* Active Recording State Banner */}
        {isRecording && (
          <div className="mb-3 flex items-center justify-between rounded-xl bg-rose-50 border border-rose-300 px-4 py-2 text-rose-900 animate-pulse">
            <div className="flex items-center gap-2">
              <span className="flex h-3 w-3 rounded-full bg-rose-600" />
              <span className="text-xs sm:text-sm font-bold">
                جاري التسجيل الصوتي ({recordingSeconds} ثانية)... تحدث بوضوح
              </span>
            </div>
            <button
              type="button"
              onClick={stopRecording}
              className="rounded-lg bg-rose-600 px-3 py-1 text-xs font-bold text-white hover:bg-rose-700 cursor-pointer"
            >
              إيقاف وإرسال
            </button>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <label htmlFor="symptoms" className="sr-only">
            وصف الأعراض
          </label>

          <div className="flex items-center gap-2">
            <input
              id="symptoms"
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="اكتب الأعراض هنا (مثال: ألم شديد في الصدر وضيق تنفس)..."
              maxLength={1500}
              autoComplete="off"
              disabled={isLoading || isRecording}
              className="min-w-0 flex-1 rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100 disabled:bg-slate-100 transition-all"
            />

            {/* Microphone Button */}
            <button
              type="button"
              onClick={isRecording ? stopRecording : startRecording}
              disabled={isLoading}
              title={
                isRecording
                  ? "إيقاف التسجيل الصوتي والإرسال"
                  : "تسجيل الأعراض صوتياً"
              }
              aria-label={
                isRecording
                  ? "إيقاف التسجيل الصوتي"
                  : "بدء التسجيل الصوتي للأعراض"
              }
              className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl transition-all cursor-pointer ${
                isRecording
                  ? "bg-rose-600 text-white ring-4 ring-rose-200 animate-pulse"
                  : "bg-slate-100 text-slate-700 hover:bg-teal-50 hover:text-teal-700"
              } disabled:cursor-not-allowed disabled:opacity-50`}
            >
              {isRecording ? (
                <div className="h-4 w-4 rounded-xs bg-white" />
              ) : (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="22"
                  height="22"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" x2="12" y1="19" y2="22" />
                </svg>
              )}
            </button>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={!input.trim() || isLoading || isRecording}
              className="shrink-0 rounded-xl bg-teal-700 px-5 py-3 text-sm font-bold text-white shadow-sm hover:bg-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors cursor-pointer"
            >
              إرسال
            </button>
          </div>

          <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
            <span>
              🔒 لا تسجل بياناتك الشخصية (الاسم أو الرقم) — النظام يتعامل بخصوصية كاملة.
            </span>
            <span className="font-mono">{input.length}/1500</span>
          </div>
        </form>
      </footer>
    </main>
  );
}
