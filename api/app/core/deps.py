from dataclasses import dataclass, field
from datetime import date

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import decode_token
from app.core.time import ist_today

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    name: str
    roles: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)  # org_unit ids; empty on national roles

    def has_role(self, *roles: str) -> bool:
        return any(r in self.roles for r in roles)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status_code=401, detail="unauthenticated")
    try:
        payload = decode_token(creds.credentials)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return CurrentUser(
        id=payload["sub"],
        name=payload.get("name", ""),
        roles=payload.get("roles", []),
        scopes=payload.get("scopes", []),
    )


def require_roles(*roles: str):
    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(*roles):
            raise HTTPException(status_code=404, detail="not_found")
        return user

    return checker


def get_effective_today(request: Request) -> date:
    """Demo clock: X-Demo-Date honoured only when DEMO_MODE=true. Otherwise today in
    IST — the statutory calendar, not the container's (Docs/rules.md C2)."""
    if settings.DEMO_MODE:
        hdr = request.headers.get("X-Demo-Date")
        if hdr:
            try:
                return date.fromisoformat(hdr)
            except ValueError:
                pass
    return ist_today()


DbDep = Depends(get_db)
