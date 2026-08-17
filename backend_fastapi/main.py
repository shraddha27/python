import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env")

from backend_fastapi.ai import ai_router, workflow_router
from backend_fastapi.auth import auth_router
from backend_fastapi.startup import startup_event
from backend_fastapi.tasks import tasks_router
from backend_fastapi.agents.routes import router as agents_router
from backend_fastapi.routes_mcp import router as mcp_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_event()
    yield

app = FastAPI(title="Task API with Auth", version="2.0", lifespan=lifespan)

cors_allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:4200").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def _startup_event() -> None:
    startup_event()

app.include_router(auth_router)
app.include_router(tasks_router)
app.include_router(ai_router)
app.include_router(workflow_router)
app.include_router(agents_router)
app.include_router(mcp_router)

__all__ = ["app"]
