export default function MedicalDisclaimer() {
  return (
    <aside
      aria-label="تنبيه طبي هام"
      className="shrink-0 border-b border-amber-300/80 bg-amber-50 px-4 py-2 text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/50 dark:text-amber-100 print:hidden"
    >
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 text-xs sm:text-sm leading-6">
        <p>
          <strong className="font-extrabold">تنبيه طبي هام: </strong>
          هذا التقييم مبدئي وإرشادي للتوجيه نحو التخصص الطبي المناسب فقط، ولا
          يُعد بديلاً عن التشخيص الطبي الاحترافي أو الفحص المباشر لدى الطبيب.
        </p>
        <a
          href="tel:123"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-red-600 px-3 py-0.5 text-xs font-bold text-white shadow-xs hover:bg-red-700 transition-colors"
        >
          <span>🚨 طوارئ الإسعاف:</span>
          <span className="font-en" dir="ltr">
            123
          </span>
        </a>
      </div>
    </aside>
  );
}
