import json
import os
import sys

import httpx


BASE_URL = os.getenv(
    "REEFCARE_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

EMAIL = os.getenv(
    "REEFCARE_TEST_EMAIL"
)

PASSWORD = os.getenv(
    "REEFCARE_TEST_PASSWORD"
)


def print_response(
    label: str,
    response: httpx.Response,
):
    print(f"\n=== {label} ===")
    print(
        "status:",
        response.status_code,
    )

    try:
        print(
            json.dumps(
                response.json(),
                indent=2,
            )
        )
    except ValueError:
        print(response.text)


def main() -> int:
    if not EMAIL or not PASSWORD:
        print(
            "Set REEFCARE_TEST_EMAIL "
            "and REEFCARE_TEST_PASSWORD "
            "before running this script."
        )

        return 2

    with httpx.Client(
        base_url=BASE_URL,
        timeout=15.0,
    ) as client:

        login = client.post(
            "/api/v1/auth/login",
            data={
                "username": EMAIL,
                "password": PASSWORD,
            },
        )

        print_response(
            "LOGIN",
            login,
        )

        login.raise_for_status()

        # Your current AuthResponse uses
        # top-level snake_case.
        token = (
            login.json()[
                "access_token"
            ]
        )

        headers = {
            "Authorization":
                f"Bearer {token}"
        }

        mine = client.get(
            "/api/v1/reports/mine",
            headers=headers,
        )

        print_response(
            "MY REPORTS",
            mine,
        )

        mine.raise_for_status()

        items = (
            mine.json()
            .get("items", [])
        )

        if not items:
            print(
                "\nNo reports exist for "
                "this observer."
            )
            return 0

        report_reference = (
            items[0][
                "reportReference"
            ]
        )

        detail = client.get(
            (
                "/api/v1/reports/"
                f"{report_reference}"
            ),
            headers=headers,
        )

        print_response(
            "REPORT DETAIL",
            detail,
        )

        detail.raise_for_status()

        timeline = client.get(
            (
                "/api/v1/reports/"
                f"{report_reference}"
                "/timeline"
            ),
            headers=headers,
        )

        print_response(
            "REPORT TIMELINE",
            timeline,
        )

        timeline.raise_for_status()

    print(
        "\nObserver endpoint "
        "smoke test passed."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())