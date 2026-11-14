from fastapi import APIRouter, Depends, Request, HTTPException, status, Path
from fastapi.responses import StreamingResponse

from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import json
import asyncio

from app.schemas.user import UserDetails
from app.schemas.chat import EditChat, StartChat
from app.schemas.response import StandardResponse

from app.api.deps import get_current_user
from app.core.db import get_database

from app.services.chat_service import ChatService
from app.services.chat_room_service import ChatRoomService

router = APIRouter(prefix="/chat", tags=["Chat"])

UserDepends = Annotated[UserDetails, Depends(get_current_user)]
DbDepends = Annotated[AsyncSession, Depends(get_database)]


def get_chat_service(request: Request, db: DbDepends):
    return ChatService(
        db=db,
        bucket_client=request.app.state.bucket_client,
        generator=request.app.state.generator,
        embedder=request.app.state.embedder,
        retriver=request.app.state.retriver,
        redis=request.app.state.redis_client,
        tokenizer=request.app.state.encoder,
    )


def get_chat_room_service(db: DbDepends):
    return ChatRoomService(db=db)


async def watch_disconnect(request: Request, cancel_event: asyncio.Event):
    while not request.is_disconnected():
        await asyncio.sleep(0.1)

    cancel_event.set()


async def generate_response(
    chat_service: ChatService,
    room_service: ChatRoomService | None,
    user: UserDepends,
    repo_id: uuid.UUID | None,
    chat_id: uuid.UUID | None,
    query: str,
    cancel_event: asyncio.Event,
    request: Request,
    is_anonymous: bool = False,
    conversation_id: uuid.UUID | None = None,
):
    if not repo_id and not chat_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="THE REQUEST IS NOT DEFIEND AS EITHER NEW OR OLD CHAT",
        )

    if repo_id is not None:
        if chat_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="FOR A NEW CHAT, CHAT-ID CAN'T EXIST",
            )

        if not room_service:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="INTERNAL SERVER ERROR",
            )

        room_data = await room_service.create_chat_room(
            user_id=user.user_id,
            repo_id=repo_id,
            is_anonymous=user.is_anonymous,
            first_msg=query,
        )

        if room_data["success"] == True:
            data = room_data["data"]
            chat_id = data.get("chat_id", None)

            creation_response = {
                "type": "metadata",
                "status": "success",
                "status_code": 200,
                "content": data or None,
            }

            yield json.dumps(creation_response)

        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="INTERNAL SERVER ERROR",
            )

    if not chat_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="CHAT-ID IS REQUIRED",
        )

    watcher = asyncio.create_task(
        watch_disconnect(request=request, cancel_event=cancel_event)
    )

    try:
        async for chunk in chat_service.chat(
            query=query,
            chat_id=chat_id,
            user_id=user.user_id,
            stop_event=cancel_event,
            conversation_id=conversation_id,
            is_anonymous=is_anonymous,
        ):
            yield str(chunk)
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


@router.post("/completion")
async def start_chat(
    user: UserDepends,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    room_service: Annotated[ChatRoomService, Depends(get_chat_room_service)],
    body: StartChat,
    request: Request,
):
    
    cancel_event = asyncio.Event()

    return StreamingResponse(
        generate_response(
            chat_service=chat_service,
            room_service=room_service,
            user=user,
            repo_id=body.repo_id,
            chat_id=body.chat_id,
            query=body.query,
            cancel_event=cancel_event,
            request=request,
            is_anonymous=user.is_anonymous,
        ),
        media_type="text/event-stream",
    )


@router.put("/update-completion")
async def edit_chat(
    body: EditChat,
    user: UserDepends,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    request: Request,
):
    cancel_event = asyncio.Event()

    return StreamingResponse(
        generate_response(
            chat_service=chat_service,
            room_service=None,
            user=user,
            repo_id=None,
            chat_id=body.chat_id,
            query=body.query,
            cancel_event=cancel_event,
            request=request,
            conversation_id=body.conversation_id,
            is_anonymous=user.is_anonymous,
        ),
        media_type="text/event-stream",
    )


@router.get("/load/{chat_id}/{page}", response_model=StandardResponse[None])
async def load_chats(
    user: UserDepends,
    chat_id: Annotated[
        uuid.UUID, Path(title="Chat ID for which the conversations needed to be loaded")
    ],
    page: Annotated[int, Path(title="Page Number to load", min=1)],
    service: Annotated[ChatService, Depends(get_chat_service)],
):
    LIMIT = 10
    OFFSET = (page - 1) * LIMIT

    result = await service.load_conversation(
        user_id=user.user_id, chat_id=chat_id, limit=LIMIT, offset=OFFSET
    )

    if result["success"]:
        return {
            "data": result["data"],
            "status": result["status"],
            "message": result["message"],
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL SERVER ERROR",
        )
