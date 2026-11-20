"""Forbidden-claim patterns in EN/FR/AR: diagnosis statements (incl. probable diagnoses), personal dosing,
stopping or changing treatment, and triage verdicts (urgency or severity judgements about the user).

Patterns run on a matching copy of one answer sentence: number words become digits ("two tablets" ->
"2 tablets", app/guardrails/numbers.py), Arabic diacritics and invisible characters are removed. Patterns are
NOT anchored to the sentence start ("Based on what you describe, you probably have pneumonia").

Guards:
- diagnosis / dosing / stop-treatment: ignored when a negation or a referral cue, or a conditional, comes
  shortly before the match ("do not stop taking your medicine without asking your doctor").
- triage: ignored when the sentence is conditional anywhere ("go to the emergency room now IF your lips turn
  blue" is the general "when to seek care" guidance every answer must carry). A negation does not guard a
  triage verdict ("do not go to the hospital" is a verdict too).
Matching sentences are removed from the answer (they are never rewritten).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.guardrails.numbers import normalise_numbers

# Negation and referral cues are whole words: "not" inside "Another", "ne" inside "Une" or "لا" inside "خلال"
# must not guard a forbidden claim. "n't" is the only cue glued to the preceding word ("don't").
_EN_NEG = r"(?:(?<!\w)(?:not|never|no one should|without|before (?:talking|speaking|asking))|n't)(?!\w)"
_FR_NEG = r"(?:(?<!\w)(?:ne|pas|jamais|sans|avant d'en parler)(?!\w)|(?<!\w)n['’])"
_AR_NEG = r"(?<!\w)(?:لا|دون|بدون|قبل استشارة)(?!\w)"

_EN_CONDITION = (
    r"(?:\w+itis|\w+osis|\w+a?emia|infection|attack|disease|disorder|syndrome|stroke|cancer|tumou?r|fracture|"
    r"sprain|concussion|allergy|allergic reaction|migraine|flu|influenza|cold|virus|ulcer|clot|embolism|"
    r"thrombosis|hernia|diabetes|asthma|pneumonia|covid(?:-19)?|angina|anaphylaxis|seizure|epilepsy|"
    r"depression|anxiety|deficiency|failure|poisoning|overdose)"
)
_FR_CONDITION = (
    r"(?:infection|crise|attaque|maladie|trouble|syndrome|avc|accident vasculaire|cancer|tumeur|fracture|"
    r"entorse|commotion|allergie|réaction allergique|migraine|grippe|rhume|virus|ulcère|caillot|embolie|"
    r"thrombose|hernie|diabète|asthme|pneumonie|angine|infarctus|covid|épilepsie|dépression|intoxication|"
    r"empoisonnement|appendicite|bronchite|sinusite|otite|gastrite|gastro-entérite|gastro|méningite|cystite|"
    r"pharyngite|laryngite|conjonctivite|hépatite|tendinite|arthrite|pancréatite|pyélonéphrite|tuberculose)"
)
_AR_CONDITION = (
    r"(?:(?:ب|ل)?(?:ال)?(?:نوبة|جلطة|سكتة|التهاب|عدوى|مرض|متلازمة|سرطان|ورم|كسر|التواء|ارتجاج|حساسية|"
    r"صداع نصفي|انفلونزا|إنفلونزا|زكام|فيروس|قرحة|ربو|سكري|ذبحة|تسمم|احتشاء|أزمة|ازمة))"
)
_LIKELY_EN = (
    r"(?:probably|likely|most likely|almost certainly|very likely|definitely|certainly|surely|clearly)"
)
_LIKELY_FR = r"(?:probablement|sûrement|surement|certainement|sans doute|vraisemblablement|très probablement)"
_LIKELY_AR = r"(?:على الأرجح|على الارجح|غالبا|ربما|من المحتمل|أغلب الظن|اغلب الظن|من الأرجح|من الارجح)"
_NOT_A_CONDITION = (
    r"(?!(?:\w+ )?(?:signs?|symptoms?|warning|risk|good|bad|idea|way|reason|option|time|chance|part|"
    r"side effects?)\b)"
)
_YOU_HAVE_EXCL = (
    r"(?!to\b|the right\b|questions?\b|any\b|a right\b|more\b|less\b|several\b|options?\b|"
    r"heard\b|noticed\b|seen\b|read\b|wondered\b|been\b|had\b|taken\b|done\b|tried\b|used\b|given\b|"
    r"\w+ed\b|at\b|in\b|on\b|with\b|access\b|time\b|(?:a|the) (?:choice|question|doctor|appointment|right|"
    r"option|possibility)\b|an? (?:higher|lower|greater|increased|reduced) (?:risk|chance)\b)"
)
# "you have X" with no hedge counts only at the sentence start or after a lead-in about the user's case.
_EN_LEAD = (
    r"(?:^|(?:based on|from|given|according to|judging (?:by|from)|considering|in view of) "
    r"(?:what you(?:'ve| have)? (?:describe|described|said|mention|mentioned|told me|report|reported)|"
    r"your (?:symptoms|description|answers|history|case|signs)|the symptoms you describe)\W+|"
    r"\b(?:in your case|therefore|thus|i think|i believe|i suspect|it is likely that|it seems|"
    r"it appears|most likely)\W+)"
)
# French counterpart of _EN_LEAD: "D'après ce que vous décrivez, vous avez une pneumonie" (red team P5).
_FR_LEAD = (
    r"(?:^|(?:d'après|selon|vu|au vu de|compte tenu de) (?:ce que vous (?:décrivez|dites|mentionnez|"
    r"avez décrit|avez dit)|vos symptômes|votre description|vos réponses|votre cas)\W+|"
    r"\b(?:dans votre cas|donc|je pense que|je crois que|il semble que|j'ai l'impression que)\W+)"
)
_DOSE_UNITS = (
    r"(?:mg|mgs|milligrams?|ml|millilit(?:er|re)s?|g|grams?|mcg|µg|cc|tablets?|pills?|capsules?|caplets?|"
    r"drops?|puffs?|sprays?|sachets?|teaspoons?|tablespoons?|tsp|tbsp|spoonfuls?|units?|iu|doses?)"
)
_FR_DOSE_UNITS = (
    r"(?:mg|ml|g|mcg|µg|ui|comprimés?|gélules?|gouttes?|sachets?|cuillères?|bouffées?|pulvérisations?|"
    r"unités?|doses?|prises?)"
)
_FR_DRUG = (
    r"(?:aspirine|ibuprofène|paracétamol|antibiotiques?|anticoagulants?|insuline|corticoïdes?|cortisone|"
    r"anti-inflammatoires?|antidépresseurs?|antihypertenseurs?|anxiolytiques?|somnifères?|"
    r"\w+(?:cilline|mycine|azole|prazole|pril|sartan|statine|olol|oxacine|lukast|codéine|morphine|formine))"
)

_DIAGNOSIS = (
    rf"\byou {_LIKELY_EN} (?:have|'ve got|are suffering from|are having|suffer from|have got)\b "
    rf"{_YOU_HAVE_EXCL}",
    rf"\byou (?:seem|appear) to (?:have|be suffering from|be having)\b {_YOU_HAVE_EXCL}",
    rf"{_EN_LEAD}you (?:may |might |could )?(?:have|'ve got|are suffering from|are having) {_YOU_HAVE_EXCL}",
    rf"\b(?:it|this|that|these|those|what you describe)(?: really)? (?:sounds?|looks?|seems?) "
    rf"(?:a lot |very much |more )?like (?:you have|you've got|you are|you're|a case of|"
    rf"(?:an? |the )?(?:[\w-]+ ){{0,3}}?{_EN_CONDITION}\b)",
    rf"\b(?:it|this|that|these|those)(?: symptoms?| signs?| pain| rash)?(?:'s| is| are) {_LIKELY_EN}"
    r"(?: just)? (?!not\b|safe\b|best\b|fine\b|normal\b|important\b|necessary\b|helpful\b|useful\b|to\b|"
    r"that\b|a good\b|good\b|better\b)\w",
    rf"\b(?:it|this|that|these symptoms|your symptoms)(?: could| might| may| would)(?: well)? "
    rf"(?:be|indicate|mean|suggest) (?:a |an |the )?{_NOT_A_CONDITION}(?:[\w-]+ ){{0,3}}?{_EN_CONDITION}\b",
    r"\byour (?:symptoms|signs) (?:indicate|suggest|mean|point to|are consistent with)\b",
    r"\bmy (?:diagnosis|assessment) is\b",
    rf"\bvous (?:avez|souffrez|faites|êtes) {_LIKELY_FR}\b",
    rf"\bvous (?:souffrez|êtes atteinte?) (?:{_LIKELY_FR} )?d",
    rf"{_FR_LEAD}vous (?:avez|faites|souffrez d'|souffrez de) (?:une? |la |le |l'|des |de la |du |d'une? )?"
    rf"(?:[\w'-]+ ){{0,2}}?{_FR_CONDITION}\b",
    r"\b(?:on dirait|cela ressemble à|ça ressemble à|il semble) que vous (?:avez|faites|souffrez)\b",
    rf"\b(?:cela|ça|ceci) (?:ressemble|fait penser) (?:à|a) (?:une? |la |le |l')?(?:[\w'-]+ ){{0,3}}?"
    rf"{_FR_CONDITION}\b",
    r"\bvos symptômes (?:indiquent|suggèrent|correspondent à)\b",
    rf"(?:\bc'est|\bce sont|\bil s'agit|\bça|\bcela|\bceci)(?: est)? {_LIKELY_FR} "
    r"(?!pas\b|normal|important|nécessaire|utile|mieux|préférable|bien\b|bon\b)",
    rf"\b(?:cela|ça|ceci|ce)(?: pourrait| peut| pourrait bien) (?:être|indiquer|signifier) "
    rf"(?:une? |la |le |l')?(?!(?:\w+ )?(?:signes?|symptômes?|bonne|mauvaise|idée|façon|raison)\b)"
    rf"(?:[\w'-]+ ){{0,3}}?{_FR_CONDITION}\b",
    r"(?:أنت|انت) (?:مصاب|مصابة|تعاني) (?:ب|من)",
    r"(?:يبدو|أعتقد|اعتقد) (?:أنك|انك) (?:مصاب|تعاني|لديك)",
    r"(?:أعراضك|اعراضك) (?:تدل|تشير)",
    rf"{_LIKELY_AR} (?:أنك|انك|أن لديك|ان لديك|لديك|تكون|أنت|انت|مصاب|مصابة|تعاني)",
    rf"(?:أنت|انت|لديك|إنك|انك) {_LIKELY_AR} (?:مصاب|مصابة|تعاني|لديك)",
    rf"(?:هذا|هذه|ذلك|تلك)(?: الأعراض| الاعراض)? {_LIKELY_AR} ",
    rf"(?:قد|ربما) (?:تكون|يكون)(?: هذه| هذا| ذلك| تلك)? {_AR_CONDITION}",
)
_DOSING = (
    r"\b(?:you should|you can|you could|you need to|you must|please) (?:take|give|use|increase|reduce|"
    r"double)\b.{0,40}\b\d",
    rf"(?:^|[,;:]\s*|\b(?:then|now|so|just|simply|please)\s+)(?:take|give(?: him| her| them| your child| "
    rf"your baby| the child| the baby)?|use) \d+(?:[.,]\d+)?\s*{_DOSE_UNITS}\b",
    r"\b(?:your|the right|a safe) dose (?:for you )?(?:is|would be|should be)\b",
    r"\bdouble (?:your|the) (?:dose|dosage)\b",
    rf"\b(?:vous devez|vous devriez|vous pouvez|vous pourriez|il faut|il vous faut|"
    rf"je vous (?:conseille|recommande) de|prenez|donnez(?:-lui|-leur)?|administrez|utilisez) "
    rf"(?:prendre |donner |utiliser |administrer )?(?:[\w'-]+ ){{0,2}}?\d+(?:[.,]\d+)?\s*{_FR_DOSE_UNITS}\b",
    r"\bvotre (?:dose|posologie) (?:est|devrait être|sera)\b",
    r"\bdoublez (?:la|votre) dose\b",
    r"(?<!\w)(?:خذ|خذي|تناول|تناولي|أعطه|اعطه|أعطها|اعطها) \d+",
    r"(?:يجب|عليك|ينبغي|يمكنك|يجب عليك|ينبغي عليك|أنصحك|انصحك)(?: أن| ان| ب)? ?"
    r"(?:تأخذ|تاخذ|تتناول|تعطي|تستعمل|تستخدم|تزيد|تضاعف|أخذ|اخذ|تناول)(?:\s+\S+){0,3}?\s+\d",
    r"(?:جرعتك|الجرعة المناسبة لك) (?:هي|هو)",
    r"(?<!\w)(?:ضاعف|ضاعفي) الجرعة",
)
_STOP_TREATMENT = (
    r"\b(?:stop|quit|discontinue|skip|halve) (?:taking )?(?:your|the|this|that) (?:medication|medicine|"
    r"treatment|pills?|tablets?|drug|dose|prescription)",
    r"\byou (?:can|should|could) (?:safely )?(?:stop|quit|discontinue|skip)\b",
    r"(?:^|[,;:]\s*|\b(?:you (?:can|could|should|must|need to|may|might want to)|please|just|then|so|now|"
    r"simply|i (?:recommend|suggest|advise)(?: that)?(?: you)?)\s+)(?:stop|quit|discontinue|skip|halve|"
    r"cut down on) (?:taking|using) \S",
    r"\b(?:arrêtez|arretez|cessez|interrompez|sautez) (?:de prendre )?(?:votre|ce|le|la|vos|ces) "
    r"(?:traitement|médicament|medicament|comprimés?|dose)",
    r"\bvous pouvez (?:arrêter|arreter|cesser|interrompre)\b",
    r"\b(?:arrêtez|arretez|cessez|interrompez|arrêter|cesser|interrompre) (?:de prendre|d'utiliser|"
    r"la prise d|l'utilisation d)",
    rf"\b(?:arrêtez|arretez|cessez|interrompez) (?:l'|le |la |les |vos |votre ){_FR_DRUG}\b",
    r"(?<!\w)(?:توقف|توقفي|أوقف|اوقف) (?:عن )?(?:تناول|أخذ|اخذ)? ?(?:الدواء|دوائك|العلاج|علاجك)",
    r"(?<!\w)(?:توقف|توقفي|أوقف|اوقف|أوقفي|اوقفي) عن (?:تناول|أخذ|اخذ|استعمال|استخدام) \S",
)
_NOW = (
    r"(?:now|immediately|right away|right now|at once|asap|straight away|urgently|today|tonight|"
    r"without delay|immédiatement|maintenant|tout de suite|sans attendre|sans tarder|aujourd'hui|ce soir|"
    r"au plus vite|d'urgence|en urgence|فورا|حالا|الآن|الان|دابا|على الفور|في الحال|بسرعة|اليوم)"
)
_TRIAGE = (
    # reassurance / no-care verdicts
    r"\byou (?:do not|don't|dont|won't|will not|shouldn't|should not|probably don't|probably do not) "
    r"(?:need|have) to (?:see|visit|go to|call|consult|contact|worry|seek|get)\b",
    r"\byou (?:do not|don't|dont) need (?:a doctor|medical (?:care|attention|help)|to be seen|treatment)\b",
    r"\b(?:there is |there's )?no need (?:for you )?to (?:see|visit|go to|call|consult|contact|worry|seek)\b",
    r"\bno (?:need|reason) to (?:worry|panic|be concerned)\b",
    r"\bnothing to worry about\b",
    r"\b(?:it|this|that)(?:'s| is)(?: probably| likely| definitely| certainly)? (?:not (?:serious|urgent|"
    r"dangerous|an emergency|worrying|a concern|something to worry about)|nothing (?:serious|urgent|"
    r"dangerous|to worry about)|harmless|benign)\b",
    r"\byou(?: are|'re) (?:fine|ok|okay|safe|not in danger|out of danger)(?=\s*(?:[.,;!]|$|for now))",
    r"\byou (?:can|could) (?:safely )?wait\b",
    r"\bit can wait\b",
    # severity verdicts about the user's own state
    r"\byour (?:condition|situation|case|state|symptoms?|injury|problem)(?: is| are|'s| seems?| looks?|"
    r" sounds?)(?: to be)?(?: very| quite| really| probably| likely)? (?:serious|severe|urgent|critical|"
    r"life[- ]threatening|an emergency|not serious|not urgent|not an emergency|benign|harmless|mild|minor|"
    r"worrying|concerning|dangerous|not dangerous)\b",
    # urgency directives (a verdict when immediate; conditional sentences are guarded)
    rf"\b(?:go|get|head|rush|come)(?: straight| directly)? to (?:the |an |your nearest |the nearest |a )?"
    rf"(?:er|e\.r\.|emergency room|emergency department|emergency|emergencies|a&e|a & e|hospital|"
    rf"urgent care|casualty)\b(?=.*\b{_NOW})",
    rf"\byou (?:need|have|must|should|ought) (?:to )?(?:go|get|be seen|see a (?:doctor|gp|physician)|"
    rf"seek (?:medical|emergency|urgent) (?:care|help|attention)|call (?:an ambulance|the emergency))\b"
    rf"(?=.*\b{_NOW})",
    rf"(?:^|[,;:]\s*)(?:seek (?:emergency|urgent|immediate) (?:medical )?(?:care|help|attention|treatment)|"
    rf"call (?:an ambulance|the emergency services))\b(?=.*\b{_NOW})",
    # French
    r"\bvous n'avez pas besoin (?:de (?:consulter|voir|aller|appeler)|d'(?:aller|appeler|un médecin|"
    r"une consultation))",
    r"\b(?:pas besoin|inutile) de (?:consulter|voir un médecin|aller (?:aux urgences|à l'hôpital|chez le "
    r"médecin)|vous inquiéter|s'inquiéter|appeler)",
    r"\bce n'est (?:probablement |sûrement |certainement )?(?:pas|rien de) (?:grave|urgent|une urgence|"
    r"inquiétant|dangereux|sérieux)",
    r"\brien (?:de grave|d'inquiétant|de sérieux|d'urgent)\b",
    r"\bvous pouvez attendre\b",
    r"\bpas d'inquiétude\b",
    r"\bvotre (?:état|situation|cas|problème)(?: de santé)? (?:est|semble|paraît|n'est pas)(?: très| assez|"
    r" probablement)? (?:urgent|grave|critique|sérieux|bénin|sans gravité|inquiétant|préoccupant|"
    r"une urgence|pas grave|pas urgent)",
    rf"\b(?:allez|rendez-vous|rendez vous|présentez-vous|filez|foncez)(?: directement| immédiatement| tout de"
    rf" suite| vite)? (?:aux urgences|à l'hôpital|au service des urgences|aux services d'urgence)"
    rf"(?=.*{_NOW})",
    rf"\bvous (?:devez|devriez) (?:aller|vous rendre|consulter|voir un médecin|appeler)\b(?=.*{_NOW})",
    # Arabic
    r"(?:لا داعي|لا حاجة|ليس هناك داع|لست بحاجة|لا تحتاج|لا يلزمك|ما تحتاجش|ماشي ضروري)(?: إلى| الى)? ?"
    r"(?:ل|لل)?(?:زيارة|رؤية|مراجعة|استشارة|الذهاب|الطبيب|طبيب|المستشفى|القلق|قلق)",
    r"(?:لا|ليس هناك ما) (?:يدعو|داعي) (?:لل|إلى ال|الى ال)?قلق",
    r"(?:حالتك|وضعك|الأعراض التي لديك)(?: الصحية)? (?:ليست |ليس |غير )?(?:خطيرة|خطير|طارئة|طارئ|مستعجلة|"
    r"حرجة|بسيطة|خفيفة)",
    r"(?:هذه|هذا) (?:ليست |ليس )?(?:خطيرا|خطير|طارئا|طارئ|حالة خطيرة|أمر خطير)",
    rf"(?:اذهب|اذهبي|توجه|توجهي|سارع|روح|سير|امش)(?: فورا| حالا| الآن| الان)? (?:إلى |الى |ل|لل)?"
    rf"(?:ال)?(?:طوارئ|مستعجلات|مستشفى|سبيطار)(?=.*{_NOW})",
    rf"(?:يجب|عليك|لازم|خاصك)(?: أن| ان)? (?:تذهب|تتوجه|تزور|تراجع|تتصل|تمشي)(?=.*{_NOW})",
)

Guard = Literal["before", "conditional"]
_CATEGORIES: tuple[tuple[str, Guard, tuple[re.Pattern[str], ...]], ...] = (
    ("diagnosis", "before", tuple(re.compile(p, re.IGNORECASE) for p in _DIAGNOSIS)),
    ("personal_dosing", "before", tuple(re.compile(p, re.IGNORECASE) for p in _DOSING)),
    ("stop_treatment", "before", tuple(re.compile(p, re.IGNORECASE) for p in _STOP_TREATMENT)),
    ("triage", "conditional", tuple(re.compile(p, re.IGNORECASE) for p in _TRIAGE)),
)
_NEGATION_BEFORE = re.compile(rf"(?:{_EN_NEG}|{_FR_NEG}|{_AR_NEG})\W*(?:\w+\W+){{0,3}}$", re.IGNORECASE)
_CONDITIONAL_BEFORE = re.compile(
    r"\b(?:if|when|whether|unless|si|lorsque|quand|إذا|اذا|عندما)\W+(?:\w+\W+){0,2}$", re.IGNORECASE
)
_CONDITIONAL_ANYWHERE = re.compile(
    r"(?<!\w)(?:if|when|whenever|unless|in case|in an emergency|should (?:you|they|he|she|your)|as soon as|"
    r"si|s'il|s'ils|lorsque|lorsqu|quand|à moins|en cas d|au cas où|dès que|إذا|اذا|إن|لو|عندما|عند|"
    r"في حالة|ما لم)(?!\w)",
    re.IGNORECASE,
)
_AR_MARKS = re.compile(r"[ً-ٰٟـ]")  # harakat, superscript alef, tatweel
_CITATIONS = re.compile(r"\[\d+(?:\s*[,;]\s*\d+)*\]")  # "[1]" is not a dose number


@dataclass(frozen=True)
class ClaimViolation:
    category: str  # "diagnosis" | "personal_dosing" | "stop_treatment" | "triage"


def _guarded(sentence: str, start: int) -> bool:
    before = sentence[:start]
    return bool(_NEGATION_BEFORE.search(before) or _CONDITIONAL_BEFORE.search(before))


def _matching_copy(sentence: str) -> str:
    text = unicodedata.normalize("NFC", sentence.strip().lstrip("-*• ").replace("**", ""))
    text = _AR_MARKS.sub("", normalise_numbers(_CITATIONS.sub(" ", text))).replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


def _violates(text: str, guard: Guard, pattern: re.Pattern[str], conditional: bool) -> bool:
    m = pattern.search(text)
    if m is None:
        return False
    if guard == "conditional":
        return not conditional
    return not _guarded(text, m.start())


def find_forbidden_claims(sentence: str) -> tuple[ClaimViolation, ...]:
    """Return the forbidden-claim categories present in one sentence (empty when safe)."""
    text = _matching_copy(sentence)
    conditional = bool(_CONDITIONAL_ANYWHERE.search(text))
    return tuple(
        ClaimViolation(category)
        for category, guard, patterns in _CATEGORIES
        if any(_violates(text, guard, p, conditional) for p in patterns)
    )
