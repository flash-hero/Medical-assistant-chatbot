/**
 * Synthetic, fictional fixtures for the mock API (docs/contracts/api.md). No real people, hospitals or
 * phone lines: every number below is a placeholder in a reserved or fictional range.
 */

const L = (en, fr, ar) => ({ en, fr, ar });

export const HOSPITAL = {
  id: "riverside_demo",
  name: L("Riverside Demo Hospital", "Hôpital de démonstration Riverside", "مستشفى ريفرسايد التجريبي"),
  address: L("12 Example Street, Lyon (fictional)", "12 rue de l'Exemple, Lyon (fictif)", "12 شارع المثال، ليون (وهمي)"),
  main_phone: { label: L("Switchboard", "Standard", "المقسم"), number: "+33 4 00 00 00 00", hours: L("24/7", "24 h/24", "على مدار الساعة") },
  emergency: { label: L("Emergency services", "Urgences", "خدمات الطوارئ"), number: "112", hours: L("", "", "") },
  crisis_lines: [{ label: L("Suicide crisis line", "Numéro national de prévention du suicide", "خط الوقاية من الانتحار"), number: "3114", hours: L("24/7", "24 h/24", "على مدار الساعة") }],
  handoff: { label: L("Front desk", "Accueil", "الاستقبال"), number: "+33 4 00 00 00 01", hours: L("8:00 to 20:00", "8 h à 20 h", "من 8:00 إلى 20:00") },
  visiting_hours: L("Every day, 12:00 to 20:00", "Tous les jours, de 12 h à 20 h", "كل يوم، من 12:00 إلى 20:00"),
  departments: [
    { id: "cardiology", name: L("Cardiology", "Cardiologie", "أمراض القلب"), location: L("Building B, floor 2", "Bâtiment B, 2e étage", "المبنى ب، الطابق 2"), hours: L("8:00 to 18:00", "8 h à 18 h", "من 8:00 إلى 18:00"), accepts_appointments: true },
    { id: "dermatology", name: L("Dermatology", "Dermatologie", "الأمراض الجلدية"), location: L("Building A, floor 1", "Bâtiment A, 1er étage", "المبنى أ، الطابق 1"), hours: L("9:00 to 17:00", "9 h à 17 h", "من 9:00 إلى 17:00"), accepts_appointments: true },
    { id: "general_medicine", name: L("General medicine", "Médecine générale", "الطب العام"), location: L("Building A, ground floor", "Bâtiment A, rez-de-chaussée", "المبنى أ، الطابق الأرضي"), hours: L("8:00 to 19:00", "8 h à 19 h", "من 8:00 إلى 19:00"), accepts_appointments: true },
  ],
};

const pick = (value, locale) => (value && typeof value === "object" && "en" in value ? value[locale] || value.en : value);

function contact(c, locale) {
  return { label: pick(c.label, locale), number: c.number, hours: pick(c.hours, locale) };
}

export function publicHospital(locale) {
  return {
    id: HOSPITAL.id,
    name: pick(HOSPITAL.name, locale),
    is_demo: true,
    address: pick(HOSPITAL.address, locale),
    main_phone: contact(HOSPITAL.main_phone, locale),
    emergency: contact(HOSPITAL.emergency, locale),
    crisis_lines: HOSPITAL.crisis_lines.map((c) => contact(c, locale)),
    handoff: contact(HOSPITAL.handoff, locale),
    visiting_hours: pick(HOSPITAL.visiting_hours, locale),
    departments: HOSPITAL.departments.map((d) => ({
      id: d.id,
      name: pick(d.name, locale),
      location: pick(d.location, locale),
      hours: pick(d.hours, locale),
      accepts_appointments: d.accepts_appointments,
    })),
  };
}

export const CITATIONS = {
  hba1c: {
    n: 1,
    title: "Hemoglobin A1C (HbA1c) Test",
    publisher: "MedlinePlus, U.S. National Library of Medicine",
    url: "https://medlineplus.gov/lab-tests/hemoglobin-a1c-hba1c-test/",
    heading: "What is it used for?",
    reviewed_on: "2025-09-12",
    language: "en",
    snippet: "A hemoglobin A1c (HbA1c) test is a blood test that shows what your average blood sugar (glucose) level was over the past three months.",
  },
  a1cNiddk: {
    n: 2,
    title: "The A1C Test & Diabetes",
    publisher: "National Institute of Diabetes and Digestive and Kidney Diseases",
    url: "https://www.niddk.nih.gov/health-information/diagnostic-tests/a1c-test",
    heading: "",
    reviewed_on: null,
    language: "en",
    snippet: "The A1C test is a common blood test used to diagnose type 1 and type 2 diabetes and to monitor how well you are managing your diabetes.",
  },
  ibuprofen: {
    n: 1,
    title: "Ibuprofen tablets: drug label",
    publisher: "U.S. Food and Drug Administration (openFDA)",
    url: "https://open.fda.gov/apis/drug/label/",
    heading: "Directions",
    reviewed_on: "2025-06-30",
    language: "en",
    snippet: "Take with food or milk if stomach upset occurs. Do not take more than directed.",
  },
  ibuprofenFr: {
    n: 2,
    title: "Ibuprofène 200 mg, comprimé (synthèse fictive)",
    publisher: "Base de données publique des médicaments (exemple)",
    url: "https://base-donnees-publique.medicaments.gouv.fr/",
    heading: "Conditions de délivrance",
    reviewed_on: "2025-10-01",
    language: "fr",
    snippet: "Médicament disponible sans ordonnance en pharmacie. Respecter la dose indiquée sur la notice.",
  },
};

export const RELEASE = {
  app_version: "mock-0.1.0",
  corpus_version: "mock-corpus",
  prompt_hash: "mock",
  models: { answer: "mock-model" },
};
