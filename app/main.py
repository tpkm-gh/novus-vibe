"""FastAPI surface for the Fund Screen PDF Copilot prototype.

Run with:  uvicorn app.main:app --reload --port 8000
Then open  http://localhost:8000/

Both agents are constructed once (module-level) and reused across requests;
they hold no per-request state themselves -- everything that needs to
persist across a request lives in Postgres via app/repository.py.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import repository
from .agents import ControllerAgent, DocGenAgent
from .db import get_session, init_db
from .schemas import DashboardStats, ScreenRequestCreate, ScreenRequestDetail, ScreenRequestSummary


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Fund Screen PDF Copilot (prototype)", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

docgen_agent = DocGenAgent()
controller_agent = ControllerAgent()


def db_session():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.post("/api/screen-requests", response_model=ScreenRequestDetail)
def create_screen_request(payload: ScreenRequestCreate, db: Session = Depends(db_session)):
    record = repository.create_request(db, label=payload.label, source_url=str(payload.source_url))
    record = docgen_agent.run(db, record)
    detail = controller_agent.get_detail(db, record.id)
    return detail


@app.get("/api/screen-requests", response_model=list[ScreenRequestSummary])
def list_screen_requests(db: Session = Depends(db_session)):
    return controller_agent.list_summaries(db)


@app.get("/api/screen-requests/{request_id}", response_model=ScreenRequestDetail)
def get_screen_request(request_id: str, db: Session = Depends(db_session)):
    detail = controller_agent.get_detail(db, request_id)
    if detail is None:
        raise HTTPException(404, f"No request {request_id}")
    return detail


@app.get("/api/screen-requests/{request_id}/download")
def download_screen_request(request_id: str, db: Session = Depends(db_session)):
    record = repository.get_request(db, request_id)
    if record is None:
        raise HTTPException(404, f"No request {request_id}")
    pdf_bytes = docgen_agent.retrieve(record)
    if pdf_bytes is None:
        raise HTTPException(404, "No stored document for this request (generation may have failed)")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{request_id}.pdf"'},
    )


@app.get("/api/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(db_session)):
    return controller_agent.get_stats(db)
