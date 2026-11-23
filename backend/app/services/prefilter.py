import hashlib
import re
from typing import Any
from app.models import RawJob

TECH_DOMAIN_PATTERNS = [
    r"\bengineer(?:s|ing)?\b",
    r"\bqa\b",
    r"\bquality\b",
    r"\btest(?:ing)?\b",
    r"\bsdet\b",
    r"\bautomation\b",
    r"\bsoftware\b",
    r"\btechnical\b",
    r"\btechnology\b",
    r"\bcto\b",
    r"\barchitect(?:ure)?\b",
    r"\bdeveloper\b",
    r"\bdevex\b",
    r"\bplatform\b",
    r"\binfrastructure\b",
    r"\bsre\b",
    r"\bdevops\b",
    r"\brelease\b",
    r"\bai\b",
    r"\bmachine learning\b",
    r"\bbackend\b",
    r"\bmobile\b",
    r"\bandroid\b",
    r"\bios\b",
    r"\bfull[\s-]?stack\b",
    r"\bfrontend\b",
]

TECH_DOMAIN_REGEX = re.compile("|".join(TECH_DOMAIN_PATTERNS), re.IGNORECASE)

NON_TECH_EXCLUSIONS = [
    "intern",
    "internship",
    "junior",
    "intermediate",
    "fresh graduate",
    "entry level",
    "sales",
    "account executive",
    "account manager",
    "chain accounts",
    "business development",
    "bdr",
    "sdr",
    "partnerships",
    "marketing",
    "gtm",
    "revops",
    "revenue operations",
    "growth operation",
    "copywriter",
    "social media",
    "customer support",
    "customer success",
    "technical support",
    "director, support",
    "call center",
    "finance",
    "financial",
    "accounting",
    "accountant",
    "tax ",
    "treasury",
    "audit",
    "payroll",
    "legal",
    "counsel",
    "paralegal",
    "compliance",
    "regulatory",
    "risk ",
    "aml",
    "kyc",
    "human resources",
    "hr ",
    "recruiter",
    "recruiting",
    "talent acquisition",
    "people operations",
    "public sector",
    "government",
    "policy",
    "communications",
    "public relations",
    "real estate",
    "facilities",
    "office manager",
    "executive assistant",
    "non-executive director",
]

APAC_OR_REMOTE_MARKERS = [
    "jakarta",
    "indonesia",
    "singapore",
    "apac",
    "asia",
    "sea",
    "southeast asia",
    "vietnam",
    "ho chi minh",
    "hanoi",
    "malaysia",
    "kuala lumpur",
    "thailand",
    "bangkok",
    "philippines",
    "manila",
    "australia",
    "sydney",
    "melbourne",
    "india",
    "bangalore",
    "bengaluru",
    "tokyo",
    "japan",
    "hong kong",
    "taiwan",
    "taipei",
    "seoul",
    "korea",
    "remote",
    "home based",
    "work from anywhere",
    "global",
    "anywhere",
    "worldwide",
    "distributed",
]

NON_APAC_DISQUALIFIERS = [
    "united states",
    "u.s.",
    "usa",
    "us only",
    "us-remote",
    "remote - us",
    "remote, us",
    "remote (us)",
    "canada",
    "united kingdom",
    "uk only",
    "london",
    "germany",
    "berlin",
    "france",
    "paris",
    "netherlands",
    "amsterdam",
    "spain",
    "poland",
    "brazil",
    "mexico",
    "argentina",
    "colombia",
    "emea",
    "amer",
    "americas",
    "latam",
    "europe",
    "dublin",
    "ireland",
    "sweden",
    "portugal",
    "israel",
    "virginia",
    "california",
    "new york",
    "seattle",
    "texas",
    "austin",
    "san francisco",
    "malta",
    "türkiye",
    "turkey",
    "seychelles",
]


def normalize_text(value: str) -> str:
    lowered = (value or "").lower().strip()
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def compute_dedup_hash(company: str, title: str) -> str:
    key = f"{normalize_text(company)}|{normalize_text(title)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def should_prefilter_out(job: RawJob, preferences: dict[str, Any]) -> tuple[bool, str | None]:
    title_raw = job.title or ""
    title_lower = f" {title_raw.lower()} "
    loc_lower = (job.location_raw or "").lower().strip()

    exclude_keywords: list[str] = list(
        set((preferences.get("exclude_title_keywords") or []) + NON_TECH_EXCLUSIONS)
    )
    for kw in exclude_keywords:
        kw_l = kw.lower()
        if kw_l in title_lower:
            return True, f"Excluded title keyword: '{kw.strip()}'"

    # Must match at least one word-bounded technical/engineering/QA domain keyword
    if not TECH_DOMAIN_REGEX.search(title_raw):
        return True, "Title is not a technical / engineering / QA role"

    # Location check: must match APAC / Remote / Global and not be restricted to US/EMEA/LATAM
    if loc_lower:
        has_explicit_apac = any(
            m in loc_lower
            for m in [
                "jakarta",
                "indonesia",
                "singapore",
                "apac",
                "asia",
                "southeast asia",
                "vietnam",
                "malaysia",
                "thailand",
                "bangkok",
                "philippines",
                "manila",
                "hong kong",
                "taiwan",
                "taipei",
                "tokyo",
                "japan",
                "australia",
                "sydney",
                "melbourne",
                "india",
                "global",
                "worldwide",
                "anywhere",
                "home based - worldwide",
            ]
        )
        has_non_apac = any(m in loc_lower for m in NON_APAC_DISQUALIFIERS)
        if has_non_apac and not has_explicit_apac:
            return True, f"Location outside target APAC geographies ({job.location_raw})"

        has_any_apac_or_remote = any(m in loc_lower for m in APAC_OR_REMOTE_MARKERS)
        if not has_any_apac_or_remote:
            return True, f"Location not in APAC or Remote ({job.location_raw})"

    return False, None


def priority_rank_for_scoring(job: RawJob) -> int:
    """Higher score means higher priority to consume LLM scoring quota first."""
    title_l = (job.title or "").lower()
    loc_l = (job.location_raw or "").lower()
    score = 0
    if any(k in title_l for k in ["head of", "vp", "vice president", "director", "chief", "cto"]):
        score += 35
    elif any(k in title_l for k in ["manager", "em", "principal", "staff", "lead", "architect"]):
        score += 25
    if any(k in title_l for k in ["qa", "quality", "test", "sdet", "automation", "devex", "platform"]):
        score += 20
    if any(k in loc_l for k in ["jakarta", "indonesia"]):
        score += 35
    elif any(k in loc_l for k in ["singapore", "apac", "southeast asia", "bangkok", "vietnam", "malaysia"]):
        score += 25
    elif any(k in loc_l for k in ["worldwide", "global", "remote"]):
        score += 15
    return score
