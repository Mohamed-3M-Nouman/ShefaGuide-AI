import { Link } from "react-router";
import { useApp } from "../context/appContext";

const FEATURES = [
  {
    icon: "🗣️",
    title: "فهم دقيق للعامية المصرية",
    desc: "يفهم وصف الأعراض باللهجة المصرية والفصحى ويحولها فوراً لتصنيف سريري موثوق دون تعقيد.",
    accent: "from-teal-500/15 to-emerald-500/10 border-teal-200 dark:border-teal-800/60",
  },
  {
    icon: "🎙️",
    title: "محادثة صوتية ثنائية الاتجاه",
    desc: "سجّل شكواك بصوتك واستمع إلى التوجيه الطبي والتنبيه الوقائي نطقاً بالعربية بضغطة زر.",
    accent: "from-indigo-500/15 to-violet-500/10 border-indigo-200 dark:border-indigo-800/60",
  },
  {
    icon: "📚",
    title: "مصادر طبية معتمدة عالمياً",
    desc: "كل توجيه غير طارئ مدعوم باستشهادات سريرية موثقة من NHS و WHO و Mayo Clinic.",
    accent: "from-sky-500/15 to-cyan-500/10 border-sky-200 dark:border-sky-800/60",
  },
  {
    icon: "🔒",
    title: "خصوصية كاملة Zero-PHI",
    desc: "لا يتم تخزين أي بيانات على جهازك أو خوادم دائمة — تُمسح الجلسة تلقائياً فور إغلاق الصفحة.",
    accent: "from-emerald-500/15 to-teal-500/10 border-emerald-200 dark:border-emerald-800/60",
  },
];

const URGENCY_LEVELS = [
  {
    level: 1,
    color: "#16A34A",
    badge: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950/70 dark:text-emerald-300",
    title: "إحالة روتينية",
    desc: "حالة مستقرة يُنصح بحجز موعد اعتيادي لها في العيادة التخصصية.",
  },
  {
    level: 2,
    color: "#0284C7",
    badge: "bg-sky-100 text-sky-900 dark:bg-sky-950/70 dark:text-sky-300",
    title: "إحالة عاجلة",
    desc: "أعراض تتطلب كشفاً طبياً مبكراً خلال نفس اليوم أو 24 ساعة.",
  },
  {
    level: 3,
    color: "#EA580C",
    badge: "bg-orange-100 text-orange-900 dark:bg-orange-950/70 dark:text-orange-300",
    title: "حالة غير واضحة — راجع طبيباً",
    desc: "توجيه احترازي للفحص المباشر عند غموض الأعراض أو انقطاع الخدمة.",
  },
  {
    level: 4,
    color: "#DC2626",
    badge: "bg-red-100 text-red-900 dark:bg-red-950/70 dark:text-red-300",
    title: "طوارئ قصوى وإسعاف 123",
    desc: "تصعيد فوري عند رصد علامات الخطر الحرجة مع تنبيه لحظي للمشرف.",
  },
];

