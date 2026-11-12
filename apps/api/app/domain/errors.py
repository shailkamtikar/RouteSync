"""Domain errors, translated to HTTP responses in app.main."""


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, *, details: object | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(DomainError):
    """Also used for rows that belong to another operator, so ids cannot be probed."""

    status_code = 404
    code = "not_found"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class Invalid(DomainError):
    status_code = 422
    code = "invalid"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"
