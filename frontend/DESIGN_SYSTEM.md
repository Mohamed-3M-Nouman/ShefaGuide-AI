# ShefaGuide AI — Design System Rules (`frontend/DESIGN_SYSTEM.md`)

Comprehensive Figma MCP & frontend engineering rules for the **ShefaGuide AI (شفاء جايد)** RTL Arabic Healthcare Triage SaaS.

---

## 1. Token Definitions

Design tokens are defined using **CSS Custom Properties (`:root`)** and **Tailwind CSS v4 (`@import "tailwindcss";`)** in `frontend/src/index.css`, paired with Google Fonts loaded in `frontend/index.html`.

```css
/* frontend/src/index.css */
@import "tailwindcss";
@custom-variant dark (&:where(.dark, .dark *));

:root {
  --font-sans: "Cairo", system-ui, -apple-system, sans-serif;
  --font-mono: "Inter", ui-monospace, SFMono-Regular, monospace;
  --color-brand-teal: #0D9488;
  --color-ai-indigo: #4F46E5;
  --color-urgency-1: #16A34A;
  --color-urgency-2: #0284C7;
  --color-urgency-3: #EA580C;
  --color-urgency-4: #DC2626;
}
```

- **Brand & Surface Palette:**
  - Primary Brand (`Healing Teal`): `#0D9488`
  - AI & Voice Accent (`Deep Indigo`): `#4F46E5`
  - Light / Dark Surfaces: `#F8FAFC` / `#0F172A`
- **Semantic Urgency Levels:**
  - Level 1 (`Routine Specialist`): `#16A34A`
  - Level 2 (`Urgent Specialist`): `#0284C7`
  - Level 3 (`Ambiguous — See a Doctor`): `#EA580C`
  - Level 4 (`Emergency Escalation`): `#DC2626`
- **Typography:**
  - Arabic UI (`body`): `Cairo` (`400`–`900`)
  - English clinical codes, URLs, session IDs, and latencies (`.font-en`): `Inter` (`400`–`700`) with `<bdi>` isolation inside RTL layouts.

---

## 2. Component Library

UI components live under `frontend/src/components/` and page views under `frontend/src/pages/`. Components are stateless-by-default functional React 19 components consuming ephemeral in-memory context (`useApp()` from `frontend/src/context/appContext.js`).

- `frontend/src/components/MedicalDisclaimer.jsx`: Persistent `FR-01` clinical disclaimer banner (`print:hidden`) with clickable `tel:123` ambulance action.
- `frontend/src/components/TopNavbar.jsx`: Global RTL navigation bar, Zero-PHI RAM badge, auth status pill, and Light/Dark toggle.
- `frontend/src/components/ChatInterface.jsx`: Gemini-style workspace with collapsible right-side in-memory session sidebar, quick-start chips, patient/AI stream, and bottom input + Voice Orb bar.
- `frontend/src/components/TriageCard.jsx`: Semantic urgency card (`1`–`4`) with `recommended_specialty`, `rationale_ar`, clickable `clarifying_questions`, `<bdi>` clinical `citations`, `detected_red_flags` / `negated_red_flags`, TTS audio button, Doctor Pass trigger, and card-level disclaimer.
- `frontend/src/components/DoctorPassModal.jsx`: Accessible (`role="dialog"`, `aria-modal="true"`) printable pre-visit clinical pass (`#printable-doctor-pass`).

---

## 3. Frameworks & Libraries

- **UI Framework:** React `^19.3.1` (`react`, `react-dom`)
- **Routing:** `react-router` `^8.5.1` (`BrowserRouter`, `Routes`, `Route`, `NavLink`, `Link`, `useNavigate`)
- **Styling:** Tailwind CSS `^4.3.5` via `@tailwindcss/vite`
- **Build & Dev Server:** Vite `^8.3.6` with `@vitejs/plugin-react` `^6.1.2`
- **Linting:** ESLint `^10.14.0` (`eslint.config.js` with `eslint-plugin-react-hooks` & `eslint-plugin-react-refresh`)

---

## 4. Asset Management

- Static public assets reside in `frontend/public/` (`favicon.svg`, `icons.svg`) and are referenced via root-relative paths (`/favicon.svg`).
- Fonts (`Cairo`, `Inter`) are loaded from Google Fonts CDN in `frontend/index.html` with `preconnect`.
- No patient audio or images are persisted; voice recordings (`MediaRecorder`) and TTS WAV audio (`data:audio/wav;base64,...`) are handled strictly in memory.

---

## 5. Icon System

- Clinical UI uses clean inline SVGs (e.g., Voice Orb microphone icon in `frontend/src/components/ChatInterface.jsx`) paired with high-contrast semantic Unicode medical/status glyphs (`🩺`, `🚨`, `🎙️`, `🔒`, `📄`, `🔊`) for zero-latency rendering without external icon-font bundles.

---

## 6. Styling Approach

- **Utility-First CSS:** Tailwind CSS v4 utility classes directly in JSX (`dark:` class variants powered by `@custom-variant dark (&:where(.dark, .dark *));`).
- **RTL-Native Logical Properties:** Root `<html lang="ar" dir="rtl">`, logical spacing (`ps-*`, `pe-*`, `ms-*`, `me-*`, `text-start`, `text-end`, `rounded-ts-xs`, `border-e`), and `<bdi>` around English medical titles and session IDs.
- **Print Isolation:** `@media print` in `frontend/src/index.css` hides `body *` and reveals only `#printable-doctor-pass` with `print-color-adjust: exact`.

---

## 7. Project Structure

```text
frontend/
├── index.html                  # RTL HTML root + Google Fonts (Cairo & Inter)
├── vite.config.js              # Vite + @tailwindcss/vite + /api proxy to :8000
├── DESIGN_SYSTEM.md            # Design system & Figma MCP rules
└── src/
    ├── main.jsx                # React 19 entry point
    ├── index.css               # Tailwind v4, CSS tokens, Voice Orb keyframes, @media print
    ├── App.jsx                 # 7-screen BrowserRouter shell + persistent disclaimer & modal
    ├── context/
    │   ├── appContext.js       # AppContext + useApp() hook
    │   └── AppProvider.jsx     # Strictly in-memory Zero-PHI state (sessions, vault, passes, theme)
    ├── services/
    │   └── api.js              # FastAPI REST & SSE client (triage, voice, escalations, audit-logs)
    ├── data/
    │   └── mockResponses.js    # Sample triage fixtures for preview/history demos
    ├── components/
    │   ├── MedicalDisclaimer.jsx
    │   ├── TopNavbar.jsx
    │   ├── ChatInterface.jsx
    │   ├── TriageCard.jsx
    │   └── DoctorPassModal.jsx
    └── pages/
        ├── LandingPage.jsx     # /
        ├── AuthPage.jsx        # /auth
        ├── ProfileVaultPage.jsx# /profile
        ├── HistoryArchivePage.jsx # /history
        └── Dashboard.jsx       # /dashboard
```
