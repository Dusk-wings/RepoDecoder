from fastapi import FastAPI
from app.core.config import env_config
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime

app = FastAPI()

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
