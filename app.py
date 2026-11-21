"""Read-only HTTP API over the monitor's SQLite database.

Self-contained (stdlib sqlite3 only, no dependency on the job_monitor
package) so it can live in its own deploy repo/container, reading the same
jobs.db the monitor writes to over a read-only bind mount.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", "/app/data/jobs.db"))
FEEDS = {
    "full-time": "full_time",
    "internships": "internship",
    "offseason-internships": "offseason_internship",
}

app = FastAPI(
    title="Job Monitor API",
    description="Read-only queries over the monitor's job database, in the same shape "
    "the Discord alerts use (company, title, location, publication evidence, sponsorship).",
    version="1.0.0",
)

# Read-only, unauthenticated, no cookies involved — safe to expose to any origin
# so the static frontend (served from S3/any domain) can call this API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def query(sql: str, params: tuple = ()) -> list[dict]:
    connection = sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


@app.get("/healthz", tags=["ops"], summary="Liveness check")
async def healthz():
    return {
        "ok": True,
        "now": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
    }


@app.get(
    "/jobs/recent",
    tags=["jobs"],
    summary="Verified recent publications (same as `jobs recent --json`)",
)
async def jobs_recent(
    feed: str = Query("full-time", description=f"One of: {', '.join(FEEDS)}"),
    hours: float = Query(
        24, gt=0, le=24, description="Rolling window in hours, (0, 24]"
    ),
    all: bool = Query(
        False, description="Include relevance-excluded jobs, not just matching ones"
    ),
):
    """Active jobs whose authoritative original publication falls in the last `hours`.

    Every row here has publication_date_confidence='ORIGINAL' and published_at inside
    the window by construction, so its classification is always "VERIFIED_RECENT".
    """
    if feed not in FEEDS:
        raise HTTPException(400, f"Unknown feed; choose one of {list(FEEDS)}")
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=hours)).isoformat(timespec="microseconds")
    rows = query(
        """SELECT j.*, c.last_successful_check FROM job_postings j JOIN companies c USING(company_key)
           WHERE j.is_active=1 AND c.enabled=1 AND publication_date_confidence='ORIGINAL'
           AND published_at>=? AND published_at<=? AND (?=0 OR included=1) AND j.audience=?
           ORDER BY published_at DESC""",
        (
            window_start,
            now.isoformat(timespec="microseconds"),
            int(not all),
            FEEDS[feed],
        ),
    )
    for row in rows:
        row["posting_age_seconds"] = (
            now - datetime.fromisoformat(row["published_at"])
        ).total_seconds()
        row["classification"] = "VERIFIED_RECENT"
    return rows
