/** Localised synthetic texts for the mock scenarios (EN / FR / AR). */

export const TEXT = {
  hba1c: {
    en: [
      "An HbA1c test measures your average blood sugar level over the past three months [1]. ",
      "It is used to check for **diabetes** and to see how well diabetes is managed over time [1, 2].\n\n",
      "- Your doctor can explain what your own result means.\n- Ask before the test whether you need to fast.",
    ],
    fr: [
      "Le test HbA1c mesure votre taux moyen de sucre dans le sang au cours des trois derniers mois [1]. ",
      "Il sert à dépister le **diabète** et à suivre son équilibre dans le temps [1, 2].\n\n",
      "- Votre médecin peut vous expliquer votre propre résultat.\n- Demandez avant l'examen s'il faut être à jeun.",
    ],
    ar: [
      "يقيس فحص HbA1c متوسط مستوى السكر في الدم خلال الأشهر الثلاثة الماضية [1]. ",
      "ويُستخدم للكشف عن **داء السكري** ومتابعة التحكم فيه مع مرور الوقت [1, 2].\n\n",
      "- يمكن لطبيبك أن يشرح لك ما تعنيه نتيجتك.\n- اسأل قبل الفحص إن كان عليك الصيام.",
    ],
  },
  sourceLanguage: {
    en: "The sources for this answer are in English.",
    fr: "Les sources de cette réponse sont en anglais.",
    ar: "مصادر هذه الإجابة باللغة الإنجليزية.",
  },
  emergency: {
    title: { en: "This may be an emergency", fr: "Il peut s'agir d'une urgence", ar: "قد تكون هذه حالة طارئة" },
    message: {
      en: "If you or someone near you has chest pain, trouble breathing or signs of a stroke, call the emergency number now. Do not wait for an answer here.",
      fr: "Si vous ou une personne près de vous avez une douleur dans la poitrine, du mal à respirer ou des signes d'AVC, appelez les urgences maintenant. N'attendez pas de réponse ici.",
      ar: "إذا كنت أنت أو شخص بقربك تعاني من ألم في الصدر أو صعوبة في التنفس أو علامات سكتة دماغية، فاتصل برقم الطوارئ الآن. لا تنتظر إجابة هنا.",
    },
  },
  selfHarm: {
    title: { en: "You are not alone", fr: "Vous n'êtes pas seul", ar: "لست وحدك" },
    message: {
      en: "If you are thinking about ending your life or hurting yourself, please talk to someone now. The crisis line answers day and night.",
      fr: "Si vous pensez à mettre fin à vos jours ou à vous faire du mal, parlez-en à quelqu'un maintenant. La ligne d'écoute répond jour et nuit.",
      ar: "إذا كنت تفكر في إنهاء حياتك أو إيذاء نفسك، فتحدث إلى شخص ما الآن. خط الأزمات متاح ليلًا ونهارًا.",
    },
  },
  refusal: {
    en: "I can't help with that request. I can explain general health information from trusted sources, or help you find your way around the hospital.",
    fr: "Je ne peux pas répondre à cette demande. Je peux expliquer des informations générales de santé issues de sources fiables, ou vous aider à vous orienter à l'hôpital.",
    ar: "لا يمكنني المساعدة في هذا الطلب. يمكنني شرح معلومات صحية عامة من مصادر موثوقة، أو مساعدتك في التنقل داخل المستشفى.",
  },
  abstain: {
    en: "I don't have reliable information on that in my sources. A doctor or pharmacist can help, or you can ask the hospital front desk.",
    fr: "Je n'ai pas d'information fiable à ce sujet dans mes sources. Un médecin ou un pharmacien peut vous aider, ou l'accueil de l'hôpital.",
    ar: "لا تتوفر لدي معلومات موثوقة حول هذا في مصادري. يمكن للطبيب أو الصيدلي مساعدتك، أو يمكنك سؤال استقبال المستشفى.",
  },
  handoff: {
    en: "You can talk to a person at the front desk.",
    fr: "Vous pouvez parler à une personne de l'accueil.",
    ar: "يمكنك التحدث إلى موظف الاستقبال.",
  },
  form: {
    title: { en: "Request an appointment", fr: "Demander un rendez-vous", ar: "طلب موعد" },
    description: {
      en: "Hospital staff will call you back to confirm a time.",
      fr: "Le personnel de l'hôpital vous rappellera pour confirmer un horaire.",
      ar: "سيتصل بك موظفو المستشفى لتأكيد الموعد.",
    },
    answer: {
      en: "I've opened an appointment request form below. Hospital staff will contact you to confirm.",
      fr: "J'ai ouvert un formulaire de demande de rendez-vous ci-dessous. Le personnel vous contactera pour confirmer.",
      ar: "فتحت لك نموذج طلب موعد أدناه. سيتواصل معك الموظفون للتأكيد.",
    },
    labels: {
      full_name: { en: "Full name", fr: "Nom complet", ar: "الاسم الكامل" },
      phone: { en: "Phone number", fr: "Numéro de téléphone", ar: "رقم الهاتف" },
      email: { en: "Email", fr: "Adresse e-mail", ar: "البريد الإلكتروني" },
      department_id: { en: "Department", fr: "Service", ar: "القسم" },
      preferred_dates: { en: "Preferred dates", fr: "Dates souhaitées", ar: "التواريخ المفضلة" },
      reason: { en: "Reason (optional)", fr: "Motif (facultatif)", ar: "السبب (اختياري)" },
    },
    confirmation: {
      en: "Thank you. The front desk will call you within two working days.",
      fr: "Merci. L'accueil vous rappellera sous deux jours ouvrés.",
      ar: "شكرًا لك. سيتصل بك الاستقبال خلال يومي عمل.",
    },
  },
  frontDesk: {
    en: "Visiting hours are **every day from 12:00 to 20:00**.\n\n- Two visitors at a time per patient.\n- Children under 12 visit with an adult.",
    fr: "Les visites ont lieu **tous les jours de 12 h à 20 h**.\n\n- Deux visiteurs à la fois par patient.\n- Les enfants de moins de 12 ans viennent avec un adulte.",
    ar: "مواعيد الزيارة **كل يوم من 12:00 إلى 20:00**.\n\n- زائران في الوقت نفسه لكل مريض.\n- يرافق شخص بالغ الأطفال دون 12 عامًا.",
  },
  ibuprofen: {
    en: "Ibuprofen is a nonsteroidal anti-inflammatory medicine used to relieve pain and reduce fever [1].\n\n- Take it with food or milk if it upsets your stomach [1].\n- Do not take more than the label says [1].\n\nA pharmacist can answer questions about your own situation.",
    fr: "L'ibuprofène est un anti-inflammatoire non stéroïdien utilisé contre la douleur et la fièvre [1].\n\n- Prenez-le avec de la nourriture ou du lait s'il irrite l'estomac [1].\n- Ne dépassez pas ce qu'indique la notice [1].\n\nUn pharmacien peut répondre aux questions sur votre situation.",
    ar: "الإيبوبروفين دواء مضاد للالتهاب غير ستيرويدي يُستخدم لتخفيف الألم وخفض الحرارة [1].\n\n- تناوله مع الطعام أو الحليب إذا سبب لك اضطرابًا في المعدة [1].\n- لا تتجاوز ما هو مذكور في النشرة [1].\n\nيمكن للصيدلي الإجابة عن أسئلتك حول حالتك.",
  },
  replaced: {
    draft: { en: "This first draft will be replaced. ", fr: "Ce premier brouillon sera remplacé. ", ar: "ستُستبدل هذه المسودة الأولى. " },
    final: {
      en: "This corrected answer replaced the draft after checking [1].",
      fr: "Cette réponse corrigée a remplacé le brouillon après vérification [1].",
      ar: "استبدلت هذه الإجابة المصححة المسودة بعد التحقق [1].",
    },
  },
  failed: {
    en: "Ausculta could not finish this answer.",
    fr: "Ausculta n'a pas pu terminer cette réponse.",
    ar: "تعذّر على أوسكولتا إكمال هذه الإجابة.",
  },
  rateLimited: { en: "Too many messages.", fr: "Trop de messages.", ar: "رسائل كثيرة جدًا." },
  overloaded: { en: "Service busy.", fr: "Service occupé.", ar: "الخدمة مشغولة." },
  slow: { en: "This answer is streaming slowly. ", fr: "Cette réponse arrive lentement. ", ar: "تصل هذه الإجابة ببطء. " },
};
