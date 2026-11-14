from redis.asyncio import Redis
from app.rag.generator.generator import Generator
from enum import Enum
from typing import cast
from datetime import timedelta


class ModelType(str, Enum):
    ACTIVE = "current_active"
    ANON_ACTIVE = "anonymous_active"
    TITLE_ACTIVE = "title_active"


class ModelFallbackService:
    def __init__(self, redis: Redis, generator: Generator) -> None:
        self.redis_client = redis
        self.priority = generator.list_models()

    async def get_model_status(self, model_name: str, is_title: bool = False) -> bool:
        if is_title:
            initials = "circuit_breaker_title"
        else:
            initials = "circuit_breaker"

        is_rate_limited = await self.redis_client.get(name=f"{initials}:{model_name}")
        return bool(is_rate_limited)

    async def down_a_model(
        self, model_name: str, second: float = 360, is_title: bool = False
    ):
        if is_title:
            initials = "circuit_breaker_title"
        else:
            initials = "circuit_breaker"

        await self.redis_client.setex(
            name=f"{initials}:{model_name}",
            time=timedelta(seconds=second),
            value="1",
        )

    async def set_active_model(self, model_name: str, model_type: ModelType):
        await self.redis_client.set(name=f"{model_type}:current", value=model_name)

    async def get_active_model(self, model_type: str) -> str | None:
        current = cast(
            str | None, await self.redis_client.get(name=f"{model_type}:current")
        )
        return current

    def next_model(
        self, count: int, is_anonymous: bool = False, is_title: bool = False
    ) -> str | None:
        if is_title:
            search_space = [
                model for model in self.priority if model.startswith("groq/")
            ][::-1][count:]
        else:
            start = 0
            if is_anonymous:
                start = next(
                    (
                        i
                        for i, model in enumerate(self.priority)
                        if model.startswith("groq/")
                    ),
                    len(self.priority),
                )

            search_space = self.priority[start + count :]

        for model in search_space:
            if not self.get_model_status(model):
                return model

        return None
