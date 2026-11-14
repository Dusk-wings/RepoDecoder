from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
from contextlib import asynccontextmanager
import tiktoken

from app.core.config import env_config
from app.core.supabase import get_supabase_async_client, close_supabase_async_client
from app.core.redis import redis_client, close_redis

from app.rag.embedder.embedder import Embedder
from app.rag.retrival.retrival import Retrival
from app.rag.generator.generator import Generator

from app.api.router.workflow_router import router as workflow_router
from app.api.router.chat_router import router as chat_router
from app.api.router.chat_room_router import router as chat_room_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bucket_client = await get_supabase_async_client()
    app.state.generator = Generator()
    app.state.embedder = Embedder()
    app.state.retriver = Retrival()
    app.state.redis_client = redis_client
    app.state.encoder = {"cl100k_base": tiktoken.get_encoding("cl100k_base")}

    try:
        await app.state.redis_client.ping()
        yield
    finally:
        app.state.bucket_client = None
        app.state.generator = None
        app.state.embedder = None
        app.state.retriever = None
        app.state.redis_client = None
        app.state.encoder.clear()

        await close_supabase_async_client()
        await close_redis()


app = FastAPI(lifespan=lifespan)

allowed_origins = []
if env_config.ALLOWED_ORIGIN:
    allowed_origins = env_config.ALLOWED_ORIGIN.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/server-status", tags=["Server Status"])
async def validate_user():
    return JSONResponse(
        status_code=200,
        content={"message": "Hello, From the server", "time": f"{datetime.now()}"},
    )


app.include_router(workflow_router)
app.include_router(chat_router)
app.include_router(chat_room_router)
