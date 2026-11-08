import { useState } from "react";
import TriageCard from "./TriageCard";
import { mockResponses } from "../data/mockResponses";
export default function ChatInterface() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [selectedCase, setSelectedCase] = useState("0");
  function handleSubmit(event) {
    event.preventDefault();

    const text = input.trim();

    if (!text) return;

    const newMessage = {
      id: crypto.randomUUID(),
      text,
    };

    setMessages((previousMessages) => [...previousMessages, newMessage]);

    setInput("");
  }

  return (
    <main className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col">
      <header className="shrink-0 border-b border-slate-200 px-4 py-4">
        <h1 className="text-2xl font-bold text-teal-800">شفاء جايد</h1>

        <p className="mt-1 text-sm text-slate-600">
          اكتب الأعراض اللي حاسس بيها، من غير بيانات شخصية.
        </p>
      </header>
      <div className="shrink-0 border-b border-slate-200 bg-white px-4 py-3">
        <label
          htmlFor="demo-case"
          className="mb-2 block text-sm font-semibold text-slate-700"
        >
          معاينة كارت تجريبي — لا يعتمد على الرسائل المكتوبة
        </label>

        <select
          id="demo-case"
          value={selectedCase}
          onChange={(event) => setSelectedCase(event.target.value)}
          className="w-full rounded-lg border border-slate-300 bg-white p-2 text-sm focus:outline-2 focus:outline-teal-600"
        >
          <option value="0">المستوى 4 — طوارئ</option>
          <option value="1">المستوى 2 — إحالة عاجلة</option>
          <option value="2">المستوى 3 — راجع طبيبًا الآن</option>
          <option value="3">المستوى 1 — إحالة روتينية</option>
        </select>
      </div>
      <section
        role="log"
        aria-label="رسائل المحادثة"
        aria-live="polite"
        className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4"
      >
        {messages.length === 0 && (
          <p className="py-12 text-center leading-7 text-slate-500">
            ابدأ بكتابة الأعراض في الخانة اللي تحت.
          </p>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className="w-fit max-w-[90%] rounded-2xl bg-teal-700 px-4 py-3 text-white sm:max-w-[80%]"
          >
            <p className="mb-1 text-xs font-bold text-teal-100">أنت</p>

            <p className="whitespace-pre-wrap leading-7 [overflow-wrap:anywhere]">
              {message.text}
            </p>
          </div>
        ))}
        <TriageCard response={mockResponses[Number(selectedCase)]} />
      </section>

      <form
        onSubmit={handleSubmit}
        className="shrink-0 border-t border-slate-200 bg-white p-4"
      >
        <label
          htmlFor="symptoms"
          className="mb-2 block text-sm font-medium text-slate-700"
        >
          وصف الأعراض
        </label>

        <div className="flex items-center gap-2">
          <input
            id="symptoms"
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="اكتب الأعراض هنا..."
            maxLength={1500}
            autoComplete="off"
            className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-3 text-slate-900 outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
          />

          <button
            type="button"
            disabled
            aria-label="التسجيل الصوتي غير متاح حاليًا"
            title="التسجيل الصوتي غير متاح حاليًا"
            className="flex h-12 w-12 shrink-0 cursor-not-allowed items-center justify-center rounded-xl bg-slate-100 text-slate-400"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="9" y="2" width="6" height="12" rx="3" />
              <path d="M5 10v2a7 7 0 0 0 14 0v-2" />
              <path d="M12 19v3M8 22h8" />
            </svg>
          </button>

          <button
            type="submit"
            disabled={!input.trim()}
            className="shrink-0 rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white hover:bg-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            إرسال
          </button>
        </div>

        <p className="mt-2 text-xs leading-6 text-slate-500">
          نسخة تجريبية للواجهة — الرد الآلي والتسجيل الصوتي غير متاحين حاليًا.
        </p>
      </form>
    </main>
  );
}
