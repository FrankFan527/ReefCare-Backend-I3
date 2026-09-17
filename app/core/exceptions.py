from dataclasses import dataclass

from fastapi import (
    FastAPI,
    Request,
    status,
)
from fastapi.responses import (
    JSONResponse,
)


class ServiceError(Exception):
    """
    Base exception for expected ReefCare service errors.
    """

    status_code = (
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )

    error_code = (
        "service_error"
    )

    default_message = (
        "Unable to complete the request"
    )

    def __init__(
        self,
        message: str | None = None,
        headers: (
            dict[str, str] | None
        ) = None,
    ):
        self.message = (
            message
            or self.default_message
        )

        self.headers = (
            headers
            or {}
        )

        super().__init__(
            self.message
        )


class AuthenticationError(
    ServiceError
):
    status_code = (
        status.HTTP_401_UNAUTHORIZED
    )

    error_code = (
        "authentication_error"
    )

    default_message = (
        "Authentication required"
    )


class AuthorizationError(
    ServiceError
):
    status_code = (
        status.HTTP_403_FORBIDDEN
    )

    error_code = (
        "authorization_error"
    )

    default_message = (
        "You do not have permission "
        "to perform this action"
    )


class NotFoundError(
    ServiceError
):
    status_code = (
        status.HTTP_404_NOT_FOUND
    )

    error_code = (
        "not_found"
    )

    default_message = (
        "Requested resource was not found"
    )


class ConflictError(
    ServiceError
):
    status_code = (
        status.HTTP_409_CONFLICT
    )

    error_code = (
        "conflict"
    )

    default_message = (
        "The request conflicts with "
        "the current resource state"
    )


class WorkflowError(
    ServiceError
):
    status_code = (
        status.HTTP_409_CONFLICT
    )

    error_code = (
        "workflow_error"
    )

    default_message = (
        "This action is not valid in "
        "the current workflow state"
    )


class WorkflowStateError(
    WorkflowError
):
    """
    Workflow conflict that also exposes the current safe
    case-status code.

    Used when the frontend needs to recover from a stale
    action without receiving any sensitive case detail.
    """

    error_code = (
        "invalid_workflow_state"
    )

    def __init__(
        self,
        message: str,
        current_status: str,
    ):
        self.current_status = (
            current_status
        )

        super().__init__(
            message=message
        )


class DomainValidationError(
    ServiceError
):
    status_code = (
        status.HTTP_400_BAD_REQUEST
    )

    error_code = (
        "validation_error"
    )

    default_message = (
        "Invalid request"
    )


class RateLimitError(
    ServiceError
):
    status_code = (
        status.HTTP_429_TOO_MANY_REQUESTS
    )

    error_code = (
        "rate_limit_exceeded"
    )

    default_message = (
        "Too many requests. "
        "Please try again later."
    )

    def __init__(
        self,
        retry_after: int,
    ):
        super().__init__(
            message=(
                self.default_message
            ),
            headers={
                "Retry-After":
                    str(
                        retry_after
                    ),
            },
        )


class DatabaseOperationError(
    ServiceError
):
    """
    Internal DB details must never be returned to clients.
    """

    status_code = (
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )

    error_code = (
        "database_error"
    )

    default_message = (
        "Unable to complete the database operation"
    )


@dataclass
class HTTPErrorMapping:
    status_code: int
    code: str
    message: str
    headers: dict[
        str,
        str,
    ]


def map_service_error_to_http(
    error: ServiceError,
) -> HTTPErrorMapping:
    return HTTPErrorMapping(
        status_code=(
            error.status_code
        ),
        code=(
            error.error_code
        ),
        message=(
            error.message
        ),
        headers=(
            error.headers
        ),
    )


async def service_error_handler(
    request: Request,
    exc: ServiceError,
):
    error = (
        map_service_error_to_http(
            exc
        )
    )

    content = {
        "detail":
            error.message,

        "code":
            error.code,
    }

    current_status = getattr(
        exc,
        "current_status",
        None,
    )

    if current_status is not None:
        content[
            "currentStatus"
        ] = current_status

    return JSONResponse(
        status_code=(
            error.status_code
        ),
        headers=(
            error.headers
        ),
        content=content,
    )


def register_exception_handlers(
    app: FastAPI,
) -> None:
    app.add_exception_handler(
        ServiceError,
        service_error_handler,
    )