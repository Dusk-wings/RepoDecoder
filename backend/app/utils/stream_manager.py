import asyncio
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, status


class StreamManager:
    def __init__(self) -> None:
        self.stream = {}

    def create_stream(self, user_id: str | None, session_id: str | None):
        cancel_event = asyncio.Event()
        stream_id = str(uuid.uuid4())

        self.stream[stream_id] = {
            "user_id": user_id,
            "session_id": session_id,
            "cancel_event": cancel_event,
            "created_at": datetime.now(timezone.utc),
        }
        return stream_id

    def _get_stream(self, stream_id: str, user_id: str | None, session_id: str | None):
        stream = self.stream[stream_id]

        if not stream_id:
            return None

        if user_id and stream.get("user_id") == user_id:
            return stream

        if session_id and stream.get("session_id") == session_id:
            return stream

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="UNAUTHORIZED USER"
        )

    def cancel_stream(
        self, stream_id: str, user_id: str | None, session_id: str | None
    ):
        stream = self._get_stream(stream_id, user_id, session_id)
        if stream:
            stream.get("cancel_event").set()
            return True

        return False

    def clean_up_stream(self, stream_id: str):
        if stream_id in self.stream:
            del self.stream[stream_id]

    async def timebond_cleanup(self, max_age_min: int = 60):
        while True:
            await asyncio.sleep(600)
            current_time = datetime.now(timezone.utc)
            expired = [
                sid
                for sid, stream in self.stream.items()
                if (current_time - stream["created_at"]).total_seconds()
                > max_age_min * 60
            ]
            for sid in expired:
                self.clean_up_stream(sid)
