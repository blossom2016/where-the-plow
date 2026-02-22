# src/where_the_plow/main.py
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from where_the_plow import collector
from where_the_plow.config import settings
from where_the_plow.db import Database
from where_the_plow.routes import router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.db_path)
    db.init()
    app.state.db = db
    app.state.store = {}
    logger.info("Database initialized at %s", settings.db_path)

    task = asyncio.create_task(collector.run(db, app.state.store))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    db.close()
    logger.info("Shutdown complete")


app = FastAPI(
    title="where the plow",
    description="Real-time and historical plow tracker for the City of St. John's. "
    "All geo endpoints return GeoJSON FeatureCollections with cursor-based pagination.\n\n"
    "**WARNING:** This API is not stable. Monitor the `openapi.json` file for breaking changes. "
    "Version 0.1.0 will remain until the API can be considered stable — and even then, "
    "it likely won't hit stable unless someone asks nicely. If you would like a stable API, "
    "shoot [jackharrhy.dev](https://jackharrhy.dev) an email.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health", tags=["system"])
def health():
    db: Database = app.state.db
    stats = db.get_stats()
    return {"status": "ok", **stats}
