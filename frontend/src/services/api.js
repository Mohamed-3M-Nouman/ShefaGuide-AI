/**
 * Centralized API service for ShefaGuide AI.
 * Handles Zero-PHI requests, Voice Triage, Speech Synthesis, Escalations, and SSE streams.
 */

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

/**
 * Standard fallback message when server is unreachable.
 */
export const SAFE_FALLBACK_RESPONSE = {
  session_id: "offline-fallback",
  urgency_level: 3,
  recommended_specialty: "طبيب عام / طوارئ للفحص المباشر",
  symptom_category: "unknown",
  rationale_ar:
    "تعذر الاتصال بالخادم حالياً — يرجى التوجه لطبيب مختص لتقييم حالتك مباشرة.",
  clarifying_questions: [],
  negated_red_flags: [],
  citations: [],
  disclaimer_ar:
    "تنبيه طبي هام: هذا التقييم مبدئي وإرشادي فقط ولا يغني عن الفحص الطبي المباشر أو استشارة الطبيب المختص. في حالات الطوارئ يرجى التوجه لأقرب مستشفى أو الاتصال بالإسعاف (123) فوراً.",
  escalation_triggered: false,
  is_offline_fallback: true,
};

/**
 * Submit patient symptoms for triage evaluation.
 * @param {{ session_id: string, user_input: string, input_mode?: string }} payload
 * @returns {Promise<any>}
 */
export async function sendTriageRequest({
  session_id,
  user_input,
  input_mode = "text",
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
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      errorData?.detail || `خطأ في الخادم (رمز الحالة: ${response.status})`
    );
  }

  return await response.json();
}

/**
 * Send voice audio payload for end-to-end voice triage (STT -> Triage -> TTS).
 * @param {{ session_id: string, audio_base64?: string, filename?: string, language?: string, fallback_text?: string }} payload
 * @returns {Promise<any>}
 */
export async function sendVoiceTriage({
  session_id,
  audio_base64,
  filename = "audio.webm",
  language = "ar",
  fallback_text = "",
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
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      errorData?.detail || `خطأ في معالجة الصوت (رمز الحالة: ${response.status})`
    );
  }

  return await response.json();
}

/**
 * Request speech synthesis (TTS) for Arabic text with guaranteed disclaimer.
 * @param {{ session_id: string, text: string, include_disclaimer?: boolean }} payload
 * @returns {Promise<any>}
 */
export async function synthesizeVoice({
  session_id,
  text,
  include_disclaimer = true,
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
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      errorData?.detail || `تعذر توليد الصوت (رمز الحالة: ${response.status})`
    );
  }

  return await response.json();
}

/**
 * Fetch emergency escalations for the supervisor dashboard.
 * @param {{ status?: string, limit?: number }} params
 * @returns {Promise<{ items: any[], count: number }>}
 */
export async function fetchEscalations({ status, limit = 50 } = {}) {
  const url = new URL(`${API_BASE_URL}/api/v1/escalations`);
  if (status) url.searchParams.set("status", status);
  if (limit) url.searchParams.set("limit", String(limit));

  const response = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error(`تعذر جلب بلاغات الطوارئ (${response.status})`);
  }

  return await response.json();
}

/**
 * Transition escalation status (acknowledged or resolved).
 * @param {string} escalationId
 * @param {"acknowledged" | "resolved"} status
 * @returns {Promise<any>}
 */
export async function patchEscalationStatus(escalationId, status) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/escalations/${encodeURIComponent(escalationId)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ status }),
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(
      errorData?.detail || `تعذر تحديث حالة البلاغ (${response.status})`
    );
  }

  return await response.json();
}

/**
 * Fetch Zero-PHI audit logs and aggregated metrics.
 * @param {{ limit?: number, escalated_only?: boolean }} params
 * @returns {Promise<{ items: any[], total_count: number, escalated_count: number, avg_latency_ms: number }>}
 */
export async function fetchAuditLogs({ limit = 50, escalated_only = false } = {}) {
  const url = new URL(`${API_BASE_URL}/api/v1/audit-logs`);
  if (limit) url.searchParams.set("limit", String(limit));
  if (escalated_only) url.searchParams.set("escalated_only", "true");

  const response = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error(`تعذر جلب سجلات التدقيق (${response.status})`);
  }

  return await response.json();
}

/**
 * Create an EventSource connection for real-time emergency escalations stream.
 * @returns {EventSource}
 */
export function createEscalationEventSource() {
  return new EventSource(`${API_BASE_URL}/api/v1/escalations/stream`);
}
