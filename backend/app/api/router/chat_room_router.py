from fastapi import APIRouter, Depends, HTTPException, status, Path

from app.schemas.response import StandardResponse
from app.schemas.user import UserDetails

from app.api.deps import get_current_user
from app.core.db import get_database
from app.services.chat_room_service import ChatRoomService
from app.schemas.chat_room import (
    GeneralChatInput,
    ChatRoomOutput,
    RenameChat,
    Chats,
    PinedChat,
    Chat,
)

from typing import Annotated
from uuid import UUID
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/chat-room", tags=["ChatRoom"])

UserDepends = Annotated[UserDetails, Depends(get_current_user)]
DbDepends = Annotated[AsyncSession, Depends(get_database)]


class LoadMore(Enum):
    PINNED = "pinned"
    UNPINNED = "un-pinned"


def get_chat_room_service(db: DbDepends) -> ChatRoomService:
    return ChatRoomService(db)


@router.put("/edit-name", response_model=StandardResponse[ChatRoomOutput])
async def edit_chat_name(
    user: UserDepends,
    body: RenameChat,
    chat_service: Annotated[ChatRoomService, Depends(get_chat_room_service)],
):
    result = await chat_service.rename_chat_room(
        user_id=user.user_id,
        chat_id=body.chat_id,
        name=body.chat_name,
        is_named_by_user=True,
    )

    if result["success"] == True:
        return {
            "status": result["status"],
            "message": result["message"],
            "data": result["data"],
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL SERVER ERROR",
        )


@router.delete("/delete/{chat_id}", response_model=StandardResponse[None])
async def delete_chat_room(
    user: UserDepends,
    chat_id: Annotated[
        UUID, Path(title="Chat ID used to identify which chat to delete")
    ],
    chat_service: Annotated[ChatRoomService, Depends(get_chat_room_service)],
):
    result = await chat_service.delete_chat_room(user_id=user.user_id, chat_id=chat_id)

    if result["success"] == True:
        return {
            "status": result["status"],
            "message": result["message"],
            "data": result["data"],
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL SERVER ERROR",
        )


@router.get("/load/{repo_id}", response_model=StandardResponse[Chats])
async def load_chat_rooms(
    user: UserDepends,
    repo_id: Annotated[
        UUID, Path(title="Repo ID for which the chat rooms are to be loaded")
    ],
    service: Annotated[ChatRoomService, Depends(get_chat_room_service)],
):

    pinned_chat = await service.load_pinned_chat_room(
        user_id=user.user_id, repo_id=repo_id
    )

    unpinned_chat = await service.load_all_chat_room_repo(
        user_id=user.user_id, repo_id=repo_id
    )

    if pinned_chat["success"] and unpinned_chat["success"]:

        data = {"pinned": pinned_chat, "all_chats": unpinned_chat}
        return {"status": 200, "message": "CHATS LOADED", "data": data}

    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL SERVER ERROR",
        )


@router.get(
    "/load-more/{what}/{repo_id}/{page}",
    response_model=StandardResponse[Chat | PinedChat],
)
async def load_more_chats(
    user: UserDepends,
    what: Annotated[LoadMore, Path(title="what to load more pinned or unpinned chats")],
    repo_id: Annotated[
        UUID, Path(title="Repo ID for which the chat rooms are to be loaded")
    ],
    page: Annotated[int, Path(title="Page number", min=2)],
    service: Annotated[ChatRoomService, Depends(get_chat_room_service)],
):
    data = None

    PIN_LIMIT = 5
    UN_PIN_LIMIT = 10

    if what == "pinned":
        offset = (page - 1) * PIN_LIMIT
        chats = await service.load_pinned_chat_room(
            user_id=user.user_id, repo_id=repo_id, limit=PIN_LIMIT, offset=offset
        )

        if chats["success"] == True:
            data = chats["data"]

    elif what == "un-pinned":
        offset = (page - 1) * UN_PIN_LIMIT
        chats = await service.load_all_chat_room_repo(
            user_id=user.user_id, repo_id=repo_id, limit=UN_PIN_LIMIT, offset=offset
        )

        if chats["success"] == True:
            data = chats["data"]

    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="UNEXPTECTED `what` RECIVED",
        )

    if data is None:
        return {"status": 200, "message": "DATA LOADED", "data": data}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL SERVER ERROR",
        )

@router.post("/pin/{chat_id}", response_model=StandardResponse[None])
async def pin_chat_room(
    user: UserDepends,
    chat_id: Annotated[
        UUID, Path(title="Chat ID used to identify which chat to pin")
    ],
    service: Annotated[ChatRoomService, Depends(get_chat_room_service)],
):
    result = await service.pin_chat_room(user_id=user.user_id, chat_id=chat_id)

    if result["success"] == True:
        return {
            "status": result["status"],
            "message": result["message"],
            "data": result["data"],
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL SERVER ERROR",
        )