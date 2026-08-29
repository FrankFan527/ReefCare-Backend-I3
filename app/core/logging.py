import logging
from typing import Any


SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "jwt",
    "jwt_secret_key",
    "database_url",
    "file_reference",
    "object_key",
    "external_auth_id",
    "latitude",
    "longitude",
    "precise_latitude",
    "precise_longitude",
    "coordinates",
}


def redact_sensitive_log_fields(
    value: Any,
):
    """
    Recursively remove sensitive ReefCare values before
    structured data is written to application logs.

    Particularly protects:
    - credentials and tokens
    - precise reef coordinates
    - private evidence object references
    - sensitive authentication fields
    """

    if isinstance(value, dict):
        redacted = {}

        for key, item in value.items():
            normalised_key = key.lower()

            if normalised_key in SENSITIVE_KEYS:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = (
                    redact_sensitive_log_fields(item)
                )

        return redacted

    if isinstance(value, list):
        return [
            redact_sensitive_log_fields(item)
            for item in value
        ]

    if isinstance(value, tuple):
        return tuple(
            redact_sensitive_log_fields(item)
            for item in value
        )

    return value


def configure_logging() -> None:
    """
    Minimal Iteration 1 application logging configuration.

    Do not enable verbose SQL/password/token logging here.
    """

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s "
            "%(message)s"
        ),
    )