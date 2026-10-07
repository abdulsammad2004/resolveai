from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status

from app.core.config import get_settings
from app.core.deps import CurrentPrincipal, DBSession, TenantDB
from app.modules.auth import service
from app.modules.auth.schemas import (
    AuthResponse,
    LoginRequest,
    MeResponse,
    SignupRequest,
    UserOut,
)
from app.modules.auth.service import AuthResult
from app.modules.workspaces.models import Role
from app.modules.workspaces.schemas import WorkspaceOut

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )


def clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )


def auth_response(response: Response, result: AuthResult) -> AuthResponse:
    set_refresh_cookie(response, result.refresh_token)
    return AuthResponse(
        access_token=result.access_token,
        user=UserOut.model_validate(result.user),
        workspace=WorkspaceOut.model_validate(result.workspace),
        role=result.role,
    )


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, response: Response, db: DBSession) -> AuthResponse:
    result = await service.signup(
        db, body.email, body.password, body.full_name, body.workspace_name
    )
    return auth_response(response, result)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, response: Response, db: DBSession) -> AuthResponse:
    result = await service.login(db, body.email, body.password)
    return auth_response(response, result)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    response: Response, db: DBSession, refresh_token: RefreshCookie = None
) -> AuthResponse:
    result = await service.refresh(db, refresh_token)
    return auth_response(response, result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(db: DBSession, refresh_token: RefreshCookie = None) -> Response:
    await service.logout(db, refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=MeResponse)
async def me(principal: CurrentPrincipal, db: TenantDB) -> MeResponse:
    user, workspace = await service.get_me(db, principal)
    return MeResponse(
        user=UserOut.model_validate(user),
        workspace=WorkspaceOut.model_validate(workspace),
        role=Role(principal.role),
    )
