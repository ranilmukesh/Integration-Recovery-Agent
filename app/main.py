from contextlib import asynccontextmanager

import uvicorn
from agno.os import AgentOS

from app.agent import agent, db
from app.config import settings
from app.db import run_migrations


@asynccontextmanager
async def lifespan(app):
    # Run database migrations on startup if DB configured
    try:
        if settings.NEON_DB_URL:
            run_migrations(settings.NEON_DB_URL)
    except Exception as e:
        print(f"[Warning] DB Migration during startup: {e}")
    yield


agent_os = AgentOS(
    id="integration-recovery-os",
    agents=[agent],
    db=db,
    tracing=True,
    lifespan=lifespan
)

app = agent_os.get_app()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
