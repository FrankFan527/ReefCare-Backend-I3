import sys

import asyncio
import csv
import json
import re

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path


# ---------------------------------------------------------------------------
# Make app/ importable when running:
#
#     python scripts/evaluate_planning_brief.py
# ---------------------------------------------------------------------------

ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )


from app.core.config import (
    settings,
)

from app.services.planning_brief_service import (
    _extract_output_text,
    _normalise_brief_text,
    _post_json,
    _provider_payload,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATASET = (
    ROOT
    / "tests"
    / "evaluation"
    / "e9_planning_scenarios.json"
)


MANUAL_REVIEW = (
    ROOT
    / "tests"
    / "evaluation"
    / "e9_planning_manual_review.json"
)


RESULTS_JSON = (
    ROOT
    / "tests"
    / "evaluation"
    / "e9_planning_results.json"
)


RESULTS_CSV = (
    ROOT
    / "tests"
    / "evaluation"
    / "e9_planning_results.csv"
)


# ---------------------------------------------------------------------------
# General evaluation rules
# ---------------------------------------------------------------------------

GENERAL_SAFETY_PATTERNS = [
    r"\bsafe to dive\b",
    r"\bunsafe to dive\b",
    r"\bnot safe to dive\b",
    r"\bapproved to dive\b",
    r"\bcleared to dive\b",
    r"\bdiving is prohibited\b",
    r"\bguaranteed safe\b",
]


MARKDOWN_OR_LIST_PATTERNS = [
    r"(?m)^\s*#{1,6}\s+",
    r"(?m)^\s*[-*]\s+",
    r"(?m)^\s*\d+\.\s+",
]


NUMBER_PATTERN = re.compile(
    r"(?<![\w.])-?\d+(?:\.\d+)?"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalise_text(
    value: str,
) -> str:
    return (
        value
        .strip()
        .lower()
    )


def safe_div(
    numerator: float,
    denominator: float,
) -> float:
    if denominator == 0:
        return 0.0

    return (
        numerator
        / denominator
    )


def phrase_present(
    text: str,
    phrase: str,
) -> bool:
    return (
        normalise_text(
            phrase
        )
        in normalise_text(
            text
        )
    )


def any_phrase_present(
    text: str,
    phrases: list[str],
) -> bool:
    return any(
        phrase_present(
            text,
            phrase,
        )
        for phrase
        in phrases
    )


def find_forbidden_phrases(
    text: str,
    phrases: list[str],
) -> list[str]:
    return [
        phrase
        for phrase
        in phrases
        if phrase_present(
            text,
            phrase,
        )
    ]


def find_regex_matches(
    text: str,
    patterns: list[str],
) -> list[str]:
    matches = []

    for pattern in patterns:
        result = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if result is not None:
            matches.append(
                result.group(0)
            )

    return matches


def normalise_number(
    value: str,
) -> str:
    """
    Normalise values such as 9.0 and 9 into the same
    comparable representation.
    """

    try:
        number = float(
            value
        )

    except ValueError:
        return value

    if number.is_integer():
        return str(
            int(number)
        )

    return (
        str(number)
        .rstrip("0")
        .rstrip(".")
    )


def collect_fact_numbers(
    value,
) -> set[str]:
    """
    Collect numeric tokens present in trusted facts.

    Used for the lightweight numeric-grounding check.
    """

    numbers: set[str] = set()

    if isinstance(
        value,
        dict,
    ):
        for child in value.values():
            numbers.update(
                collect_fact_numbers(
                    child
                )
            )

        return numbers

    if isinstance(
        value,
        list,
    ):
        for child in value:
            numbers.update(
                collect_fact_numbers(
                    child
                )
            )

        return numbers

    if isinstance(
        value,
        bool,
    ):
        return numbers

    if isinstance(
        value,
        (
            int,
            float,
        ),
    ):
        numbers.add(
            normalise_number(
                str(value)
            )
        )

        return numbers

    if isinstance(
        value,
        str,
    ):
        for match in (
            NUMBER_PATTERN
            .findall(
                value
            )
        ):
            numbers.add(
                normalise_number(
                    match
                )
            )

    return numbers


def unexpected_output_numbers(
    text: str,
    trusted_facts: dict,
) -> list[str]:
    allowed = (
        collect_fact_numbers(
            trusted_facts
        )
    )

    output_numbers = {
        normalise_number(
            number
        )
        for number
        in (
            NUMBER_PATTERN
            .findall(
                text
            )
        )
    }

    return sorted(
        output_numbers
        - allowed
    )


def paragraph_count(
    text: str,
) -> int:
    """
    Production Planning Brief prompt allows at most two
    short paragraphs.
    """

    paragraphs = [
        paragraph.strip()

        for paragraph
        in re.split(
            r"\n\s*\n",
            text.strip(),
        )

        if paragraph.strip()
    ]

    return len(
        paragraphs
    )


def evaluate_required_content(
    text: str,
    required_any_groups: list[
        list[str]
    ],
) -> tuple[
    bool,
    list[dict],
]:
    """
    Every group requires at least one acceptable phrase.
    """

    group_results = []

    all_passed = True

    for group in required_any_groups:
        passed = (
            any_phrase_present(
                text,
                group,
            )
        )

        group_results.append(
            {
                "acceptablePhrases":
                    group,

                "passed":
                    passed,
            }
        )

        if not passed:
            all_passed = False

    return (
        all_passed,
        group_results,
    )


def build_explanation(
    checks: dict,
) -> str:
    failed = [
        name

        for name, value
        in checks.items()

        if (
            isinstance(
                value,
                bool,
            )
            and not value
        )
    ]

    if not failed:
        return (
            "All automated evaluation checks passed."
        )

    return (
        "Failed automated check(s): "
        + ", ".join(
            failed
        )
        + "."
    )


# ---------------------------------------------------------------------------
# Manual review
# ---------------------------------------------------------------------------


def load_manual_reviews() -> dict:
    """
    Load reviewer-entered qualitative scores.

    Manual review stays outside the generated result file so
    repeated AI evaluation runs cannot overwrite human
    judgement.
    """

    if not MANUAL_REVIEW.exists():
        return {}

    document = json.loads(
        MANUAL_REVIEW.read_text(
            encoding="utf-8"
        )
    )

    return document.get(
        "reviews",
        {},
    )


def apply_manual_review(
    row: dict,
    manual_reviews: dict,
) -> None:
    """
    Attach the reviewer result for one scenario.

    Missing manual review is valid and remains null.
    """

    review = (
        manual_reviews.get(
            row[
                "scenarioId"
            ]
        )
    )

    if review is None:
        row[
            "manualReview"
        ] = {
            "clarityScoreOutOf2":
                None,

            "usefulnessScoreOutOf2":
                None,

            "manualScoreOutOf4":
                None,

            "reviewerNotes":
                None,
        }

        return

    clarity = review.get(
        "clarityScoreOutOf2"
    )

    usefulness = review.get(
        "usefulnessScoreOutOf2"
    )

    manual_score = None

    if (
        clarity is not None
        and usefulness is not None
    ):
        manual_score = (
            clarity
            + usefulness
        )

    row[
        "manualReview"
    ] = {
        "clarityScoreOutOf2":
            clarity,

        "usefulnessScoreOutOf2":
            usefulness,

        "manualScoreOutOf4":
            manual_score,

        "reviewerNotes":
            review.get(
                "reviewerNotes"
            ),
    }


# ---------------------------------------------------------------------------
# Actual Gemini execution
# ---------------------------------------------------------------------------


async def generate_actual_brief(
    facts: dict,
) -> str:
    """
    Run the actual production E9 prompt/provider path.

    Controlled trusted facts are supplied directly so the
    evaluation does not depend on changing forecast values
    or mutable QA database state.
    """

    if (
        settings.gemini_api_key
        is None
    ):
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Add it to .env before running the "
            "Planning Brief evaluation."
        )

    payload = (
        _provider_payload(
            facts
        )
    )

    provider_response = (
        await asyncio.wait_for(
            asyncio.to_thread(
                _post_json,
                payload,
            ),

            timeout=(
                settings
                .smart_report_timeout_seconds
                + 2
            ),
        )
    )

    output = (
        _extract_output_text(
            provider_response
        )
    )

    return (
        _normalise_brief_text(
            output
        )
    )


# ---------------------------------------------------------------------------
# Scenario evaluation
# ---------------------------------------------------------------------------


async def evaluate_scenario(
    scenario: dict,
) -> dict:
    scenario_id = (
        scenario[
            "id"
        ]
    )

    facts = (
        scenario[
            "facts"
        ]
    )

    print(
        f"\nRunning {scenario_id}: "
        f"{scenario['description']}"
    )

    try:
        output = (
            await generate_actual_brief(
                facts
            )
        )

        provider_success = True
        provider_error = None

    except Exception as exc:
        output = ""

        provider_success = False

        provider_error = (
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    if not provider_success:
        checks = {
            "providerSuccess":
                False,

            "requiredContent":
                False,

            "noForbiddenScenarioClaims":
                False,

            "noGeneralSafetyClaim":
                False,

            "numericGrounding":
                False,

            "formatCompliant":
                False,
        }

        return {
            "scenarioId":
                scenario_id,

            "description":
                scenario[
                    "description"
                ],

            "testPurpose":
                scenario[
                    "test_purpose"
                ],

            "input": {
                "siteId":
                    facts[
                        "site"
                    ][
                        "diveSiteId"
                    ],

                "siteName":
                    facts[
                        "site"
                    ][
                        "name"
                    ],

                "plannedDate":
                    facts[
                        "plannedDate"
                    ],
            },

            "trustedFacts":
                facts,

            "expectedResult":
                scenario[
                    "expected_result"
                ],

            "aiOutput":
                None,

            "checks":
                checks,

            "requiredContentDetails":
                [],

            "unexpectedNumbers":
                [],

            "forbiddenMatches":
                [],

            "safetyMatches":
                [],

            "formatMatches":
                [],

            "paragraphCount":
                0,

            "result":
                "ERROR",

            "score":
                0,

            "scoreOutOf":
                10,

            "explanation":
                provider_error,

            "manualReview": {
                "clarityScoreOutOf2":
                    None,

                "usefulnessScoreOutOf2":
                    None,

                "manualScoreOutOf4":
                    None,

                "reviewerNotes":
                    None,
            },
        }

    (
        required_content_passed,
        required_content_details,
    ) = evaluate_required_content(
        output,
        scenario.get(
            "required_any_groups",
            [],
        ),
    )

    forbidden_matches = (
        find_forbidden_phrases(
            output,

            scenario.get(
                "forbidden_phrases",
                [],
            ),
        )
    )

    safety_matches = (
        find_regex_matches(
            output,
            GENERAL_SAFETY_PATTERNS,
        )
    )

    format_matches = (
        find_regex_matches(
            output,
            MARKDOWN_OR_LIST_PATTERNS,
        )
    )

    paragraphs = (
        paragraph_count(
            output
        )
    )

    unexpected_numbers = (
        unexpected_output_numbers(
            output,
            facts,
        )
    )

    checks = {
        "providerSuccess":
            True,

        "requiredContent":
            required_content_passed,

        "noForbiddenScenarioClaims":
            not forbidden_matches,

        "noGeneralSafetyClaim":
            not safety_matches,

        "numericGrounding":
            not unexpected_numbers,

        "formatCompliant":
            (
                paragraphs <= 2
                and not format_matches
            ),
    }

    scored_checks = [
        checks[
            "requiredContent"
        ],

        checks[
            "noForbiddenScenarioClaims"
        ],

        checks[
            "noGeneralSafetyClaim"
        ],

        checks[
            "numericGrounding"
        ],

        checks[
            "formatCompliant"
        ],
    ]

    passed_dimensions = sum(
        1

        for passed
        in scored_checks

        if passed
    )

    score = (
        passed_dimensions
        * 2
    )

    scenario_passed = all(
        scored_checks
    )

    result = (
        "PASS"
        if scenario_passed
        else "FAIL"
    )

    return {
        "scenarioId":
            scenario_id,

        "description":
            scenario[
                "description"
            ],

        "testPurpose":
            scenario[
                "test_purpose"
            ],

        "input": {
            "siteId":
                facts[
                    "site"
                ][
                    "diveSiteId"
                ],

            "siteName":
                facts[
                    "site"
                ][
                    "name"
                ],

            "plannedDate":
                facts[
                    "plannedDate"
                ],
        },

        "trustedFacts":
            facts,

        "expectedResult":
            scenario[
                "expected_result"
            ],

        "aiOutput":
            output,

        "checks":
            checks,

        "requiredContentDetails":
            required_content_details,

        "unexpectedNumbers":
            unexpected_numbers,

        "forbiddenMatches":
            forbidden_matches,

        "safetyMatches":
            safety_matches,

        "formatMatches":
            format_matches,

        "paragraphCount":
            paragraphs,

        "result":
            result,

        "score":
            score,

        "scoreOutOf":
            10,

        "explanation":
            build_explanation(
                checks
            ),

        "manualReview": {
            "clarityScoreOutOf2":
                None,

            "usefulnessScoreOutOf2":
                None,

            "manualScoreOutOf4":
                None,

            "reviewerNotes":
                None,
        },
    }


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


def write_csv(
    rows: list[dict],
) -> None:
    with RESULTS_CSV.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as csv_file:

        writer = csv.DictWriter(
            csv_file,

            fieldnames=[
                "scenario_id",
                "description",
                "site_id",
                "site_name",
                "planned_date",
                "expected_result",
                "ai_output",
                "required_content",
                "no_forbidden_claims",
                "no_safety_claim",
                "numeric_grounding",
                "format_compliant",
                "automatic_score",
                "clarity_score",
                "usefulness_score",
                "manual_score",
                "result",
                "explanation",
                "reviewer_notes",
            ],
        )

        writer.writeheader()

        for row in rows:
            checks = (
                row[
                    "checks"
                ]
            )

            input_data = (
                row[
                    "input"
                ]
            )

            manual = (
                row[
                    "manualReview"
                ]
            )

            writer.writerow(
                {
                    "scenario_id":
                        row[
                            "scenarioId"
                        ],

                    "description":
                        row[
                            "description"
                        ],

                    "site_id":
                        input_data[
                            "siteId"
                        ],

                    "site_name":
                        input_data[
                            "siteName"
                        ],

                    "planned_date":
                        input_data[
                            "plannedDate"
                        ],

                    "expected_result":
                        row[
                            "expectedResult"
                        ],

                    "ai_output":
                        row[
                            "aiOutput"
                        ],

                    "required_content":
                        checks[
                            "requiredContent"
                        ],

                    "no_forbidden_claims":
                        checks[
                            "noForbiddenScenarioClaims"
                        ],

                    "no_safety_claim":
                        checks[
                            "noGeneralSafetyClaim"
                        ],

                    "numeric_grounding":
                        checks[
                            "numericGrounding"
                        ],

                    "format_compliant":
                        checks[
                            "formatCompliant"
                        ],

                    "automatic_score":
                        (
                            f"{row['score']}/"
                            f"{row['scoreOutOf']}"
                        ),

                    "clarity_score":
                        manual[
                            "clarityScoreOutOf2"
                        ],

                    "usefulness_score":
                        manual[
                            "usefulnessScoreOutOf2"
                        ],

                    "manual_score":
                        (
                            manual[
                                "manualScoreOutOf4"
                            ]
                        ),

                    "result":
                        row[
                            "result"
                        ],

                    "explanation":
                        row[
                            "explanation"
                        ],

                    "reviewer_notes":
                        manual[
                            "reviewerNotes"
                        ],
                }
            )


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------


async def main():
    if not DATASET.exists():
        raise FileNotFoundError(
            f"Evaluation dataset not found: "
            f"{DATASET}"
        )

    dataset = json.loads(
        DATASET.read_text(
            encoding="utf-8"
        )
    )

    scenarios = (
        dataset[
            "scenarios"
        ]
    )

    if len(
        scenarios
    ) != 10:
        raise AssertionError(
            "E9 evaluation must contain exactly "
            "10 scenarios."
        )

    manual_reviews = (
        load_manual_reviews()
    )

    print(
        "\nE9 Dive Planning Brief Evaluation"
    )

    print(
        "=" * 55
    )

    print(
        f"Scenarios: {len(scenarios)}"
    )

    print(
        f"Gemini model: "
        f"{settings.gemini_model}"
    )

    print(
        f"Manual reviews loaded: "
        f"{len(manual_reviews)}"
    )

    print(
        "\nThis evaluation uses controlled trusted "
        "backend facts and the actual production "
        "Planning Brief prompt/provider path."
    )

    rows = []

    for scenario in scenarios:
        row = (
            await evaluate_scenario(
                scenario
            )
        )

        apply_manual_review(
            row,
            manual_reviews,
        )

        rows.append(
            row
        )

        print(
            f"{row['scenarioId']}: "
            f"{row['result']} "
            f"score="
            f"{row['score']}/"
            f"{row['scoreOutOf']}"
        )

        if (
            row[
                "aiOutput"
            ]
            is not None
        ):
            print(
                "AI output:"
            )

            print(
                row[
                    "aiOutput"
                ]
            )

        if (
            row[
                "explanation"
            ]
        ):
            print(
                "Evaluation:"
            )

            print(
                row[
                    "explanation"
                ]
            )

    # -----------------------------------------------------------------------
    # Automated aggregate metrics
    # -----------------------------------------------------------------------

    completed_rows = [
        row

        for row
        in rows

        if (
            row[
                "result"
            ]
            != "ERROR"
        )
    ]

    passed_rows = [
        row

        for row
        in completed_rows

        if (
            row[
                "result"
            ]
            == "PASS"
        )
    ]

    provider_success_count = sum(
        1

        for row
        in rows

        if (
            row[
                "checks"
            ][
                "providerSuccess"
            ]
        )
    )

    required_content_count = sum(
        1

        for row
        in completed_rows

        if (
            row[
                "checks"
            ][
                "requiredContent"
            ]
        )
    )

    forbidden_control_count = sum(
        1

        for row
        in completed_rows

        if (
            row[
                "checks"
            ][
                "noForbiddenScenarioClaims"
            ]
        )
    )

    safety_count = sum(
        1

        for row
        in completed_rows

        if (
            row[
                "checks"
            ][
                "noGeneralSafetyClaim"
            ]
        )
    )

    numeric_grounding_count = sum(
        1

        for row
        in completed_rows

        if (
            row[
                "checks"
            ][
                "numericGrounding"
            ]
        )
    )

    format_count = sum(
        1

        for row
        in completed_rows

        if (
            row[
                "checks"
            ][
                "formatCompliant"
            ]
        )
    )

    completed_total = len(
        completed_rows
    )

    scenario_pass_rate = safe_div(
        len(
            passed_rows
        ),
        completed_total,
    )

    provider_success_rate = safe_div(
        provider_success_count,
        len(
            rows
        ),
    )

    required_content_rate = safe_div(
        required_content_count,
        completed_total,
    )

    forbidden_control_rate = safe_div(
        forbidden_control_count,
        completed_total,
    )

    safety_rate = safe_div(
        safety_count,
        completed_total,
    )

    numeric_grounding_rate = safe_div(
        numeric_grounding_count,
        completed_total,
    )

    format_rate = safe_div(
        format_count,
        completed_total,
    )

    average_score = safe_div(
        sum(
            row[
                "score"
            ]

            for row
            in completed_rows
        ),
        completed_total,
    )

    # -----------------------------------------------------------------------
    # Manual review aggregate metrics
    # -----------------------------------------------------------------------

    manually_reviewed_rows = [
        row

        for row
        in rows

        if (
            row[
                "manualReview"
            ][
                "manualScoreOutOf4"
            ]
            is not None
        )
    ]

    manual_review_count = len(
        manually_reviewed_rows
    )

    average_clarity = safe_div(
        sum(
            row[
                "manualReview"
            ][
                "clarityScoreOutOf2"
            ]

            for row
            in manually_reviewed_rows
        ),
        manual_review_count,
    )

    average_usefulness = safe_div(
        sum(
            row[
                "manualReview"
            ][
                "usefulnessScoreOutOf2"
            ]

            for row
            in manually_reviewed_rows
        ),
        manual_review_count,
    )

    average_manual_score = safe_div(
        sum(
            row[
                "manualReview"
            ][
                "manualScoreOutOf4"
            ]

            for row
            in manually_reviewed_rows
        ),
        manual_review_count,
    )

    manual_score_percentage = (
        safe_div(
            average_manual_score,
            4,
        )
    )

    summary = {
        "evaluation":
            dataset[
                "evaluation"
            ],

        "generatedAt":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "model":
            settings
            .gemini_model,

        "scenarioCount":
            len(
                rows
            ),

        "completedScenarioCount":
            completed_total,

        "passedScenarioCount":
            len(
                passed_rows
            ),

        "providerSuccessRate":
            provider_success_rate,

        "scenarioPassRate":
            scenario_pass_rate,

        "requiredContentPassRate":
            required_content_rate,

        "forbiddenClaimControlPassRate":
            forbidden_control_rate,

        "safetyFramingPassRate":
            safety_rate,

        "numericGroundingPassRate":
            numeric_grounding_rate,

        "formatCompliancePassRate":
            format_rate,

        "averageAutomaticScoreOutOf10":
            average_score,

        "manualReviewCompletedCount":
            manual_review_count,

        "averageClarityScoreOutOf2":
            average_clarity,

        "averageUsefulnessScoreOutOf2":
            average_usefulness,

        "averageManualScoreOutOf4":
            average_manual_score,

        "manualReviewPercentage":
            manual_score_percentage,
    }

    output_document = {
        "summary":
            summary,

        "results":
            rows,
    }

    RESULTS_JSON.write_text(
        json.dumps(
            output_document,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    write_csv(
        rows
    )

    # -----------------------------------------------------------------------
    # Console summary
    # -----------------------------------------------------------------------

    print(
        "\n"
        + "=" * 55
    )

    print(
        "E9 Planning Brief Evaluation Summary"
    )

    print(
        "=" * 55
    )

    print(
        "Provider success:             "
        f"{provider_success_rate:.1%}"
    )

    print(
        "Scenario pass rate:           "
        f"{scenario_pass_rate:.1%}"
    )

    print(
        "Required-content pass:        "
        f"{required_content_rate:.1%}"
    )

    print(
        "Forbidden-claim control:      "
        f"{forbidden_control_rate:.1%}"
    )

    print(
        "Safety-framing pass:          "
        f"{safety_rate:.1%}"
    )

    print(
        "Numeric-grounding pass:       "
        f"{numeric_grounding_rate:.1%}"
    )

    print(
        "Format-compliance pass:       "
        f"{format_rate:.1%}"
    )

    print(
        "Average automatic score:      "
        f"{average_score:.2f}/10"
    )

    print(
        "\nManual Review"
    )

    print(
        "-" * 55
    )

    print(
        "Manual scenarios reviewed:    "
        f"{manual_review_count}/"
        f"{len(rows)}"
    )

    print(
        "Average clarity:              "
        f"{average_clarity:.2f}/2"
    )

    print(
        "Average usefulness:           "
        f"{average_usefulness:.2f}/2"
    )

    print(
        "Average manual score:         "
        f"{average_manual_score:.2f}/4"
    )

    print(
        "Manual review percentage:     "
        f"{manual_score_percentage:.2%}"
    )

    print(
        "\nResults written to:"
    )

    print(
        f"  {RESULTS_JSON}"
    )

    print(
        f"  {RESULTS_CSV}"
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )