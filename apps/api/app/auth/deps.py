"""FastAPI dependencies for authentication and operator scoping.

The operator is always resolved from the verified user's membership row.
No client-supplied operator id is ever read.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import InvalidToken, TokenUser, verify_access_token
from app.db import DbConn
from app.domain import membership

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class OperatorContext:
    user_id: uuid.UUID
    email: str | None
    operator_id: uuid.UUID
    operator_name: str
    role: str

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenUser:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    try:
        return verify_access_token(credentials.credentials)
    except InvalidToken:
        raise unauthorized from None


def get_operator_context(
    user: Annotated[TokenUser, Depends(get_current_user)],
    conn: DbConn,
) -> OperatorContext:
    found = membership.fetch_membership(conn, user.user_id)
    if found is None or found.operator_status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No active operator membership")
    return OperatorContext(
        user_id=user.user_id,
        email=user.email,
        operator_id=found.operator_id,
        operator_name=found.operator_name,
        role=found.role,
    )


def require_owner(
    ctx: Annotated[OperatorContext, Depends(get_operator_context)],
) -> OperatorContext:
    if not ctx.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    return ctx


CurrentOperator = Annotated[OperatorContext, Depends(get_operator_context)]
OwnerOperator = Annotated[OperatorContext, Depends(require_owner)]
