const disclaimer =
  "تنبيه طبي هام: هذا التقييم مبدئي وإرشادي فقط ولا يغني عن الفحص الطبي المباشر أو استشارة الطبيب المختص. في حالات الطوارئ يرجى التوجه لأقرب مستشفى أو الاتصال بالإسعاف (123) فوراً.";

export const mockResponses = [
  {
    session_id: "sess-001",
    urgency_level: 4,
    recommended_specialty: "طوارئ المستشفى فوراً",
    symptom_category: "cardiopulmonary",
    rationale_ar:
      "تم رصد علامات تحذيرية حرجة تستدعي تقييماً طبياً طارئاً وفورياً في أقرب قسم طوارئ مستشفى دون تأخير.",
    clarifying_questions: [],
    negated_red_flags: [],
    citations: [],
    disclaimer_ar: disclaimer,
    escalation_triggered: true,
    escalation_note:
      "يرجى التوجه فوراً لأقرب قسم طوارئ أو الاتصال بالإسعاف (123).",
    detected_red_flags: [
      "ألم حاد ومفاجئ في الصدر",
      "صعوبة وضيق في التنفس",
      "تعرق بارد مصاحب للدوخة",
    ],
  },
  {
    session_id: "sess-002",
    urgency_level: 2,
    recommended_specialty: "عيادة الباطنة والجهاز الهضمي",
    symptom_category: "gastrointestinal",
    rationale_ar:
      "الأعراض الموصوفة تشير لاحتمال التهاب أو ارتجاع في المريء يتطلب كشفاً عاجلاً لدى طبيب باطنة وجهاز هضمي لتقييم صعوبة البلع.",
    clarifying_questions: [
      "هل تعاني من صعوبة في بلع السوائل أم الطعام الصلب؟",
      "هل يصاحب الحرقان قيء أو فقدان غير مبرر في الوزن؟",
    ],
    negated_red_flags: ["لا يوجد ألم صدر مسمع في الذراع", "لا يوجد قيء دموي"],
    citations: [
      {
        doc_id: "NHS-GI-001",
        source: "NHS",
        title: "Heartburn and acid reflux",
        url: "https://www.nhs.uk/conditions/heartburn-and-acid-reflux/",
        snippet:
          "Severe or frequent heartburn with difficulty swallowing requires timely medical evaluation by a specialist.",
      },
    ],
    disclaimer_ar: disclaimer,
    escalation_triggered: false,
    escalation_note: null,
  },
  {
    session_id: "sess-003",
    urgency_level: 3,
    recommended_specialty: "راجع طبيباً مختصاً للتقييم المباشر",
    symptom_category: "unknown",
    rationale_ar:
      "الأعراض الموصوفة عامة وغير محددة بشكل كافٍ لتحديد تخصص دقيق بثقة، لذا يوصى بمراجعة طبيب باطنة أو طبيب أسرة للفحص المباشر.",
    clarifying_questions: [
      "هل توجد حرارة مرتفعة أو تغيرات في الشهية؟",
      "منذ متى بدأت هذه الأعراض بالضبط؟",
    ],
    negated_red_flags: [],
    citations: [],
    disclaimer_ar: disclaimer,
    escalation_triggered: false,
    escalation_note: null,
  },
  {
    session_id: "sess-004",
    urgency_level: 1,
    recommended_specialty: "عيادة جراحة العظام والمفاصل",
    symptom_category: "musculoskeletal",
    rationale_ar:
      "ألم الركبة المرتبط بالمشي وصعود السلم دون تورم حاد أو إصابة مفاجئة يناسب الحجز في عيادة العظام للمتابعة الروتينية.",
    clarifying_questions: [
      "هل يوجد تورم ملحوظ أو سخونة في مفصل الركبة؟",
      "هل سبق وتعرضت لإصابة أو التواء في الركبة؟",
    ],
    negated_red_flags: ["لا يوجد فقدان قدرة مفاجئ على تحميل الوزن"],
    citations: [
      {
        doc_id: "NHS-MSK-DEMO",
        source: "NHS",
        title: "Knee pain assessment",
        url: "https://www.nhs.uk/conditions/knee-pain/",
        snippet:
          "Persistent mechanical knee pain aggravated by walking or stairs should be evaluated in an orthopedic outpatient clinic.",
      },
    ],
    disclaimer_ar: disclaimer,
    escalation_triggered: false,
    escalation_note: null,
  },
];
