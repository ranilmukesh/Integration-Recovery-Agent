import os
from contextlib import asynccontextmanager

import uvicorn
from agno.os import AgentOS
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput

from app.agent import db, recovery_team
from app.config import settings
from app.db import run_migrations
from app.semantica_integration import shared_context


# Patch Agno RunOutput/TeamRunOutput to support string status serialization in Agno OS routers
class _StatusWrapper(str):
    @property
    def value(self):
        return str(self)


def _patch_model_status(model_cls):
    orig_getattr = model_cls.__getattribute__

    def custom_getattr(self, name):
        val = orig_getattr(self, name)
        if name == "status" and val is not None and not hasattr(val, "value"):
            return _StatusWrapper(val)
        return val

    model_cls.__getattribute__ = custom_getattr


_patch_model_status(TeamRunOutput)
_patch_model_status(RunOutput)

# 1. Define custom routes on a base FastAPI app per AgentOS best practices
base_app = FastAPI(title="B2B Payment Recovery API")


@base_app.get("/api/compliance/graph")
async def get_semantica_knowledge_graph():
    """Retrieve full Semantica Knowledge Graph representation for visual explorer dashboards."""
    graph_dict = shared_context.kg.to_dict()
    return JSONResponse(content={
        "status": "success",
        "nodes_count": len(graph_dict.get("nodes", [])),
        "edges_count": len(graph_dict.get("edges", [])),
        "graph": graph_dict,
    })


@base_app.get("/api/compliance/export")
async def export_prov_o_compliance_report(output_filename: str = "compliance_audit.ttl"):
    """Export W3C PROV-O RDF Turtle file for financial auditors."""
    res = shared_context.export_compliance_report(output_path=output_filename, format="turtle")
    if res.get("success") and os.path.exists(output_filename):
        return FileResponse(
            path=output_filename,
            media_type="text/turtle",
            filename=output_filename
        )
    return JSONResponse(status_code=500, content=res)


@base_app.get("/api/compliance/precedents")
async def get_schema_drift_precedents(scenario: str = Query(..., description="Partner schema drift scenario")):
    """Query precedent decisions recorded in the Semantica Knowledge Graph."""
    precedents = shared_context.find_precedents(scenario)
    return JSONResponse(content={
        "scenario": scenario,
        "count": len(precedents),
        "precedents": precedents,
    })


@asynccontextmanager
async def lifespan(app):
    # Run database migrations on startup if DB configured
    try:
        if settings.NEON_DB_URL:
            run_migrations(settings.NEON_DB_URL)
    except Exception as e:
        print(f"[Warning] DB Migration during startup: {e}")
    yield


# 2. Pass base_app to AgentOS with explicit route conflict handling
agent_os = AgentOS(
    id="integration-recovery-os",
    teams=[recovery_team],
    db=db,
    tracing=True,
    base_app=base_app,
    lifespan=lifespan,
    on_route_conflict="preserve_base_app",
)

app = agent_os.get_app()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)