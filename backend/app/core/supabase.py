from app.core.config import env_config
from supabase import Client, create_client, AsyncClient, create_async_client

supabase_client: Client = create_client(
    supabase_url=env_config.SUPABASE_URL or "",
    supabase_key=env_config.SUPABASE_KEY or "",
)

_client: AsyncClient | None = None

async def get_supabase_async_client():
    global _client
    if _client is None:
        _client = await create_async_client(
            supabase_url=env_config.SUPABASE_URL or "",
            supabase_key=env_config.SUPABASE_KEY or "",
    )

    return _client

async def close_supabase_async_client():
    global _client
    _client = None