/**
 * Centralized API service for ShefaGuide AI.
 * Handles Zero-PHI requests, Voice Triage, Speech Synthesis, Escalations, and SSE streams.
 */

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

const SUPERVISOR_STORAGE_KEY = "shefaguide_supervisor_key";

export function getSupervisorKey() {
  try {
    const saved = window.localStorage.getItem(SUPERVISOR_STORAGE_KEY);
    if (saved && saved.trim()) return saved.trim();
  } catch {}
  return (import.meta.env.VITE_SUPERVISOR_KEY ?? "").trim();
}

export function setSupervisorKey(key) {
  try {
    if (key && key.trim()) window.localStorage.setItem(SUPERVISOR_STORAGE_KEY, key.trim());
    else window.localStorage.removeItem(SUPERVISOR_STORAGE_KEY);
  } catch {}
}

function getSupervisorHeaders(extra = {}) {
  const key = getSupervisorKey();
  return key ? { ...extra, "X-Supervisor-Key": key } : { ...extra };
}

/**
 * Format FastAPI error payloads (including 422 validation error arrays) cleanly.
 */
function formatErrorDetail(errorData, fallbackMessage) {
  const detail = errorData?.detail;
  if (!detail) return fallbackMessage;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const joined = detail
      .map((item) => item?.msg || (typeof item === "string" ? item : JSON.stringify(item)))
      .filter(Boolean)
      .join(" | ");
    return joined || fallbackMessage;
  }
  if (typeof detail === "object") {
    return detail.message || JSON.stringify(detail);
  }
  return String(detail);
}

/**
 * Standard fallback response when backend is unreachable.
 */
export const SAFE_FALLBACK_RESPONSE = {
  session_id: "offline-fallback",
  urgency_level: 3,
  recommended_specialty: "طبيب عام / طوارئ للفحص المباشر",
  symptom_category: "unknown",
  rationale_ar:
    "تعذر الاتصال بالخادم حالياً — يرجى التوجه لطبيب مختص لتقييم حالتك مباشرة أو مراجعة أقرب مركز طبي.",
  clarifying_questions: [],
  negated_red_flags: [],
  citations: [],
  disclaimer_ar:
    "تنبيه طبي هام: هذا التقييم مبدئي وإرشادي فقط ولا يغني عن الفحص الطبي المباشر أو استشارة الطبيب المختص. في حالات الطوارئ يرجى التوجه لأقرب مستشفى أو الاتصال بالإسعاف (123) فوراً.",
  escalation_triggered: false,
  is_offline_fallback: true,
};

/**
 * Submit patient symptoms for clinical triage evaluation.
 * Strict TriageRequest contract: { session_id, user_input, input_mode }.
 * @param {{ session_id: string, user_input: string, input_mode?: string, signal?: AbortSignal }} payload
 */
export async function sendTriageRequest({
  session_id,
  user_input,
  input_mode = "text",
  signal,
}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/triage`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      session_id,
      user_input,
      input_mode,
    }),
    signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      formatErrorDetail(errorData, `خطأ في الخادم (رمز الحالة: ${response.status})`)
    );
  }

  return await response.json();
}

/**
 * Send voice audio payload for end-to-end voice triage (STT -> Triage -> TTS).
 * @param {{ session_id: string, audio_base64?: string|null, filename?: string, language?: string, fallback_text?: string|null, signal?: AbortSignal }} payload
 */
export async function sendVoiceTriage({
  session_id,
  audio_base64,
  filename = "audio.webm",
  language = "ar",
  fallback_text = null,
  signal,
}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/voice/triage`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      session_id,
      audio_base64: audio_base64 || null,
      filename,
      language,
      fallback_text: fallback_text || null,
    }),
    signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      formatErrorDetail(errorData, `خطأ في معالجة الصوت (رمز الحالة: ${response.status})`)
    );
  }

  return await response.json();
}

/**
 * Request speech synthesis (TTS) for Arabic text with guaranteed disclaimer.
 * @param {{ session_id: string, text: string, include_disclaimer?: boolean, signal?: AbortSignal }} payload
 */
export async function synthesizeVoice({
  session_id,
  text,
  include_disclaimer = true,
  signal,
}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/voice/synthesize`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      session_id,
      text,
      include_disclaimer,
    }),
    signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      formatErrorDetail(errorData, `تعذر توليد الصوت (رمز الحالة: ${response.status})`)
    );
  }

  return await response.json();
}

/**
 * Fetch emergency escalations for the supervisor dashboard.
 * @param {{ status?: string, limit?: number }} params
 */
export async function fetchEscalations({ status, limit = 50 } = {}) {
  const base = API_BASE_URL || window.location.origin;
  const url = new URL(`${base}/api/v1/escalations`);
  if (status) url.searchParams.set("status", status);
  if (limit) url.searchParams.set("limit", String(limit));

  const response = await fetch(url.toString(), {
    headers: getSupervisorHeaders({ Accept: "application/json" }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      formatErrorDetail(errorData, `تعذر جلب بلاغات الطوارئ (${response.status})`)
    );
  }

  return await response.json();
}

/**
 * Transition escalation status (acknowledged or resolved).
 * @param {string} escalationId
 * @param {"acknowledged" | "resolved"} status
 */
export async function patchEscalationStatus(escalationId, status) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/escalations/${encodeURIComponent(escalationId)}`,
    {
      method: "PATCH",
      headers: {
        ...getSupervisorHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
      },
      body: JSON.stringify({ status }),
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      formatErrorDetail(errorData, `تعذر تحديث حالة البلاغ (${response.status})`)
    );
  }

  return await response.json();
}

/**
 * Fetch Zero-PHI audit logs and aggregated metrics.
 * @param {{ limit?: number, escalated_only?: boolean }} params
 */
export async function fetchAuditLogs({ limit = 50, escalated_only = false } = {}) {
  const base = API_BASE_URL || window.location.origin;
  const url = new URL(`${base}/api/v1/audit-logs`);
  if (limit) url.searchParams.set("limit", String(limit));
  if (escalated_only) url.searchParams.set("escalated_only", "true");

  const response = await fetch(url.toString(), {
    headers: getSupervisorHeaders({ Accept: "application/json" }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      formatErrorDetail(errorData, `تعذر جلب سجلات التدقيق (${response.status})`)
    );
  }

  return await response.json();
}

/**
 * Create an EventSource connection for real-time emergency escalations stream.
 */
export function createEscalationEventSource() {
  return (() => { const k = getSupervisorKey(); const u = new URL(`${API_BASE_URL}/api/v1/escalations/stream`); if (k) u.searchParams.set("supervisor_key", k); return new EventSource(u.toString()); })();
}
