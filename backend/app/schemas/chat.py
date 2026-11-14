from pydantic import BaseModel
from uuid import UUID


class StartChat(BaseModel):
    chat_id: UUID | None
    query: str
    repo_id: UUID | None

class EditChat(BaseModel):
    chat_id: UUID
    conversation_id: UUID | None
    query: str