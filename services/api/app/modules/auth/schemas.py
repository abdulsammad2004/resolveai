import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.workspaces.models import Role
from app.modules.workspaces.schemas import WorkspaceOut

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 256


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    full_name: str = Field(min_length=1, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str


class MeResponse(BaseModel):
    user: UserOut
    workspace: WorkspaceOut
    role: Role


class AuthResponse(MeResponse):
    access_token: str
    token_type: str = "bearer"
