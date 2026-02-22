from fastapi import FastAPI

from src.app.api.routes import router as summarize_router
from src.app.core.logging import configure_logging

configure_logging()

app = FastAPI(
    title="GitHub Repository Summarizer",
    description="Returns a human-readable summary of any public GitHub repository.",
    version="1.0.0",
)

app.include_router(summarize_router)

