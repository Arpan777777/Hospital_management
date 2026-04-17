import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count
from .models import Appointment, Availability

# Download required NLTK data (runs once)
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)

try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt_tab', quiet=True)

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords', quiet=True)

try:
    nltk.data.find('corpora/wordnet')
except LookupError:
    nltk.download('wordnet', quiet=True)

# Initialise stemmer and stopwords
stemmer = PorterStemmer()
STOP_WORDS = set(stopwords.words('english'))

# Medical keyword mapping - expanded for better NLP matching
SPECIALIZATION_KEYWORDS = {
    "cardiology": [
        "chest", "heart", "cardiac", "cardio", "breathless", "palpitation",
        "blood", "pressure", "hypertension", "angina", "arrhythmia", "pulse",
        "coronary", "stroke", "infarction", "shortness", "breath"
    ],
    "dermatology": [
        "skin", "rash", "itch", "acne", "eczema", "psoriasis", "lesion",
        "hives", "allergy", "blister", "wart", "mole", "dermatitis",
        "inflammation", "spot", "patch", "sore", "wound"
    ],
    "neurology": [
        "headache", "migraine", "seizure", "stroke", "numb", "tremor",
        "dizzy", "dizziness", "vertigo", "memory", "confusion", "nerve",
        "paralysis", "tingling", "weakness", "epilepsy", "concussion"
    ],
    "orthopedics": [
        "bone", "knee", "back", "joint", "fracture", "sprain", "muscle",
        "spine", "shoulder", "hip", "ankle", "wrist", "tendon", "ligament",
        "arthritis", "osteoporosis", "pain", "stiffness", "swelling"
    ],
    "pediatrics": [
        "child", "baby", "infant", "fever", "vaccination", "growth",
        "developmental", "toddler", "newborn", "immunisation", "colic",
        "teething", "childhood", "adolescent", "pediatric"
    ],
    "gastroenterology": [
        "stomach", "abdomen", "bowel", "nausea", "vomiting", "diarrhea",
        "constipation", "bloating", "acid", "reflux", "ulcer", "colon",
        "digestive", "gastric", "intestinal", "liver", "gallbladder"
    ],
    "general": [
        "checkup", "fever", "cough", "cold", "flu", "pain", "fatigue",
        "tired", "weak", "infection", "viral", "bacterial", "general",
        "routine", "wellness", "examination", "screening"
    ],
}

# Pre-stem all keywords for faster matching
STEMMED_KEYWORDS = {}
for spec, keywords in SPECIALIZATION_KEYWORDS.items():
    STEMMED_KEYWORDS[spec] = [stemmer.stem(k.lower()) for k in keywords]


def extract_keywords_nltk(text: str) -> list:
    """
    Uses NLTK to tokenize and extract meaningful keywords from patient reason text.
    Removes stopwords and applies stemming for better matching.
    """
    if not text:
        return []

    # Tokenize the text
    tokens = word_tokenize(text.lower())

    # Remove stopwords and non-alphabetic tokens
    filtered = [
        stemmer.stem(token)
        for token in tokens
        if token.isalpha() and token not in STOP_WORDS and len(token) > 2
    ]

    return filtered


def _keyword_match_nltk(reason_text: str, specialization: str) -> float:
    """
    NLP-enhanced keyword matching using NLTK tokenization and stemming.
    Returns a score between 0.0 and 1.0.
    """
    if not reason_text or not specialization:
        return 0.0

    s = specialization.lower()

    # Direct specialization mention (highest score)
    if s in reason_text.lower():
        return 1.0

    # Extract NLP keywords from patient reason
    patient_keywords = extract_keywords_nltk(reason_text)

    if not patient_keywords:
        return 0.0

    # Get stemmed keywords for this specialization
    spec_keywords = STEMMED_KEYWORDS.get(s, [])

    if not spec_keywords:
        return 0.0

    # Count how many patient keywords match specialization keywords
    hits = sum(1 for pk in patient_keywords if pk in spec_keywords)

    # Score based on proportion of matches
    score = hits / max(3, len(spec_keywords))

    return min(1.0, score)


def get_extracted_keywords(reason_text: str) -> list:
    """
    Returns the extracted keywords from the patient reason text.
    Used for displaying NLP extraction results to the user.
    """
    if not reason_text:
        return []

    tokens = word_tokenize(reason_text.lower())
    keywords = [
        token for token in tokens
        if token.isalpha() and token not in STOP_WORDS and len(token) > 2
    ]
    return list(set(keywords))


def recommend_slots(reason_text: str, preferred_specialization: str | None = None, top_n: int = 3):
    """
    Returns list of tuples: (slot, score, explanation_dict)
    Uses NLTK NLP for keyword extraction and matching.
    """
    now = timezone.now()
    lookback = now - timedelta(days=30)

    # Only free slots in the future
    slots_qs = Availability.objects.select_related("doctor").filter(
        is_booked=False,
        start_time__gte=now
    ).order_by("start_time")

    if preferred_specialization:
        slots_qs = slots_qs.filter(doctor__specialization__iexact=preferred_specialization)

    slots = list(slots_qs[:200])

    # Doctor workload = appointments per doctor (last 30 days)
    doctor_load = dict(
        Appointment.objects.filter(appointment_date__gte=lookback)
        .values("doctor_id")
        .annotate(c=Count("id"))
        .values_list("doctor_id", "c")
    )

    # Busy hours = appointments per hour (last 30 days)
    recent_appts = Appointment.objects.filter(
        appointment_date__gte=lookback
    ).values_list("appointment_date", flat=True)

    hour_busy = {}
    day_busy = {}
    for dt in recent_appts:
        hr = dt.hour
        wd = dt.weekday()
        hour_busy[hr] = hour_busy.get(hr, 0) + 1
        day_busy[wd] = day_busy.get(wd, 0) + 1

    def busy_score(hour: int, weekday: int) -> float:
        hb = hour_busy.get(hour, 0)
        db = day_busy.get(weekday, 0)
        return 1.0 / (1.0 + hb + db)

    # Extract NLP keywords once for efficiency
    extracted_keywords = get_extracted_keywords(reason_text)

    results = []
    for slot in slots:
        doc = slot.doctor
        load = doctor_load.get(doc.id, 0)

        # Components using NLTK NLP matching
        load_component = 1.0 / (1.0 + load)
        time_component = busy_score(slot.start_time.hour, slot.start_time.weekday())
        match_component = _keyword_match_nltk(reason_text, doc.specialization)

        # Soonest bonus
        minutes_ahead = max(0, int((slot.start_time - now).total_seconds() // 60))
        soon_component = 1.0 / (1.0 + minutes_ahead / 240.0)

        # Final weighted score
        score = (
            0.40 * load_component +
            0.30 * time_component +
            0.20 * match_component +
            0.10 * soon_component
        )

        explanation = {
            "doctor_load_last_30_days": load,
            "match_score": round(match_component, 2),
            "hour": slot.start_time.hour,
            "weekday": slot.start_time.weekday(),
            "extracted_keywords": extracted_keywords,
        }

        results.append((slot, score, explanation))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n]
