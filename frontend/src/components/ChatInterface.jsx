import { useState, useRef, useEffect } from "react";
import { Link } from "react-router";
import TriageCard from "./TriageCard";
import { mockResponses } from "../data/mockResponses";
import { useApp } from "../context/appContext";
import {
  sendTriageRequest,
  sendVoiceTriage,
  SAFE_FALLBACK_RESPONSE,
} from "../services/api";

const SUGGESTION_CHIPS = [
  {
    label: "🚨 ألم شديد في الصدر",
    text: "عندي وجع جامد ومفاجئ في صدري مسمع في كتفي الشمال مع عرق بارد ونهجان",
  },
  {
    label: "🔥 حرقان معدة وصعوبة بلع",
    text: "عندي حرقان شديد في فم المعدة مع ارتجاع مستمر وصعوبة في البلع بقالي يومين",
  },
  {
    label: "🦴 ألم في الركبة مع المشي",
    text: "عندي ألم خفيف في مفصل الركبة اليمين بيزيد مع المشي الطويل وطلوع السلم",
  },
  {
    label: "🤒 سخونية وكحة مستمرة",
    text: "عندي سخونية وكحة مستمرة بقالي أسبوع مع تكسير في الجسم",
  },
];

export default function ChatInterface() {
  const {
    sessions,
    activeSession,
    activeSessionId,
    createNewSession,
    selectSession,
    appendMessageToSession,
    recordSavedPass,
    patientVault,
    savedPasses,
  } = useApp();

  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [networkError, setNetworkError] = useState(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  // Audio recording state
  const [isRecording, setIsRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [audioError, setAudioError] = useState(null);

  // Optional dev mock preview toggle
  const [isDemoMode, setIsDemoMode] = useState(false);
  const [selectedCase, setSelectedCase] = useState("0");

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const recognitionRef = useRef(null);
  const liveTranscriptRef = useRef("");
  const recordingTimerRef = useRef(null);
  const chatScrollAnchorRef = useRef(null);
  const textareaRef = useRef(null);
  const abortControllerRef = useRef(null);
  const activeSessionIdRef = useRef(activeSessionId);

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  const messages = activeSession?.messages || [];

  useEffect(() => {
    chatScrollAnchorRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, isLoading]);

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      if (
        mediaRecorderRef.current &&
        mediaRecorderRef.current.state !== "inactive"
      ) {
        mediaRecorderRef.current.stop();
      }
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };
  }, []);

  // Auto-expand textarea height up to 140px
  function handleInputChange(event) {
    const val = event.target.value;
    setInput(val);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        140
      )}px`;
    }
  }

  function handleNewSession() {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    createNewSession();
    setInput("");
    setIsLoading(false);
    setNetworkError(null);
    setAudioError(null);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  async function submitTriageText(rawText) {
    const text = (rawText || "").trim();
    if (!text || isLoading) return;

    const targetSessionId = activeSessionId;
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setNetworkError(null);
    setAudioError(null);

    const userMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text,
      time: new Date().toLocaleTimeString("ar-EG", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    };

    appendMessageToSession(targetSessionId, userMessage, text);
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    setIsLoading(true);

    try {
      const response = await sendTriageRequest({
        session_id: targetSessionId,
        user_input: text,
        input_mode: "text",
        signal: controller.signal,
      });

      if (activeSessionIdRef.current !== targetSessionId) return;

      appendMessageToSession(targetSessionId, {
        id: crypto.randomUUID(),
        role: "assistant",
        data: response,
        originalInput: text,
      });
      recordSavedPass({ triageData: response, patientComplaint: text });
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (activeSessionIdRef.current !== targetSessionId) return;

      console.warn("Triage live connection error:", err);
      setNetworkError(
        "تعذر الاتصال بالخادم حالياً — تم عرض التوجيه الطبي الآمن كبديل فوري."
      );

      const fallbackData = {
        ...SAFE_FALLBACK_RESPONSE,
        session_id: targetSessionId,
      };

      appendMessageToSession(targetSessionId, {
        id: crypto.randomUUID(),
        role: "assistant",
        data: fallbackData,
        isFallback: true,
        originalInput: text,
      });
      recordSavedPass({ triageData: fallbackData, patientComplaint: text });
    } finally {
      if (activeSessionIdRef.current === targetSessionId) {
        setIsLoading(false);
      }
    }
  }

  function handleSubmit(event) {
    event?.preventDefault();
    submitTriageText(input);
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitTriageText(input);
    }
  }

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
          // Optional browser recognition
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
        "تعذر الوصول إلى الميكروفون. يرجى التحقق من أذونات المتصفح أو كتابة الأعراض نصياً."
      );
      setIsRecording(false);
    }
  }

  function stopRecording() {
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        // Ignore stop errors
      }
      recognitionRef.current = null;
    }

    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== "inactive"
    ) {
      mediaRecorderRef.current.stop();
    }

    setIsRecording(false);
  }

  async function processRecordedAudio(audioBlob, fallbackText) {
    const targetSessionId = activeSessionId;
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setNetworkError(null);

    const reader = new FileReader();
    reader.onloadend = async () => {
      const base64Data = reader.result;
      const cleanFallback = fallbackText.trim();
      const userText = cleanFallback || "🎙️ [تسجيل صوتي للمريض]";

      appendMessageToSession(
        targetSessionId,
        {
          id: crypto.randomUUID(),
          role: "user",
          text: userText,
          isVoice: true,
          time: new Date().toLocaleTimeString("ar-EG", {
            hour: "2-digit",
            minute: "2-digit",
          }),
        },
        userText
      );

      try {
        const result = await sendVoiceTriage({
          session_id: targetSessionId,
          audio_base64: base64Data,
          filename: "patient_voice.webm",
          language: "ar",
          fallback_text: cleanFallback || null,
          signal: controller.signal,
        });

        if (activeSessionIdRef.current !== targetSessionId) return;

        const triageData = result.triage || result;
        const complaintText =
          result.transcription?.text || cleanFallback || "تسجيل صوتي للمريض";

        appendMessageToSession(targetSessionId, {
          id: crypto.randomUUID(),
          role: "assistant",
          data: triageData,
          originalInput: complaintText,
        });
        recordSavedPass({
          triageData,
          patientComplaint: complaintText,
        });
      } catch (err) {
        if (err?.name === "AbortError") return;
        if (activeSessionIdRef.current !== targetSessionId) return;

        console.warn("Voice triage connection error:", err);
        setNetworkError(
          "تعذر الاتصال بخدمة معالجة الصوت حالياً — تم تفعيل التوجيه الآمن."
        );

        const fallbackData = {
          ...SAFE_FALLBACK_RESPONSE,
          session_id: targetSessionId,
        };

        appendMessageToSession(targetSessionId, {
          id: crypto.randomUUID(),
          role: "assistant",
          data: fallbackData,
          isFallback: true,
          originalInput: cleanFallback || "تسجيل صوتي",
        });
        recordSavedPass({
          triageData: fallbackData,
          patientComplaint: cleanFallback || "تسجيل صوتي",
        });
      } finally {
        if (activeSessionIdRef.current === targetSessionId) {
          setIsLoading(false);
        }
      }
    };

    reader.onerror = () => {
      setAudioError("حدث خطأ أثناء قراءة التسجيل الصوتي.");
      setIsLoading(false);
    };

    reader.readAsDataURL(audioBlob);
  }

  const hasVaultContext = Boolean(
    patientVault.age ||
      patientVault.gender ||
      patientVault.chronicConditions.length > 0
  );

  return (
    <div className="flex min-h-0 flex-1 bg-[#F8FAFC] dark:bg-[#0F172A]">
      {/* Collapsible Right-Side Chat History Sidebar (RTL Right Edge) */}
      <aside
        aria-label="سجل المحادثات المؤقت"
        className={`shrink-0 flex-col border-e border-slate-200 bg-white transition-all dark:border-slate-800 dark:bg-slate-900 print:hidden ${
          isSidebarOpen ? "hidden md:flex md:w-72" : "hidden"
        }`}
      >
        <div className="p-4 border-b border-slate-200 dark:border-slate-800 space-y-3">
          <button
            type="button"
            onClick={handleNewSession}
            className="flex w-full items-center justify-center gap-2 rounded-2xl bg-[#0D9488] px-4 py-2.5 text-xs sm:text-sm font-extrabold text-white shadow-xs hover:bg-teal-700 transition-colors cursor-pointer"
          >
            <span>+</span>
            <span>محادثة جديدة</span>
          </button>

          {hasVaultContext && (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/80 px-3 py-2 text-[11px] text-emerald-900 dark:border-emerald-800/60 dark:bg-emerald-950/40 dark:text-emerald-200">
              <span className="font-bold">✓ الخزنة المؤقتة مفعّلة:</span>{" "}
              {patientVault.age || "عمر غير محدد"}
              {patientVault.chronicConditions.length > 0
                ? ` • ${patientVault.chronicConditions.join("، ")}`
                : ""}
            </div>
          )}
        </div>

        {/* In-Memory Conversation Sessions List */}
        <div className="min-h-0 flex-1 overflow-y-auto p-3 space-y-1.5">
          <p className="px-2 py-1 text-[11px] font-bold text-slate-400">
            جلسات الذاكرة المؤقتة ({sessions.length})
          </p>
          {sessions.map((sess) => {
            const isCurrent = sess.id === activeSessionId;
            return (
              <button
                key={sess.id}
                type="button"
                onClick={() => selectSession(sess.id)}
                className={`w-full rounded-xl px-3 py-2.5 text-start transition-colors cursor-pointer ${
                  isCurrent
                    ? "bg-teal-50 text-[#0D9488] border border-teal-200 font-bold dark:bg-teal-950/50 dark:text-teal-300 dark:border-teal-800"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                <div className="truncate text-xs">{sess.title}</div>
                <div className="mt-1 flex items-center justify-between text-[10px] opacity-70">
                  <span className="font-en" dir="ltr">
                    {sess.id}
                  </span>
                  <span>{sess.messages.length} رسالة</span>
                </div>
              </button>
            );
          })}
        </div>

        {/* Quick Links to Archive, Profile & Dashboard */}
        <div className="border-t border-slate-200 p-3 space-y-1.5 text-xs dark:border-slate-800">
          <Link
            to="/history"
            className="flex items-center justify-between rounded-xl px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <span>📄 أرشيف البطاقات</span>
            <span className="font-en rounded-full bg-slate-200 px-2 py-0.5 text-[10px] dark:bg-slate-700">
              {savedPasses.length}
            </span>
          </Link>
          <Link
            to="/profile"
            className="flex items-center justify-between rounded-xl px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <span>🛡️ الخزنة الصحية المؤقتة</span>
          </Link>
          <Link
            to="/dashboard"
            className="flex items-center justify-between rounded-xl px-3 py-2 font-semibold text-[#4F46E5] hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-950/40"
          >
            <span>🚨 لوحة المشرف (SSE)</span>
          </Link>
        </div>
      </aside>

      {/* Main Gemini-Style Chat Workspace */}
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Workspace Toolbar */}
        <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white/80 px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900/80 print:hidden">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsSidebarOpen((v) => !v)}
              className="hidden md:inline-flex items-center gap-1 rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 cursor-pointer"
            >
              <span>{isSidebarOpen ? "إخفاء السجل" : "إظهار السجل"}</span>
            </button>
            <button
              type="button"
              onClick={handleNewSession}
              className="md:hidden inline-flex items-center gap-1 rounded-xl bg-[#0D9488] px-3 py-1.5 text-xs font-bold text-white cursor-pointer"
            >
              <span>+ محادثة جديدة</span>
            </button>
            <span className="font-en rounded-lg bg-slate-100 px-2.5 py-1 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {activeSessionId}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsDemoMode((v) => !v)}
              className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
                isDemoMode
                  ? "border border-amber-300 bg-amber-100 text-amber-900 dark:border-amber-700 dark:bg-amber-950/60 dark:text-amber-200"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300"
              }`}
            >
              {isDemoMode ? "إخفاء المعاينة التجريبية" : "معاينة بطاقة Mock"}
            </button>
          </div>
        </div>

        {/* Collapsible Mock Card Preview Selector */}
        {isDemoMode && (
          <div className="shrink-0 border-b border-amber-200 bg-amber-50/70 px-4 py-2.5 dark:border-amber-800 dark:bg-amber-950/30 print:hidden">
            <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-3">
              <label
                htmlFor="demo-case"
                className="text-xs font-bold text-amber-950 dark:text-amber-200"
              >
                معاينة سريعة لمستويات الفرز:
              </label>
              <select
                id="demo-case"
                value={selectedCase}
                onChange={(e) => setSelectedCase(e.target.value)}
                className="flex-1 min-w-[240px] rounded-xl border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-800 dark:border-amber-700 dark:bg-slate-900 dark:text-slate-100"
              >
                <option value="0">المستوى 4 — طوارئ قصوى (Emergency Escalation)</option>
                <option value="1">المستوى 2 — إحالة عاجلة (Urgent Specialist)</option>
                <option value="2">المستوى 3 — حالة غير واضحة (Ambiguous)</option>
                <option value="3">المستوى 1 — إحالة روتينية (Routine Specialist)</option>
              </select>
            </div>
          </div>
        )}

        {/* Network & Audio Alerts */}
        {networkError && (
          <aside
            role="alert"
            className="shrink-0 flex items-center justify-between border-b border-rose-200 bg-rose-50 px-4 py-2 text-xs font-semibold text-rose-800 dark:border-rose-900 dark:bg-rose-950/60 dark:text-rose-200 print:hidden"
          >
            <span>⚠️ {networkError}</span>
            <button
              type="button"
              onClick={() => setNetworkError(null)}
              className="font-bold cursor-pointer"
            >
              ✕
            </button>
          </aside>
        )}

        {audioError && (
          <aside
            role="alert"
            className="shrink-0 flex items-center justify-between border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs font-semibold text-amber-800 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200 print:hidden"
          >
            <span>🎙️ {audioError}</span>
            <button
              type="button"
              onClick={() => setAudioError(null)}
              className="font-bold cursor-pointer"
            >
              ✕
            </button>
          </aside>
        )}

        {/* Chat Scroll Stream */}
        <section
          role="log"
          aria-label="رسائل المحادثة"
          aria-live="polite"
          className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6"
        >
          <div className="mx-auto max-w-4xl space-y-6">
            {isDemoMode && (
              <div className="rounded-3xl border-2 border-dashed border-amber-300 bg-amber-50/40 p-4 dark:border-amber-700 dark:bg-amber-950/20">
                <span className="mb-2 inline-block rounded-md bg-amber-200 px-2.5 py-0.5 text-[10px] font-bold text-amber-950">
                  معاينة بطاقة تجريبية
                </span>
                <TriageCard
                  response={mockResponses[Number(selectedCase)]}
                  patientComplaint="حالة تجريبية منتقاة للمعاينة"
                />
              </div>
            )}

            {/* Gemini-Style Empty State with Quick-Start Egyptian Arabic Chips */}
            {messages.length === 0 && !isDemoMode && (
              <div className="py-10 text-center space-y-6">
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl bg-gradient-to-br from-[#0D9488] to-[#4F46E5] text-3xl text-white shadow-lg shadow-teal-600/20">
                  🩺
                </div>

                <div className="space-y-2">
                  <h1 className="text-2xl sm:text-3xl font-black text-slate-900 dark:text-white">
                    أهلاً بك في مساحة الفرز الذكي
                  </h1>
                  <p className="mx-auto max-w-xl text-sm leading-7 text-slate-600 dark:text-slate-300">
                    اوصف أعراضك بالعامية المصرية أو اضغط على زر الصوت البنفسجي
                    بالأسفل. جميع النتائج تعتمد على فحص علامات الخطر أولاً ثم
                    التوجيه الطبي الموثق.
                  </p>
                </div>

                {/* Clickable Egyptian Arabic Quick-Start Chips */}
                <div className="mx-auto grid max-w-2xl grid-cols-1 gap-2.5 sm:grid-cols-2 text-start">
                  {SUGGESTION_CHIPS.map((chip) => (
                    <button
                      key={chip.label}
                      type="button"
                      onClick={() => submitTriageText(chip.text)}
                      className="rounded-2xl border border-slate-200 bg-white p-3.5 shadow-xs hover:border-[#0D9488] hover:bg-teal-50/50 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-teal-600 dark:hover:bg-teal-950/30 transition-all cursor-pointer"
                    >
                      <div className="text-xs font-extrabold text-[#0D9488] dark:text-teal-400">
                        {chip.label}
                      </div>
                      <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300 line-clamp-2">
                        {chip.text}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Message Stream: Patient Right (items-start in RTL), AI Triage Left (items-end in RTL) */}
            {messages.map((message) => {
              if (message.role === "user") {
                return (
                  <div
                    key={message.id}
                    className="flex flex-col items-start"
                  >
                    <div className="w-fit max-w-[90%] sm:max-w-[78%] rounded-2xl rounded-ts-xs bg-[#0D9488] px-4 py-3 text-white shadow-sm">
                      <div className="mb-1 flex items-center justify-between gap-4 text-[11px] font-bold text-teal-100">
                        <span>
                          {message.isVoice ? "أنت (صوتياً 🎙️)" : "شكوى المريض"}
                        </span>
                        <span>{message.time}</span>
                      </div>
                      <p className="whitespace-pre-wrap text-sm leading-7 [overflow-wrap:anywhere]">
                        {message.text}
                      </p>
                    </div>
                  </div>
                );
              }

              if (message.role === "assistant") {
                return (
                  <div key={message.id} className="flex flex-col items-end">
                    <div className="w-full lg:w-[92%]">
                      <TriageCard
                        response={message.data}
                        patientComplaint={message.originalInput}
                        onSelectClarifyingQuestion={(q) =>
                          setInput((prev) => (prev ? `${prev} — ${q}: ` : `${q}: `))
                        }
                      />
                    </div>
                  </div>
                );
              }

              return null;
            })}

            {/* Loading State */}
            {isLoading && (
              <div
                role="status"
                aria-live="polite"
                className="flex items-center gap-3 rounded-2xl border border-indigo-200 bg-indigo-50/70 p-4 dark:border-indigo-800 dark:bg-indigo-950/40"
              >
                <div className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-[#4F46E5] border-t-transparent" />
                <div>
                  <p className="text-sm font-bold text-slate-900 dark:text-white">
                    جاري فحص علامات الخطورة ومطابقة المصادر الطبية...
                  </p>
                  <p className="text-xs text-slate-600 dark:text-slate-300">
                    يتم تحليل الأعراض وتحديد التخصص الأنسب بأمان
                  </p>
                </div>
              </div>
            )}

            <div ref={chatScrollAnchorRef} />
          </div>
        </section>

        {/* Bottom Gemini-Style Input Bar + Animated Indigo Voice Orb */}
        <footer className="shrink-0 border-t border-slate-200 bg-white px-4 py-3.5 dark:border-slate-800 dark:bg-slate-900 print:hidden">
          <div className="mx-auto max-w-4xl">
            {isRecording && (
              <div className="mb-3 flex items-center justify-between rounded-2xl border border-indigo-300 bg-indigo-50 px-4 py-2 text-indigo-950 dark:border-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-100">
                <div className="flex items-center gap-2.5">
                  <span className="h-3 w-3 rounded-full bg-red-600 animate-ping" />
                  <span className="text-xs sm:text-sm font-bold">
                    جاري التسجيل الصوتي ({recordingSeconds} ثانية)... تحدث بوضوح بالعامية
                  </span>
                </div>
                <button
                  type="button"
                  onClick={stopRecording}
                  className="rounded-xl bg-red-600 px-3.5 py-1.5 text-xs font-extrabold text-white hover:bg-red-700 cursor-pointer"
                >
                  إيقاف وإرسال
                </button>
              </div>
            )}

            <form onSubmit={handleSubmit}>
              <label htmlFor="symptoms" className="sr-only">
                وصف الأعراض
              </label>

              <div className="flex items-end gap-2.5 rounded-2xl border border-slate-300 bg-slate-50/70 p-2 focus-within:border-[#0D9488] focus-within:ring-2 focus-within:ring-teal-100 dark:border-slate-700 dark:bg-slate-800/80 dark:focus-within:ring-teal-900/40">
                <textarea
                  ref={textareaRef}
                  id="symptoms"
                  rows={1}
                  value={input}
                  onChange={handleInputChange}
                  onKeyDown={handleKeyDown}
                  placeholder="اكتب أعراضك هنا بالعامية المصرية (مثال: عندي صداع وزغللة من الصبح)..."
                  maxLength={1500}
                  disabled={isLoading || isRecording}
                  className="min-w-0 flex-1 resize-none bg-transparent px-3 py-2 text-sm leading-6 text-slate-900 outline-none placeholder:text-slate-400 disabled:opacity-60 dark:text-white"
                />

                {/* Animated Circular Indigo Voice Orb */}
                <button
                  type="button"
                  onClick={isRecording ? stopRecording : startRecording}
                  disabled={isLoading}
                  aria-label={
                    isRecording ? "إيقاف التسجيل الصوتي" : "تسجيل الأعراض بالصوت"
                  }
                  title={
                    isRecording ? "إيقاف التسجيل وإرسال الصوت" : "التحدث بالصوت (Voice Orb)"
                  }
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-white shadow-md transition-all cursor-pointer disabled:opacity-50 ${
                    isRecording
                      ? "bg-red-600 ring-4 ring-red-300 animate-pulse"
                      : "bg-[#4F46E5] hover:bg-indigo-700 voice-orb-idle"
                  }`}
                >
                  {isRecording ? (
                    <span className="h-3.5 w-3.5 rounded-xs bg-white" />
                  ) : (
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="20"
                      height="20"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.2"
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

                {/* Send Button */}
                <button
                  type="submit"
                  disabled={!input.trim() || isLoading || isRecording}
                  className="shrink-0 rounded-xl bg-[#0D9488] px-4 py-2.5 text-sm font-extrabold text-white shadow-xs hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors cursor-pointer"
                >
                  إرسال
                </button>
              </div>

              <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
                <span>
                  🔒 لا تكتب اسمك أو رقم تليفونك — الجلسة تعمل بخصوصية Zero-PHI في الذاكرة فقط.
                </span>
                <span className="font-en" dir="ltr">
                  {input.length}/1500
                </span>
              </div>
            </form>
          </div>
        </footer>
      </main>
    </div>
  );
}