export default function LandingPage() {
  const { continueAsGuest } = useApp();

  return (
    <main className="min-h-0 flex-1 overflow-y-auto bg-[#F8FAFC] dark:bg-[#0F172A]">
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12 space-y-12">
        {/* Hero Section */}
        <section className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white p-6 sm:p-10 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="pointer-events-none absolute -top-24 -left-24 h-64 w-64 rounded-full bg-[#0D9488]/10 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-24 -right-24 h-64 w-64 rounded-full bg-[#4F46E5]/10 blur-3xl" />

          <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div className="max-w-2xl space-y-5">
              <div className="inline-flex flex-wrap items-center gap-2 rounded-full border border-teal-200 bg-teal-50 px-3.5 py-1 text-xs font-bold text-[#0D9488] dark:border-teal-800/70 dark:bg-teal-950/50 dark:text-teal-300">
                <span>✨</span>
                <span>منصة فرز سريري ذكية باللهجة المصرية</span>
                <span className="font-en text-[#4F46E5] dark:text-indigo-300">
                  • Voice STT/TTS
                </span>
              </div>

              <h1 className="text-3xl sm:text-4xl lg:text-5xl font-black leading-tight text-slate-900 dark:text-white">
                توجيه طبي فوري وآمن
                <span className="block bg-gradient-to-l from-[#0D9488] to-[#4F46E5] bg-clip-text text-transparent">
                  قبل زيارتك للطبيب
                </span>
              </h1>

              <p className="text-sm sm:text-base leading-8 text-slate-600 dark:text-slate-300">
                اشرح ما تشعر به كتابةً أو بصوتك بالعامية المصرية، وسيقوم{" "}
                <strong className="text-slate-900 dark:text-white">شفاء جايد</strong>{" "}
                برصد علامات الخطورة فوراً، وتحديد التخصص الطبي الأنسب مدعوماً بمصادر
                طبية موثوقة، مع إصدار{" "}
                <strong>بطاقة عرض للطبيب جاهزة للطباعة (PDF)</strong> دون حفظ أي
                بيانات شخصية.
              </p>

              {/* Primary & Secondary CTAs */}
              <div className="flex flex-wrap items-center gap-3 pt-1">
                <Link
                  to="/triage"
                  onClick={continueAsGuest}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl bg-[#0D9488] px-6 py-3.5 text-sm sm:text-base font-extrabold text-white shadow-md shadow-teal-600/20 hover:bg-teal-700 transition-all"
                >
                  <span>🩺</span>
                  <span>ابدأ الفرز الفوري كزائر (بدون بيانات)</span>
                </Link>

                <Link
                  to="/auth"
                  className="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-300 bg-white px-5 py-3.5 text-sm sm:text-base font-bold text-slate-800 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700 transition-colors"
                >
                  <span>👤</span>
                  <span>تسجيل الدخول / حساب شخصي</span>
                </Link>
              </div>
            </div>

            {/* Interactive Preview Card on Desktop */}
            <div className="w-full max-w-sm shrink-0 rounded-2xl border border-slate-200 bg-slate-50/90 p-5 shadow-inner dark:border-slate-800 dark:bg-slate-950/60">
              <div className="flex items-center justify-between border-b border-slate-200 pb-3 dark:border-slate-800">
                <span className="text-xs font-bold text-slate-500 dark:text-slate-400">
                  معاينة سريعة للفرز الذكي
                </span>
                <span className="rounded-full bg-[#4F46E5]/10 px-2.5 py-0.5 text-[11px] font-bold text-[#4F46E5] dark:text-indigo-300">
                  صوت + نص
                </span>
              </div>
              <div className="mt-4 space-y-3 text-xs">
                <div className="rounded-xl rounded-te-xs bg-[#0D9488] p-3 text-white shadow-xs">
                  &quot;عندي حرقان جامد في فم المعدة وصعوبة في البلع بقالي يومين&quot;
                </div>
                <div className="rounded-xl border-2 border-[#0284C7] bg-sky-50 p-3.5 text-sky-950 dark:bg-sky-950/40 dark:text-sky-100">
                  <div className="flex items-center justify-between">
                    <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-bold text-sky-900 dark:bg-sky-900 dark:text-sky-200">
                      إحالة عاجلة (المستوى 2)
                    </span>
                    <span className="font-en text-[10px] opacity-70">NHS Citation</span>
                  </div>
                  <p className="mt-2 font-extrabold text-sm">
                    عيادة الباطنة والجهاز الهضمي
                  </p>
                  <p className="mt-1 text-[11px] opacity-85 leading-5">
                    توجيه مبدئي مدعوم بدليل طبي مع إمكانية طباعة بطاقة الطبيب.
                  </p>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between gap-2 text-[11px]">
                <Link
                  to="/profile"
                  className="font-bold text-[#0D9488] hover:underline dark:text-teal-400"
                >
                  تجهيز الخزنة المؤقتة ←
                </Link>
                <Link
                  to="/dashboard"
                  className="font-bold text-[#4F46E5] hover:underline dark:text-indigo-400"
                >
                  لوحة المشرف (SSE) ←
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* 4 Core Feature Cards */}
        <section aria-label="المميزات الرئيسية">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-xl sm:text-2xl font-black text-slate-900 dark:text-white">
                لماذا شفاء جايد؟
              </h2>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                تصميم طبي حديث يجمع بين دقة الفرز السريري وخصوصية المريض الكاملة
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((feat) => (
              <article
                key={feat.title}
                className={`rounded-2xl border bg-gradient-to-br p-5 shadow-xs transition-transform hover:-translate-y-0.5 ${feat.accent}`}
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white text-2xl shadow-xs dark:bg-slate-900">
                  {feat.icon}
                </div>
                <h3 className="mt-4 text-base font-extrabold text-slate-900 dark:text-white">
                  {feat.title}
                </h3>
                <p className="mt-2 text-xs sm:text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {feat.desc}
                </p>
              </article>
            ))}
          </div>
        </section>

        {/* Semantic 4-Level Urgency Scale */}
        <section className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
            <div>
              <h2 className="text-lg sm:text-xl font-black text-slate-900 dark:text-white">
                مقياس الأولوية السريرية رباعي المستويات
              </h2>
              <p className="mt-1 text-xs sm:text-sm text-slate-500 dark:text-slate-400">
                تصنيف لوني واضح يساعد المريض والطبيب على استيعاب درجة الاستعجال من النظرة الأولى
              </p>
            </div>
            <Link
              to="/history"
              className="rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2 text-xs font-bold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            >
              📄 استعراض نماذج البطاقات
            </Link>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {URGENCY_LEVELS.map((u) => (
              <div
                key={u.level}
                className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/60"
              >
                <div className="flex items-center justify-between">
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${u.badge}`}
                  >
                    المستوى {u.level}
                  </span>
                  <span
                    className="h-3 w-3 rounded-full"
                    style={{ backgroundColor: u.color }}
                  />
                </div>
                <h3 className="mt-3 text-sm font-extrabold text-slate-900 dark:text-white">
                  {u.title}
                </h3>
                <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-400">
                  {u.desc}
                </p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
