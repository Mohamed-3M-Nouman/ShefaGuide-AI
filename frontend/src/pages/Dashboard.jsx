import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchEscalations,
  patchEscalationStatus,
  fetchAuditLogs,
  createEscalationEventSource,
} from "../services/api";

export default function Dashboard() {
  // Escalations state
  const [escalations, setEscalations] = useState([]);
  const [escalationsCount, setEscalationsCount] = useState(0);
  const [escalationFilter, setEscalationFilter] = useState("all");
  const [updatingEscalationId, setUpdatingEscalationId] = useState(null);

  // Audit logs & summary stats state
  const [auditLogs, setAuditLogs] = useState([]);
  const [metrics, setMetrics] = useState({
    total_count: 0,
    escalated_count: 0,
    avg_latency_ms: 0,
  });

  // UI & Live Stream state
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState(null);
  const [liveAlert, setLiveAlert] = useState(null);
  const [isConnectedSSE, setIsConnectedSSE] = useState(false);

  const eventSourceRef = useRef(null);
  const alertDismissTimeoutRef = useRef(null);

  // Play subtle emergency audio chime via Web Audio API (No external assets required)
  const playEmergencyTone = useCallback(() => {
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = "sine";
      osc.frequency.setValueAtTime(880, ctx.currentTime); // A5
      osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.3);

      gain.setValueAtTime(0.3, ctx.currentTime);
      gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    } catch {
      // Audio playback fails silently if user has not interacted with DOM yet
    }
  }, []);

  // Manual reload button handler
  const reloadAllData = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const filterParam = escalationFilter === "all" ? undefined : escalationFilter;
      const [escData, auditData] = await Promise.all([
        fetchEscalations({ status: filterParam, limit: 50 }),
        fetchAuditLogs({ limit: 50 }),
      ]);
      setEscalations(escData.items || []);
      setEscalationsCount(escData.count ?? escData.items?.length ?? 0);
      setAuditLogs(auditData.items || []);
      setMetrics({
        total_count: auditData.total_count ?? 0,
        escalated_count: auditData.escalated_count ?? 0,
        avg_latency_ms: auditData.avg_latency_ms ?? 0,
      });
    } catch (err) {
      setErrorMessage("تعذر الاتصال بالخادم لجلب بيانات لوحة التحكم.");
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  }, [escalationFilter]);

  // Initial load via async effect
  useEffect(() => {
    let ignore = false;
    async function loadInitialData() {
      try {
        const filterParam = escalationFilter === "all" ? undefined : escalationFilter;
        const [escData, auditData] = await Promise.all([
          fetchEscalations({ status: filterParam, limit: 50 }),
          fetchAuditLogs({ limit: 50 }),
        ]);
        if (!ignore) {
          setEscalations(escData.items || []);
          setEscalationsCount(escData.count ?? escData.items?.length ?? 0);
          setAuditLogs(auditData.items || []);
          setMetrics({
            total_count: auditData.total_count ?? 0,
            escalated_count: auditData.escalated_count ?? 0,
            avg_latency_ms: auditData.avg_latency_ms ?? 0,
          });
          setIsLoading(false);
        }
      } catch (err) {
        if (!ignore) {
          setErrorMessage("تعذر الاتصال بالخادم لجلب بيانات لوحة التحكم.");
          setIsLoading(false);
        }
        console.error(err);
      }
    }

    loadInitialData();
    return () => {
      ignore = true;
    };
  }, [escalationFilter]);

  // Set up real-time SSE stream for Level 4 emergency escalations
  useEffect(() => {
    let es;
    try {
      es = createEscalationEventSource();
      eventSourceRef.current = es;

      es.addEventListener("open", () => {
        setIsConnectedSSE(true);
      });

      es.addEventListener("connected", () => {
        setIsConnectedSSE(true);
      });

      // Listen specifically to 'escalation' event frames
      es.addEventListener("escalation", (event) => {
        try {
          const raw = JSON.parse(event.data);
          if (!raw) return;

          // Play emergency chime
          playEmergencyTone();

          // Trigger prominent emergency Banner / Toast
          setLiveAlert({
            session_id: raw.session_id,
            symptom_category: raw.symptom_category,
            recommended_specialty: raw.recommended_specialty,
            detected_red_flags: raw.detected_red_flags || [],
            scrubbed_summary: raw.scrubbed_summary,
            timestamp: new Date().toLocaleTimeString("ar-EG"),
          });

          // Auto-clear banner after 12 seconds
          if (alertDismissTimeoutRef.current) {
            clearTimeout(alertDismissTimeoutRef.current);
          }
          alertDismissTimeoutRef.current = setTimeout(() => {
            setLiveAlert(null);
          }, 12000);

          // Prepend new escalation item to current list dynamically without refresh
          setEscalations((prev) => {
            const exists = prev.some(
              (item) => item.id === raw.id || item.event_id === raw.event_id
            );
            if (exists) return prev;

            const newItem = {
              id: raw.id || raw.event_id || crypto.randomUUID(),
              session_id: raw.session_id,
              created_at: raw.timestamp || new Date().toISOString(),
              symptom_category: raw.symptom_category,
              detected_red_flags: raw.detected_red_flags || [],
              scrubbed_summary: raw.scrubbed_summary || raw.recommended_specialty,
              status: raw.status || "pending",
            };

            return [newItem, ...prev];
          });

          // Increment emergency count
          setMetrics((prev) => ({
            ...prev,
            escalated_count: prev.escalated_count + 1,
            total_count: prev.total_count + 1,
          }));
          setEscalationsCount((prev) => prev + 1);
        } catch (parseErr) {
          console.warn("SSE JSON parse error:", parseErr);
        }
      });

      es.onerror = () => {
        setIsConnectedSSE(false);
      };
    } catch (err) {
      console.warn("EventSource setup failed:", err);
    }

    return () => {
      if (es) es.close();
      if (alertDismissTimeoutRef.current) clearTimeout(alertDismissTimeoutRef.current);
    };
  }, [playEmergencyTone]);

  // Transition escalation status (acknowledged or resolved)
  async function handleStatusChange(escalationId, newStatus) {
    setUpdatingEscalationId(escalationId);
    try {
      const updated = await patchEscalationStatus(escalationId, newStatus);

      setEscalations((prev) =>
        prev.map((item) => {
          if (item.id === escalationId || item.event_id === escalationId) {
            return {
              ...item,
              status: updated.status || newStatus,
              acknowledged_at: updated.acknowledged_at || item.acknowledged_at,
              resolved_at: updated.resolved_at || item.resolved_at,
            };
          }
          return item;
        })
      );
    } catch (err) {
      alert(err.message || "فشل في تحديث حالة البلاغ.");
    } finally {
      setUpdatingEscalationId(null);
    }
  }

  // Format date safely
  function formatDate(isoString) {
    if (!isoString) return "—";
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString("ar-EG", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return String(isoString);
    }
  }

  return (
    <main className="min-h-0 flex-1 overflow-y-auto bg-slate-50 p-4 sm:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        {/* Top Header */}
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 pb-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-black text-slate-900">
                لوحة تحكم الطوارئ وسجلات التدقيق السريري
              </h1>
              <span
                className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold ${
                  isConnectedSSE
                    ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                    : "bg-slate-200 text-slate-700"
                }`}
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    isConnectedSSE ? "bg-emerald-500 animate-ping" : "bg-slate-400"
                  }`}
                />
                {isConnectedSSE ? "متصل لحظياً (Live SSE)" : "غير متصل بالبث"}
              </span>
            </div>
            <p className="mt-1 text-sm text-slate-600">
              متابعة حالات الطوارئ المصعدة فوراً ومراقبة الامتثال لمعايير Zero-PHI
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={reloadAllData}
              disabled={isLoading}
              className="flex items-center gap-2 rounded-xl bg-white border border-slate-300 px-4 py-2 text-xs sm:text-sm font-semibold text-slate-700 hover:bg-slate-100 transition-colors shadow-xs cursor-pointer disabled:opacity-50"
            >
              <svg
                className={`h-4 w-4 ${isLoading ? "animate-spin text-teal-600" : ""}`}
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
              <span>تحديث البيانات</span>
            </button>
          </div>
        </header>

        {/* Live Emergency Alert Banner (Triggered via EventSource) */}
        {liveAlert && (
          <div
            role="alert"
            className="rounded-2xl border-2 border-rose-500 bg-rose-50 p-4 shadow-lg animate-bounce sm:animate-none"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rose-600 text-white text-xl font-bold shadow-sm">
                  🚨
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-base sm:text-lg font-black text-rose-950">
                      تنبيه طوارئ فوري جديد (Level 4 Escalation)!
                    </h3>
                    <span className="rounded bg-rose-200 px-2 py-0.5 text-xs font-mono font-bold text-rose-900">
                      {liveAlert.timestamp}
                    </span>
                  </div>
                  <p className="mt-1 text-sm font-semibold text-rose-900">
                    رقم الجلسة: <bdi className="font-mono">{liveAlert.session_id}</bdi> —{" "}
                    التوجيه: {liveAlert.recommended_specialty}
                  </p>
                  {liveAlert.detected_red_flags.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {liveAlert.detected_red_flags.map((flag, idx) => (
                        <span
                          key={idx}
                          className="rounded-md bg-rose-200 px-2 py-0.5 text-xs font-bold text-rose-900"
                        >
                          ⚠️ {flag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setLiveAlert(null)}
                className="rounded-lg p-1 text-rose-700 hover:bg-rose-200 text-lg leading-none cursor-pointer"
                title="إخفاء التنبيه"
              >
                ✕
              </button>
            </div>
          </div>
        )}

        {/* Error message */}
        {errorMessage && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-800">
            ⚠️ {errorMessage}
          </div>
        )}

        {/* Top 3 Metric Cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {/* Total Count */}
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
            <div className="flex items-center justify-between">
              <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">
                إجمالي الجلسات (Total Sessions)
              </p>
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-teal-50 text-teal-700 font-bold text-sm">
                📊
              </span>
            </div>
            <p className="mt-3 text-3xl font-black text-slate-900">
              {metrics.total_count}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              جلسات فرز مسجلة عبر المنظومة
            </p>
          </div>

          {/* Escalated Count */}
          <div className="rounded-2xl border border-rose-200 bg-white p-5 shadow-xs">
            <div className="flex items-center justify-between">
              <p className="text-xs font-bold text-rose-700 uppercase tracking-wider">
                بلاغات الطوارئ المصعدة (Level 4)
              </p>
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-rose-50 text-rose-700 font-bold text-sm">
                🚨
              </span>
            </div>
            <p className="mt-3 text-3xl font-black text-rose-700">
              {metrics.escalated_count}
            </p>
            <p className="mt-1 text-xs text-rose-600">
              حالات حرجة تم تصعيدها للمستشفى
            </p>
          </div>

          {/* Average Latency */}
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
            <div className="flex items-center justify-between">
              <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">
                متوسط زمن الاستجابة (Latency)
              </p>
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-blue-50 text-blue-700 font-bold text-sm">
                ⚡
              </span>
            </div>
            <p className="mt-3 text-3xl font-black text-slate-900">
              {metrics.avg_latency_ms.toFixed(1)}{" "}
              <span className="text-sm font-semibold text-slate-500">ms</span>
            </p>
            <p className="mt-1 text-xs text-slate-500">
              متوسط سرعة الفرز واستخراج التوصيات
            </p>
          </div>
        </div>

        {/* Section 1: Emergency Escalations Table */}
        <section className="rounded-2xl border border-slate-200 bg-white shadow-xs overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 p-4 sm:p-5">
            <div>
              <div className="flex items-center gap-2">
                <span className="flex h-3 w-3 rounded-full bg-rose-600" />
                <h2 className="text-lg font-bold text-slate-900">
                  بلاغات الطوارئ والمستوى الرابع الحرجة (Active Escalations)
                </h2>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                الحالات التي تتطلب توجيهاً فورياً للمستشفى أو الإسعاف — العدد: {escalationsCount}
              </p>
            </div>

            {/* Filter buttons */}
            <div className="flex items-center gap-1.5 rounded-xl bg-slate-100 p-1 text-xs font-semibold">
              <button
                type="button"
                onClick={() => setEscalationFilter("all")}
                className={`rounded-lg px-3 py-1.5 transition-colors cursor-pointer ${
                  escalationFilter === "all"
                    ? "bg-white text-slate-900 shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                الكل
              </button>
              <button
                type="button"
                onClick={() => setEscalationFilter("pending")}
                className={`rounded-lg px-3 py-1.5 transition-colors cursor-pointer ${
                  escalationFilter === "pending"
                    ? "bg-rose-600 text-white shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                قيد الانتظار (Pending)
              </button>
              <button
                type="button"
                onClick={() => setEscalationFilter("acknowledged")}
                className={`rounded-lg px-3 py-1.5 transition-colors cursor-pointer ${
                  escalationFilter === "acknowledged"
                    ? "bg-blue-600 text-white shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                تم الاستلام (Acknowledged)
              </button>
              <button
                type="button"
                onClick={() => setEscalationFilter("resolved")}
                className={`rounded-lg px-3 py-1.5 transition-colors cursor-pointer ${
                  escalationFilter === "resolved"
                    ? "bg-emerald-600 text-white shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                تم الحل (Resolved)
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px] text-start text-xs sm:text-sm">
              <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                <tr>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    رقم الجلسة
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    التوقيت
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    الفئة السريرية
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    علامات الخطر المرصودة
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    الحالة الحالية
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    إجراءات المشرف
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {escalations.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="p-8 text-center text-slate-500 font-medium">
                      لا توجد بلاغات طوارئ في هذا التصنيف حالياً.
                    </td>
                  </tr>
                ) : (
                  escalations.map((item) => {
                    const status = item.status?.toLowerCase() || "pending";
                    const isPending = status === "pending";
                    const isAck = status === "acknowledged";
                    const isResolved = status === "resolved";

                    return (
                      <tr
                        key={item.id || item.event_id || item.session_id}
                        className="hover:bg-slate-50/70 transition-colors align-middle"
                      >
                        <td className="p-3.5 font-mono text-slate-700">
                          <bdi>{item.session_id}</bdi>
                        </td>
                        <td className="p-3.5 text-slate-500">
                          {formatDate(item.created_at || item.timestamp)}
                        </td>
                        <td className="p-3.5 font-medium text-slate-800">
                          {item.symptom_category || "طوارئ"}
                        </td>
                        <td className="p-3.5">
                          <div className="flex flex-wrap gap-1 max-w-xs">
                            {(item.detected_red_flags || []).length > 0 ? (
                              item.detected_red_flags.map((flag, idx) => (
                                <span
                                  key={idx}
                                  className="rounded bg-rose-100 px-2 py-0.5 text-[11px] font-bold text-rose-900"
                                >
                                  {flag}
                                </span>
                              ))
                            ) : (
                              <span className="text-slate-400 text-xs">
                                {item.scrubbed_summary || "بلاغ طوارئ"}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="p-3.5">
                          {isPending && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-bold text-rose-800">
                              <span className="h-1.5 w-1.5 rounded-full bg-rose-600 animate-pulse" />
                              قيد الانتظار
                            </span>
                          )}
                          {isAck && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-bold text-blue-800">
                              تم الاستلام
                            </span>
                          )}
                          {isResolved && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-bold text-emerald-800">
                              تم الإنهاء والحل
                            </span>
                          )}
                        </td>
                        <td className="p-3.5">
                          <div className="flex items-center gap-2">
                            {isPending && (
                              <button
                                type="button"
                                disabled={updatingEscalationId === item.id}
                                onClick={() =>
                                  handleStatusChange(item.id, "acknowledged")
                                }
                                className="rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white shadow-xs hover:bg-blue-700 disabled:opacity-50 cursor-pointer transition-colors"
                              >
                                {updatingEscalationId === item.id
                                  ? "جاري التحديث..."
                                  : "تأكيد الاستلام"}
                              </button>
                            )}
                            {(isPending || isAck) && (
                              <button
                                type="button"
                                disabled={updatingEscalationId === item.id}
                                onClick={() =>
                                  handleStatusChange(item.id, "resolved")
                                }
                                className="rounded-lg bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white shadow-xs hover:bg-emerald-700 disabled:opacity-50 cursor-pointer transition-colors"
                              >
                                {updatingEscalationId === item.id
                                  ? "جاري التحديث..."
                                  : "إنهاء البلاغ"}
                              </button>
                            )}
                            {isResolved && (
                              <span className="text-xs text-emerald-700 font-medium">
                                مكتمل ✓
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Section 2: Zero-PHI Scrubbed Audit Logs Table */}
        <section className="rounded-2xl border border-slate-200 bg-white shadow-xs overflow-hidden">
          <div className="border-b border-slate-200 p-4 sm:p-5">
            <div className="flex items-center gap-2">
              <span className="flex h-3 w-3 rounded-full bg-teal-600" />
              <h2 className="text-lg font-bold text-slate-900">
                سجل التدقيق السريري المطهر (Zero-PHI Scrubbed Audit Trail)
              </h2>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              إثبات عدم تسريب أي أرقام هواتف أو أسماء مرضى عبر استبدالها آلياً بعلامات التطهير مثل{" "}
              <code className="rounded bg-slate-100 px-1 py-0.5 text-teal-800">[PHONE_NUMBER]</code> و{" "}
              <code className="rounded bg-slate-100 px-1 py-0.5 text-teal-800">[PATIENT_NAME]</code>.
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px] text-start text-xs sm:text-sm">
              <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                <tr>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    الجلسة
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    الشكوى المطهرة (Zero-PHI Input)
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    المستوى
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    التخصص الموصى به
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    الزمن (Latency)
                  </th>
                  <th scope="col" className="p-3.5 text-start font-bold">
                    التوقيت
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {auditLogs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="p-8 text-center text-slate-500 font-medium">
                      لا توجد سجلات تدقيق مسجلة حتى الآن.
                    </td>
                  </tr>
                ) : (
                  auditLogs.map((log) => (
                    <tr
                      key={log.id}
                      className="hover:bg-slate-50/70 transition-colors align-middle"
                    >
                      <td className="p-3.5 font-mono text-slate-700">
                        <bdi>{log.session_id}</bdi>
                      </td>
                      <td className="p-3.5 max-w-md">
                        <p className="font-mono text-xs bg-slate-50 border border-slate-200 rounded p-2 text-slate-800 leading-relaxed whitespace-pre-wrap">
                          {log.scrubbed_input}
                        </p>
                      </td>
                      <td className="p-3.5">
                        <span
                          className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-bold ${
                            log.urgency_level === 4
                              ? "bg-rose-100 text-rose-800"
                              : log.urgency_level === 2
                              ? "bg-blue-100 text-blue-800"
                              : log.urgency_level === 3
                              ? "bg-amber-100 text-amber-800"
                              : "bg-emerald-100 text-emerald-800"
                          }`}
                        >
                          مستوى {log.urgency_level}
                        </span>
                      </td>
                      <td className="p-3.5 font-medium text-slate-800">
                        {log.recommended_specialty || "—"}
                      </td>
                      <td className="p-3.5 font-mono text-slate-600">
                        {log.latency_ms ? `${log.latency_ms.toFixed(1)} ms` : "—"}
                      </td>
                      <td className="p-3.5 text-slate-500">
                        {formatDate(log.created_at)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
