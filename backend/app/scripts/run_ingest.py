import os
import asyncio
import uuid
from app.services.ingest.ingest_service import Ingest


async def main(url: str, id: str):
    user_id = uuid.UUID(id)
    ingester = Ingest(github_url=url, user_id=user_id)
    await ingester.ingest_repo()


if __name__ == "__main__":
    github_url = os.getenv("GITHUB_URL")
    user_id = os.getenv("USER_ID")

    if not github_url:
        raise ValueError("[INGEST] THE GITHUB URL IS NOT DEFINED")

    if not user_id:
        raise ValueError("[INGEST] USER_ID IS NOT DEFINED")

    asyncio.run(main(url=github_url or "", id=user_id or ""))
