import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

ActorTypeLiteral = Literal["user", "ai", "system", "customer"]


class AuditEventOut(BaseModel):
    id: uuid.UUID
    actor_type: ActorTypeLiteral
    actor_id: uuid.UUID | None
    # The acting user's name, when the actor is a user who still exists.
    actor_name: str | None
    action: str
    target_type: str
    target_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime
