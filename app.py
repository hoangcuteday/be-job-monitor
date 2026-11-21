"""Read-only HTTP API over the monitor's SQLite database.

Runs as a second process against the same jobs.db the monitor writes to
(WAL mode allows concurrent readers); it never writes. Same pattern as the
`jobs status`/`jobs recent` CLI commands, which already run alongside the
monitor.
"""

from fastapi import FastAPI, HTTPException, Query

from job_monitor.config import Settings
from job_monitor.database import Database
from job_monitor.dates import parse_timestamp, stamp, utcnow
from job_monitor.models import CHANNELS, FEEDS

settings = Settings.from_env()
db = Database(settings.database_path)
app = FastAPI(
    title="Job Monitor API",
    description="Read-only queries over the monitor's job database, in the same shape "
    "the Discord alerts use (company, title, location, publication evidence, sponsorship).",
    version="1.0.0",
)


@app.get("/healthz", tags=["ops"], summary="Liveness check")
async def healthz():
    return {"ok": True, "now": stamp(utcnow())}


@app.get("/status", tags=["ops"], summary="Monitor status (same as `jobs status --json`)")
async def status():
    # async: sqlite3 connections are thread-affine, and FastAPI runs sync `def`
    # endpoints in a worker thread pool, not the thread that opened `db`.
    return db.status(settings, utcnow())


@app.get("/jobs/recent", tags=["jobs"], summary="Verified recent publications (same as `jobs recent --json`)")
async def jobs_recent(
    feed: str = Query("full-time", description=f"One of: {', '.join(FEEDS)}"),
    hours: float = Query(24, gt=0, le=24, description="Rolling window in hours, (0, 24]"),
    all: bool = Query(False, description="Include relevance-excluded jobs, not just matching ones"),
):
    """Active jobs whose authoritative original publication falls in the last `hours`."""
    if feed not in FEEDS:
        raise HTTPException(400, f"Unknown feed; choose one of {list(FEEDS)}")
    now = utcnow()
    rows = db.recent(hours, now, not all, FEEDS[feed])
    for row in rows:
        row["posting_age_seconds"] = (now - parse_timestamp(row["published_at"])).total_seconds()
        row["classification"] = Database.category(row, now)
    return rows


@app.get("/jobs/open", tags=["jobs"], summary="Matching jobs not yet sent or queued to Discord")
async def jobs_open(feed: str = Query("full-time", description=f"One of: {', '.join(CHANNELS)}")):
    """Matching jobs on enabled boards this feed hasn't sent or queued yet, newest first."""
    if feed not in CHANNELS:
        raise HTTPException(400, f"Unknown feed; choose one of {list(CHANNELS)}")
    return db.open_jobs(CHANNELS[feed])
