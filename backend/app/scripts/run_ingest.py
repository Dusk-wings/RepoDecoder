import os
import asyncio
from app.services.ingest.ingest_service import Ingest


async def main(url: str):
    ingester = Ingest(github_url=url)
    await ingester.ingest_repo()


if __name__ == "__main__":
    github_url = os.getenv("GITHUB_URL")
    if not github_url:
        raise ValueError("[INGEST] THE GITHUB URL IS NOT DEFINED")
    asyncio.run(main(url=github_url or ""))
