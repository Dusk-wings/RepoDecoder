from app.core.config import env_config
from supabase import Client, create_client

supabase_client: Client = create_client(
    supabase_url=env_config.SUPABASE_URL if env_config.SUPABASE_URL else "",
    supabase_key=env_config.SUPABASE_KEY if env_config.SUPABASE_KEY else "",
)

