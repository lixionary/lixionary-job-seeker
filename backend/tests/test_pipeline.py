from app.models import RawJob
from app.services.prefilter import compute_dedup_hash, should_prefilter_out
from app.services.scorer import extract_json_object, heuristic_score_job


def test_dedup_hash_normalization():
    h1 = compute_dedup_hash("Grab", "Head of Quality Engineering")
    h2 = compute_dedup_hash("  grab ", "Head of Quality Engineering!!")
    h3 = compute_dedup_hash("Agoda", "Head of Quality Engineering")
    assert h1 == h2
    assert h1 != h3


def test_prefilter_excludes_junior_and_non_engineering():
    preferences = {
        "exclude_title_keywords": ["intern", "junior", "account executive"],
        "include_title_keywords": ["engineer", "engineering", "qa", "quality", "head of", "director"],
    }
    intern_job = RawJob(
        company="Grab",
        title="Software Engineering Intern",
        location_raw="Jakarta, Indonesia",
        description="Internship role",
        source="greenhouse",
        url="https://example.com/1",
    )
    filtered, reason = should_prefilter_out(intern_job, preferences)
    assert filtered is True
    assert "intern" in (reason or "").lower()

    sales_job = RawJob(
        company="Grab",
        title="Enterprise Account Executive",
        location_raw="Jakarta, Indonesia",
        description="Sales role",
        source="greenhouse",
        url="https://example.com/2",
    )
    filtered2, _ = should_prefilter_out(sales_job, preferences)
    assert filtered2 is True

    us_only_job = RawJob(
        company="Stripe",
        title="Engineering Manager",
        location_raw="San Francisco, United States",
        description="US role",
        source="greenhouse",
        url="https://example.com/3",
    )
    filtered3, reason3 = should_prefilter_out(us_only_job, preferences)
    assert filtered3 is True
    assert "outside target apac" in (reason3 or "").lower()

    target_job = RawJob(
        company="Grab",
        title="Head of Quality Engineering",
        location_raw="Jakarta, Indonesia",
        description="Lead QA org",
        source="greenhouse",
        url="https://example.com/4",
    )
    filtered4, _ = should_prefilter_out(target_job, preferences)
    assert filtered4 is False


def test_extract_json_object_with_reasoning_tags_and_fences():
    raw_llm_output = """
    <think>
    Evaluating candidate experience: 10+ years logistics tech, 41 QA engineers, 92% coverage.
    </think>
    ```json
    {
      "match_score": 9,
      "role_track": "Quality Engineering Leadership",
      "location_policy": "Hybrid - Jakarta",
      "relocation_or_visa_note": "Local role",
      "summary": "Strong match for QA leadership.",
      "match_reasons": ["Led 41 QA engineers"],
      "red_flags": [],
      "tailoring_angle": "Highlight 92% automation coverage."
    }
    ```
    """
    parsed = extract_json_object(raw_llm_output)
    assert parsed["match_score"] == 9
    assert parsed["role_track"] == "Quality Engineering Leadership"


def test_heuristic_scorer_high_match():
    job = RawJob(
        company="Xendit",
        title="Head of Engineering - Logistics & Platform",
        location_raw="Jakarta, Indonesia (Hybrid)",
        description="Looking for a Head of Engineering to scale our engineering & quality automation org and AI developer productivity.",
        source="lever",
        url="https://example.com/xendit",
    )
    analysis = heuristic_score_job(job, "# CV", {})
    assert analysis.match_score >= 8
    assert analysis.role_track == "Engineering Leadership"
    assert analysis.scored_by == "heuristic_fallback"
