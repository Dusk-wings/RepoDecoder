from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from datetime import datetime


class GeneralChatInput(BaseModel):
    chat_id: UUID


class ChatRoomCreateInput(BaseModel):
    repo_id: UUID
    first_msg: str


class ChatRoomOutput(GeneralChatInput):
    chat_name: str
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RenameChat(GeneralChatInput):
    model_config = ConfigDict(str_strip_whitespace=True)

    chat_name: str = Field(max_length=150, min_length=3)


class Chat(BaseModel):
    chat_id: UUID
    chat_name: str
    created_at: datetime
    updated_at: datetime


class PinedChat(Chat):
    pinned_at: datetime


class Chats(BaseModel):
    pinned: PinedChat
    all_chats: Chat

    model_config = ConfigDict(from_attributes=True)
