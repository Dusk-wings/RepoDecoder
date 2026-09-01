from core.config import env_config
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

DATABASE_URL = env_config.DATABASE_URL or ""
engine = create_async_engine(url=DATABASE_URL, echo=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession
)

Base = declarative_base()


async def get_database():
    async with AsyncSessionLocal() as session:
        yield session
