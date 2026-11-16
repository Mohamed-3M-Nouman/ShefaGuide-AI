import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchEscalations,
  patchEscalationStatus,
  fetchAuditLogs,
  createEscalationEventSource,
} from "../services/api";

export default function Dashboard() {
  const [escalations, setEscalations] = useState([]);
  const [escalationsCount, setEscalationsCount] = useState(0);
  const [escalationFilter, setEscalationFilter] = useState("all");
  const [updatingEscalationId, setUpdatingEscalationId] = useState(null);

  const [auditLogs, setAuditLogs] = useState([]);
  const [metrics, setMetrics] = useState({
    total_count: 0,
    escalated_count: 0,
    avg_latency_ms: 0,
  });

  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState(null);
  const [liveAlert, setLiveAlert] = useState(null);
  const [isConnectedSSE, setIsConnectedSSE] = useState(false);

  const eventSourceRef = useRef(null);
  const alertDismissTimeoutRef = useRef(null);
  const audioCtxRef = useRef(null);

  // Reusable Web AudioContext emergency chime (avoids hitting browser 6-context cap)
  const playEmergencyTone = useCallback(() => {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
        audioCtxRef.current = new AudioCtx();
      }
      const ctx = audioCtxRef.current;
      if (ctx.state === "suspended") {
        ctx.resume().catch(() => {});
      }

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = "sine";
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.3);

      gain.setValueAtTime(0.3, ctx.currentTime);
      gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    } catch {
      // Non-fatal if blocked by autoplay policy
    }
  }, []);

  useEffect(() => {
    return () => {
      if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
        audioCtxRef.current.close().catch(() => {});
      }
    };
  }, []);

  const reloadAllData = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const filterParam =
        escalationFilter === "all" ? undefined : escalationFilter;
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

  useEffect(() => {
    let ignore = false;
    async function loadInitialData() {
      try {
        const filterParam =
          escalationFilter === "all" ? undefined : escalationFilter;
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

  // Real-time SSE subscription for Level 4 emergency escalations
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

      es.addEventListener("escalation", (event) => {
        try {
          const raw = JSON.parse(event.data);
          if (!raw) return;

          playEmergencyTone();

          setLiveAlert({
            session_id: raw.session_id,
            symptom_category: raw.symptom_category,
            recommended_specialty: raw.recommended_specialty,
            detected_red_flags: raw.detected_red_flags || [],
            scrubbed_summary: raw.scrubbed_summary,
            timestamp: new Date().toLocaleTimeString("ar-EG"),
          });

          if (alertDismissTimeoutRef.current) {
            clearTimeout(alertDismissTimeoutRef.current);
          }
          alertDismissTimeoutRef.current = setTimeout(() => {
            setLiveAlert(null);
          }, 12000);

          // Sync from DB endpoints so newly persisted EscalationAlert UUIDs are immediately patchable
          const filterParam =
            escalationFilter === "all" ? undefined : escalationFilter;
          Promise.all([
            fetchEscalations({ status: filterParam, limit: 50 }),
            fetchAuditLogs({ limit: 50 }),
          ])
            .then(([escData, auditData]) => {
              setEscalations(escData.items || []);
              setEscalationsCount(escData.count ?? escData.items?.length ?? 0);
              setAuditLogs(auditData.items || []);
              setMetrics({
                total_count: auditData.total_count ?? 0,
                escalated_count: auditData.escalated_count ?? 0,
                avg_latency_ms: auditData.avg_latency_ms ?? 0,
              });
            })
            .catch(() => {
              setEscalations((prev) => {
                const exists = prev.some(
                  (item) => item.id === raw.id || item.event_id === raw.event_id
                );
                if (exists) return prev;
                return [
                  {
                    id: raw.id || raw.event_id || crypto.randomUUID(),
                    session_id: raw.session_id,
                    created_at: raw.timestamp || new Date().toISOString(),
                    symptom_category: raw.symptom_category,
                    detected_red_flags: raw.detected_red_flags || [],
                    scrubbed_summary:
                      raw.scrubbed_summary || raw.recommended_specialty,
                    status: raw.status || "pending",
                  },
                  ...prev,
                ];
              });
            });
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
      if (alertDismissTimeoutRef.current) {
        clearTimeout(alertDismissTimeoutRef.current);
      }
    };
  }, [playEmergencyTone, escalationFilter]);

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
      setErrorMessage(err.message || "فشل في تحديث حالة البلاغ.");
    } finally {
      setUpdatingEscalationId(null);
    }
  }

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
    <main className="min-h-0 flex-1 overflow-y-auto bg-[#F8FAFC] p-4 sm:p-6 dark:bg-[#0F172A]">
      <div className="mx-auto max-w-7xl space-y-6">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 pb-4 dark:border-slate-800">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl sm:text-2xl font-black text-slate-900 dark:text-white">
                لوحة تحكم الطوارئ وسجلات التدقيق السريري
              </h1>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-0.5 text-xs font-bold ${
                  isConnectedSSE
                    ? "border border-emerald-300 bg-emerald-100 text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200"
                    : "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                }`}
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    isConnectedSSE ? "bg-emerald-500 animate-ping" : "bg-slate-400"
                  }`}
                />
                <span>
                  {isConnectedSSE ? "متصل لحظياً (Live SSE)" : "غير متصل بالبث"}
                </span>
              </span>
            </div>
            <p className="mt-1 text-xs sm:text-sm text-slate-600 dark:text-slate-400">
              متابعة حالات الطوارئ المصعدة فوراً ومراقبة الامتثال لمعايير Zero-PHI
            </p>
          </div>

          <button
            type="button"
            onClick={reloadAllData}
            disabled={isLoading}
            className="flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs sm:text-sm font-bold text-slate-700 shadow-xs hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800 transition-colors cursor-pointer"
          >
            <span>{isLoading ? "جاري التحديث..." : "🔄 تحديث البيانات"}</span>
          </button>
        </header>

        {/* Live SSE Alert Banner */}
        {liveAlert && (
          <div
            role="alert"
            className="rounded-2xl border-2 border-[#DC2626] bg-red-50 p-4 shadow-lg dark:bg-red-950/70"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#DC2626] text-white text-xl font-bold">
                  🚨
                </span>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base sm:text-lg font-black text-red-950 dark:text-white">
                      تنبيه طوارئ فوري جديد (Level 4 Escalation)!
                    </h3>
                    <span className="font-en rounded bg-red-200 px-2 py-0.5 text-xs font-bold text-red-900">
                      {liveAlert.timestamp}
                    </span>
                  </div>
                  <p className="mt-1 text-xs sm:text-sm font-semibold text-red-900 dark:text-red-100">
                    رقم الجلسة:{" "}
                    <bdi className="font-en">{liveAlert.session_id}</bdi> —{" "}
                    التوجيه: {liveAlert.recommended_specialty}
                  </p>
                  {liveAlert.detected_red_flags.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {liveAlert.detected_red_flags.map((flag, idx) => (
                        <span
                          key={idx}
                          className="rounded-md bg-red-200 px-2 py-0.5 text-xs font-bold text-red-950"
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
                className="rounded-lg p-1 text-red-700 hover:bg-red-200 text-lg leading-none cursor-pointer dark:text-red-200"
              >
                ✕
              </button>
            </div>
          </div>
        )}

        {errorMessage && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs sm:text-sm font-semibold text-rose-800 dark:border-rose-900 dark:bg-rose-950/60 dark:text-rose-200">
            ⚠️ {errorMessage}
          </div>
        )}

        {/* Top 3 KPI Metric Cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center justify-between">
              <p className="text-xs font-bold text-slate-500 dark:text-slate-400">
                إجمالي الجلسات (Total Sessions)
              </p>
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-teal-50 text-sm dark:bg-teal-950">
                📊
              </span>
            </div>
            <p className="font-en mt-3 text-3xl font-black text-slate-900 dark:text-white">
              {metrics.total_count}
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              جلسات فرز مسجلة عبر المنظومة
            </p>
          </div>

          <div className="rounded-2xl border border-red-200 bg-white p-5 shadow-xs dark:border-red-900/60 dark:bg-slate-900">
            <div className="flex items-center justify-between">
              <p className="text-xs font-bold text-[#DC2626] dark:text-red-400">
                بلاغات الطوارئ المصعدة (Level 4)
              </p>
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-red-50 text-sm dark:bg-red-950">
                🚨
              </span>
            </div>
            <p className="font-en mt-3 text-3xl font-black text-[#DC2626] dark:text-red-400">
              {metrics.escalated_count}
            </p>
            <p className="mt-1 text-xs text-red-600 dark:text-red-300">
              حالات حرجة تم تصعيدها للطوارئ
            </p>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center justify-between">
              <p className="text-xs font-bold text-slate-500 dark:text-slate-400">
                متوسط زمن الاستجابة (Latency)
              </p>
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-50 text-sm dark:bg-indigo-950">
                ⚡
              </span>
            </div>
            <p className="font-en mt-3 text-3xl font-black text-slate-900 dark:text-white">
              {metrics.avg_latency_ms.toFixed(1)}{" "}
              <span className="text-sm font-semibold text-slate-500">ms</span>
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              متوسط سرعة الفرز واستخراج التوصيات
            </p>
          </div>
        </div>

        {/* Section 1: Real-Time SSE Escalation Queue */}
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 p-4 sm:p-5 dark:border-slate-800">
            <div>
              <div className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-full bg-[#DC2626]" />
                <h2 className="text-base sm:text-lg font-bold text-slate-900 dark:text-white">
                  بلاغات الطوارئ والمستوى الرابع الحرجة (Active Escalations)
                </h2>
              </div>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                الحالات التي تتطلب توجيهاً فورياً للمستشفى أو الإسعاف — العدد:{" "}
                {escalationsCount}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-1.5 rounded-xl bg-slate-100 p-1 text-xs font-semibold dark:bg-slate-800">
              {[
                { id: "all", label: "الكل", activeCls: "bg-white text-slate-900 dark:bg-slate-900 dark:text-white" },
                { id: "pending", label: "قيد الانتظار (Pending)", activeCls: "bg-[#DC2626] text-white" },
                { id: "acknowledged", label: "تم الاستلام (Acknowledged)", activeCls: "bg-[#0284C7] text-white" },
                { id: "resolved", label: "تم الحل (Resolved)", activeCls: "bg-[#16A34A] text-white" },
              ].map((btn) => (
                <button
                  key={btn.id}
                  type="button"
                  onClick={() => setEscalationFilter(btn.id)}
                  className={`rounded-lg px-3 py-1.5 transition-colors cursor-pointer ${
                    escalationFilter === btn.id
                      ? `${btn.activeCls} shadow-xs`
                      : "text-slate-600 hover:text-slate-900 dark:text-slate-300"
                  }`}
                >
                  {btn.label}
                </button>
              ))}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px] text-start text-xs sm:text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-800/60 dark:text-slate-300">
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
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {escalations.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="p-8 text-center text-slate-500 dark:text-slate-400 font-medium"
                    >
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
                        className="hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors align-middle"
                      >
                        <td className="font-en whitespace-nowrap p-3.5 text-slate-700 dark:text-slate-200">
                          <bdi>{item.session_id}</bdi>
                        </td>
                        <td className="font-en whitespace-nowrap p-3.5 text-slate-500 dark:text-slate-400">
                          {formatDate(item.created_at || item.timestamp)}
                        </td>
                        <td className="p-3.5 font-medium text-slate-800 dark:text-slate-200">
                          {item.symptom_category || "طوارئ"}
                        </td>
                        <td className="p-3.5">
                          <div className="flex flex-wrap gap-1 max-w-xs">
                            {(item.detected_red_flags || []).length > 0 ? (
                              item.detected_red_flags.map((flag, idx) => (
                                <span
                                  key={idx}
                                  className="rounded bg-red-100 px-2 py-0.5 text-[11px] font-bold text-red-900 dark:bg-red-950 dark:text-red-200"
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
                        <td className="whitespace-nowrap p-3.5">
                          {isPending && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-bold text-red-800 dark:bg-red-950 dark:text-red-200">
                              <span className="h-1.5 w-1.5 rounded-full bg-red-600 animate-pulse" />
                              قيد الانتظار
                            </span>
                          )}
                          {isAck && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-bold text-sky-800 dark:bg-sky-950 dark:text-sky-200">
                              تم الاستلام
                            </span>
                          )}
                          {isResolved && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-bold text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
                              تم الإنهاء والحل
                            </span>
                          )}
                        </td>
                        <td className="whitespace-nowrap p-3.5">
                          <div className="flex items-center gap-2">
                            {isPending && (
                              <button
                                type="button"
                                disabled={updatingEscalationId === item.id}
                                onClick={() =>
                                  handleStatusChange(item.id, "acknowledged")
                                }
                                className="rounded-lg bg-[#0284C7] px-2.5 py-1 text-xs font-semibold text-white hover:bg-sky-700 disabled:opacity-50 cursor-pointer transition-colors"
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
                                className="rounded-lg bg-[#16A34A] px-2.5 py-1 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50 cursor-pointer transition-colors"
                              >
                                {updatingEscalationId === item.id
                                  ? "جاري التحديث..."
                                  : "إنهاء البلاغ"}
                              </button>
                            )}
                            {isResolved && (
                              <span className="text-xs text-[#16A34A] dark:text-emerald-400 font-bold">
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
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <div className="border-b border-slate-200 p-4 sm:p-5 dark:border-slate-800">
            <div className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-full bg-[#0D9488]" />
              <h2 className="text-base sm:text-lg font-bold text-slate-900 dark:text-white">
                سجل التدقيق السريري المطهر (Zero-PHI Scrubbed Audit Trail)
              </h2>
            </div>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              إثبات عدم تسريب أي أرقام هواتف أو أسماء مرضى عبر استبدالها آلياً بعلامات التطهير مثل{" "}
              <code className="font-en rounded bg-slate-100 px-1 py-0.5 text-[#0D9488] dark:bg-slate-800">
                [PHONE_NUMBER]
              </code>{" "}
              و{" "}
              <code className="font-en rounded bg-slate-100 px-1 py-0.5 text-[#0D9488] dark:bg-slate-800">
                [PATIENT_NAME]
              </code>
              .
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px] text-start text-xs sm:text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-800/60 dark:text-slate-300">
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
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {auditLogs.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="p-8 text-center text-slate-500 dark:text-slate-400 font-medium"
                    >
                      لا توجد سجلات تدقيق مسجلة حتى الآن.
                    </td>
                  </tr>
                ) : (
                  auditLogs.map((log) => (
                    <tr
                      key={log.id}
                      className="hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors align-middle"
                    >
                      <td className="font-en whitespace-nowrap p-3.5 text-slate-700 dark:text-slate-200">
                        <bdi>{log.session_id}</bdi>
                      </td>
                      <td className="p-3.5 max-w-md">
                        <p className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs text-slate-800 leading-relaxed whitespace-pre-wrap dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
                          {log.scrubbed_input}
                        </p>
                      </td>
                      <td className="whitespace-nowrap p-3.5">
                        <span
                          className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-bold ${
                            log.urgency_level === 4
                              ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200"
                              : log.urgency_level === 2
                              ? "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200"
                              : log.urgency_level === 3
                              ? "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-200"
                              : "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
                          }`}
                        >
                          مستوى {log.urgency_level}
                        </span>
                      </td>
                      <td className="p-3.5 font-medium text-slate-800 dark:text-slate-200">
                        {log.recommended_specialty || "—"}
                      </td>
                      <td className="font-en whitespace-nowrap p-3.5 text-slate-600 dark:text-slate-300">
                        {log.latency_ms ? `${log.latency_ms.toFixed(1)} ms` : "—"}
                      </td>
                      <td className="font-en whitespace-nowrap p-3.5 text-slate-500 dark:text-slate-400">
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
