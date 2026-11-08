import { mockResponses } from "../data/mockResponses";

export default function Dashboard() {
  const escalations = mockResponses.filter(
    (response) => response.escalation_triggered === true,
  );

  return (
    <main className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
      <div className="mx-auto max-w-6xl">
        <header>
          <h1 className="text-2xl font-bold text-slate-900">
            لوحة متابعة حالات الطوارئ
          </h1>

          <p className="mt-2 leading-7 text-slate-600">
            بيانات تجريبية ثابتة لعرض الحالات التي تم تصعيدها.
          </p>

          <p className="mt-3 font-semibold text-red-700">
            عدد الحالات: {escalations.length}
          </p>
        </header>

        <div className="mt-6 overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[700px] text-start text-sm">
            <caption className="sr-only">
              حالات الطوارئ الموجودة في بيانات التجربة
            </caption>

            <thead className="bg-slate-100 text-slate-700">
              <tr>
                <th scope="col" className="p-4 text-start">
                  رقم الجلسة
                </th>

                <th scope="col" className="p-4 text-start">
                  مستوى الاستعجال
                </th>

                <th scope="col" className="p-4 text-start">
                  التوجيه
                </th>

                <th scope="col" className="p-4 text-start">
                  التفسير
                </th>

                <th scope="col" className="p-4 text-start">
                  ملاحظة التصعيد
                </th>
              </tr>
            </thead>

            <tbody>
              {escalations.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-slate-500">
                    لا توجد حالات طوارئ في بيانات التجربة.
                  </td>
                </tr>
              ) : (
                escalations.map((item) => (
                  <tr
                    key={item.session_id}
                    className="border-t border-slate-200 align-top hover:bg-slate-50"
                  >
                    <td className="p-4">
                      <bdi className="font-mono">{item.session_id}</bdi>
                    </td>

                    <td className="p-4">
                      <span className="inline-block whitespace-nowrap rounded-full bg-red-100 px-3 py-1 font-semibold text-red-800">
                        المستوى {item.urgency_level}
                      </span>
                    </td>

                    <td className="p-4 font-semibold leading-7">
                      {item.recommended_specialty}
                    </td>

                    <td className="p-4 leading-7 text-slate-600">
                      {item.rationale_ar}
                    </td>

                    <td className="p-4 leading-7 text-red-800">
                      {item.escalation_note || "لا توجد ملاحظة إضافية"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
