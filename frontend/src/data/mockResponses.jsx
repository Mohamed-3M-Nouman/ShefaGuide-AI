const disclaimer =
  "تنبيه طبي: هذا التوجيه إرشادي فقط ولا يغني عن الفحص الطبي المباشر.";

export const mockResponses = [
  {
    session_id: "sess-001",
    urgency_level: 4,
    recommended_specialty: "طوارئ المستشفى فورًا",
    rationale_ar: "هذه حالة تجريبية لعرض تنبيه يتطلب تقييمًا طبيًا طارئًا.",
    clarifying_questions: [],
    citations: [],
    disclaimer_ar: disclaimer,
    escalation_triggered: true,
    escalation_note:
      "يرجى التوجه فورًا لأقرب قسم طوارئ أو الاتصال بالإسعاف (123).",
  },
  {
    session_id: "sess-002",
    urgency_level: 2,
    recommended_specialty: "عيادة الباطنة والجهاز الهضمي",
    rationale_ar: "هذا مثال تجريبي لعرض تحويل عاجل إلى التخصص المناسب.",
    clarifying_questions: [
      "هل تعاني من صعوبة في البلع؟",
      "من إمتى بدأت الأعراض؟",
    ],
    citations: [
      {
        doc_id: "NHS-GI-001",
        source: "NHS",
        title: "Heartburn and acid reflux",
        url: "https://www.nhs.uk/conditions/heartburn-and-acid-reflux/",
      },
    ],
    disclaimer_ar: disclaimer,
    escalation_triggered: false,
    escalation_note: null,
  },
  {
    session_id: "sess-003",
    urgency_level: 3,
    recommended_specialty: "راجع طبيبًا الآن",
    rationale_ar:
      "هذا مثال تجريبي لحالة غير واضحة لا يمكن توجيهها بثقة إلى تخصص محدد.",
    clarifying_questions: [],
    citations: [],
    disclaimer_ar: disclaimer,
    escalation_triggered: false,
    escalation_note: null,
  },
  {
    session_id: "sess-004",
    urgency_level: 1,
    recommended_specialty: "عيادة العظام",
    rationale_ar: "هذا مثال تجريبي لعرض إحالة روتينية إلى عيادة تخصصية.",
    clarifying_questions: ["من إمتى بدأ الألم؟", "هل الألم بيزيد مع الحركة؟"],
    citations: [
      {
        doc_id: "NHS-MSK-DEMO",
        source: "NHS",
        title: "Joint pain",
        url: "https://www.nhs.uk/conditions/joint-pain/",
      },
    ],
    disclaimer_ar: disclaimer,
    escalation_triggered: false,
    escalation_note: null,
  },
];
