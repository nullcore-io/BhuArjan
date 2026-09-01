"""RFC 7807 problem+json errors (see Docs/APIs.md §6)."""

from fastapi import Request
from fastapi.responses import JSONResponse


class Problem(Exception):
    def __init__(
        self,
        type_: str,
        title: str,
        status: int,
        detail: str = "",
        errors: list | None = None,
        ruleset_ref: str | None = None,
    ):
        self.type = type_
        self.title = title
        self.status = status
        self.detail = detail
        self.errors = errors or []
        self.ruleset_ref = ruleset_ref


def problem_handler(request: Request, exc: Problem) -> JSONResponse:
    body = {
        "type": exc.type,
        "title": exc.title,
        "status": exc.status,
        "detail": exc.detail,
        "instance": str(request.url.path),
    }
    if exc.errors:
        body["errors"] = exc.errors
    if exc.ruleset_ref:
        body["ruleset_ref"] = exc.ruleset_ref
    return JSONResponse(status_code=exc.status, content=body, media_type="application/problem+json")


def transition_not_allowed(detail: str, ruleset_ref: str) -> Problem:
    return Problem("transition_not_allowed", "Transition not allowed", 422, detail, ruleset_ref=ruleset_ref)


def precondition_failed(errors: list, detail: str = "Required prior event missing") -> Problem:
    return Problem("precondition_failed", "Precondition failed", 422, detail, errors=errors)


def guard_failed(detail: str, errors: list | None = None) -> Problem:
    return Problem("guard_failed", "Guard failed", 422, detail, errors=errors)


def document_required(detail: str = "Statutory event requires a document") -> Problem:
    return Problem("document_required", "Document required", 422, detail)


def not_found() -> Problem:
    return Problem("not_found", "Not found", 404)


def stale_state(detail: str) -> Problem:
    return Problem("stale_state", "Stale state", 409, detail)
