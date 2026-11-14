from redis.asyncio import Redis
from app.core.config import env_config

redis_client = Redis.from_url(
    env_config.REDIS_URL or "",
    decode_responses=True,
    max_connections=10,
    socket_timeout=5,
    socket_connect_timeout=5,
)

async def close_redis():
    await redis_client.aclose()
