import { useState, useEffect, useCallback, useMemo } from "react";
import { AppContext } from "./appContext";
import { mockResponses } from "../data/mockResponses";

const INITIAL_VAULT = {
  age: "",
  gender: "",
  governorate: "",
  chronicConditions: [],
  allergies: "",
};

const INITIAL_GUEST_AUTH = {
  mode: "guest",
  name: "زائر (بدون بيانات)",
  email: "",
};

function createEmptySession(index = 1) {
  return {
    id: "sess-" + crypto.randomUUID().slice(0, 10),
    title: `محادثة فرز #${index}`,
    createdAt: new Date().toISOString(),
    messages: [],
  };
}

export default function AppProvider({ children }) {
  // Theme (Light default, class-based dark mode in RAM only)
  const [theme, setTheme] = useState("light");

  // Ephemeral guest / personal session state (Zero-PHI: never written to disk)
  const [authUser, setAuthUser] = useState(INITIAL_GUEST_AUTH);
  const [patientVault, setPatientVault] = useState(INITIAL_VAULT);

  // In-memory Gemini-style conversation sessions
  const [sessions, setSessions] = useState(() => [createEmptySession(1)]);
  const [activeSessionId, setActiveSessionId] = useState(
    () => null
  );

  const currentSessionId = activeSessionId || sessions[0]?.id;

  // Saved Pre-Visit Doctor Passes generated during this RAM session
  const [savedPasses, setSavedPasses] = useState([]);

  // Global Doctor Pass Modal state
  const [modalState, setModalState] = useState({
    isOpen: false,
    triageData: null,
    patientComplaint: "",
    patientContext: null,
  });

  // Sync Tailwind dark class on <html>
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  }, []);

  const loginAsPersonal = useCallback(({ name, email }) => {
    setAuthUser({
      mode: "personal",
      name: (name || "").trim() || "مستخدم مسجل (جلسة مؤقتة)",
      email: (email || "").trim(),
    });
  }, []);

  const continueAsGuest = useCallback(() => {
    setAuthUser(INITIAL_GUEST_AUTH);
  }, []);

  const updatePatientVault = useCallback((patch) => {
    setPatientVault((prev) => ({ ...prev, ...patch }));
  }, []);

  const clearPatientVault = useCallback(() => {
    setPatientVault(INITIAL_VAULT);
  }, []);

  const createNewSession = useCallback(() => {
    let createdId = "";
    setSessions((prev) => {
      const next = createEmptySession(prev.length + 1);
      createdId = next.id;
      return [next, ...prev];
    });
    if (createdId) {
      setActiveSessionId(createdId);
    }
    return createdId;
  }, []);

  const selectSession = useCallback((sessionId) => {
    setActiveSessionId(sessionId);
  }, []);

  const appendMessageToSession = useCallback(
    (targetSessionId, messageObj, maybeTitle) => {
      setSessions((prev) =>
        prev.map((sess) => {
          if (sess.id !== targetSessionId) return sess;
          const updatedTitle =
            maybeTitle && sess.messages.length === 0
              ? maybeTitle.slice(0, 38) + (maybeTitle.length > 38 ? "..." : "")
              : sess.title;
          return {
            ...sess,
            title: updatedTitle,
            messages: [...sess.messages, messageObj],
          };
        })
      );
    },
    []
  );

  const recordSavedPass = useCallback(
    ({ triageData, patientComplaint }) => {
      if (!triageData) return;
      const newPass = {
        passId: "pass-" + crypto.randomUUID().slice(0, 8),
        sessionId: triageData.session_id || currentSessionId,
        createdAt: new Date().toISOString(),
        patientComplaint: patientComplaint || "استشارة طبية مسجلة",
        triageData,
        patientVaultSnapshot: { ...patientVault },
      };
      setSavedPasses((prev) => [newPass, ...prev]);
    },
    [currentSessionId, patientVault]
  );

  const loadSamplePasses = useCallback(() => {
    const sampleComplaints = [
      "ألم حاد ومفاجئ في الصدر مسمع في الكتف الأيسر مع تعرق وضيق تنفس",
      "حرقان شديد في فم المعدة مع ارتجاع مستمر وصعوبة في البلع",
      "إرهاق عام وخمول بسيط غير محدد منذ يومين",
      "ألم خفيف في مفصل الركبة اليمنى بعد المشي لمسافات طويلة",
    ];
    const samples = mockResponses.map((resp, idx) => ({
      passId: `sample-pass-${idx + 1}`,
      sessionId: resp.session_id,
      createdAt: new Date(Date.now() - idx * 600000).toISOString(),
      patientComplaint: sampleComplaints[idx] || "حالة استرشادية",
      triageData: resp,
      patientVaultSnapshot: { ...patientVault },
    }));
    setSavedPasses((prev) => {
      const existingIds = new Set(prev.map((p) => p.passId));
      const fresh = samples.filter((s) => !existingIds.has(s.passId));
      return [...prev, ...fresh];
    });
  }, [patientVault]);

  const openDoctorPass = useCallback(
    (triageData, patientComplaint, customVaultSnapshot) => {
      setModalState({
        isOpen: true,
        triageData,
        patientComplaint: patientComplaint || "",
        patientContext: customVaultSnapshot || patientVault,
      });
    },
    [patientVault]
  );

  const closeDoctorPass = useCallback(() => {
    setModalState((prev) => ({ ...prev, isOpen: false }));
  }, []);

  const wipeAllMemory = useCallback(() => {
    const fresh = createEmptySession(1);
    setAuthUser(INITIAL_GUEST_AUTH);
    setPatientVault(INITIAL_VAULT);
    setSessions([fresh]);
    setActiveSessionId(fresh.id);
    setSavedPasses([]);
    setModalState({
      isOpen: false,
      triageData: null,
      patientComplaint: "",
      patientContext: null,
    });
  }, []);

  const activeSession = useMemo(() => {
    return sessions.find((s) => s.id === currentSessionId) || sessions[0];
  }, [sessions, currentSessionId]);

  const value = useMemo(
    () => ({
      theme,
      toggleTheme,
      authUser,
      loginAsPersonal,
      continueAsGuest,
      patientVault,
      updatePatientVault,
      clearPatientVault,
      sessions,
      activeSession,
      activeSessionId: currentSessionId,
      createNewSession,
      selectSession,
      appendMessageToSession,
      savedPasses,
      recordSavedPass,
      loadSamplePasses,
      modalState,
      openDoctorPass,
      closeDoctorPass,
      wipeAllMemory,
    }),
    [
      theme,
      toggleTheme,
      authUser,
      loginAsPersonal,
      continueAsGuest,
      patientVault,
      updatePatientVault,
      clearPatientVault,
      sessions,
      activeSession,
      currentSessionId,
      createNewSession,
      selectSession,
      appendMessageToSession,
      savedPasses,
      recordSavedPass,
      loadSamplePasses,
      modalState,
      openDoctorPass,
      closeDoctorPass,
      wipeAllMemory,
    ]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
