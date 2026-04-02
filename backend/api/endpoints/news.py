# backend/api/endpoints/news.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from api.endpoints.auth import get_current_user
from core.config import get_settings
from core.database import get_db, SessionLocal
from models.database import StockNews, User
from models.schemas import (
    NewsFetchRequest,
    NewsStreamRequest,
    NewsStreamResponse,
    NewsStreamStopRequest,
    NewsArticleResponse,
    JobSubmitResponse,
)
from services import scraper_service
from services.job_service import create_job, run_job

router = APIRouter(prefix="/news", tags=["news"])


def _get_keys():
    settings = get_settings()
    api_key = settings.alpaca_api_key.get_secret_value()
    secret_key = settings.alpaca_secret_key.get_secret_value()
    if not api_key or not secret_key:
        raise HTTPException(
            status_code=503,
            detail="Alpaca API keys not configured. Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env",
        )
    return api_key, secret_key


# ─── Historical fetch ─────────────────────────────────────────────────────────

@router.post("/fetch", response_model=JobSubmitResponse)
def fetch_news(
    body: NewsFetchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Trigger a one-time historical news download for the given tickers.
    Tickers are processed one at a time to respect API rate limits.
    Returns a job_id you can poll at GET /jobs/{job_id}.
    """
    api_key, secret_key = _get_keys()
    tickers = [t.upper() for t in body.tickers]
    start = body.start

    job = create_job(db, current_user.id, "news_fetch")

    background_tasks.add_task(
        run_job,
        job.id,
        lambda bg_db: scraper_service.fetch_historical_news(
            tickers=tickers,
            db=bg_db,
            api_key=api_key,
            secret_key=secret_key,
            start=start,
        ),
    )

    return JobSubmitResponse(job_id=job.id, status=job.status)


# ─── Streaming ────────────────────────────────────────────────────────────────

@router.post("/stream/start", response_model=NewsStreamResponse)
def stream_start(
    body: NewsStreamRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Start a real-time news stream for the given tickers.
    Incoming articles are automatically inserted into the database.
    """
    api_key, secret_key = _get_keys()
    upper_tickers = [t.upper() for t in body.tickers]
    stream_key = scraper_service.start_news_stream(
        tickers=upper_tickers,
        db_factory=SessionLocal,
        api_key=api_key,
        secret_key=secret_key,
    )
    return NewsStreamResponse(stream_key=stream_key, tickers=upper_tickers, status="running")


@router.post("/stream/stop", response_model=NewsStreamResponse)
def stream_stop(
    body: NewsStreamStopRequest,
    current_user: User = Depends(get_current_user),
):
    """Stop a running news stream by its stream_key."""
    stopped = scraper_service.stop_news_stream(body.stream_key)
    if not stopped:
        raise HTTPException(status_code=404, detail=f"No active stream found for key '{body.stream_key}'")
    tickers = body.stream_key.split(",")
    return NewsStreamResponse(stream_key=body.stream_key, tickers=tickers, status="stopped")


@router.get("/stream", response_model=list[str])
def stream_list(current_user: User = Depends(get_current_user)):
    """List stream keys of all currently active streams."""
    return scraper_service.list_active_streams()


# ─── Available tickers ───────────────────────────────────────────────────────

@router.get("/tickers", response_model=list[str])
def get_tickers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all distinct ticker symbols that have stored news articles."""
    rows = db.query(StockNews.ticker).distinct().order_by(StockNews.ticker).all()
    return [r.ticker for r in rows]



@router.get("/", response_model=list[NewsArticleResponse])
def get_news(
    ticker: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve stored news articles, newest first.
    Optionally filter by ticker symbol.
    """
    query = db.query(StockNews).order_by(StockNews.published_at.desc())
    if ticker:
        query = query.filter(StockNews.ticker == ticker.upper())
    return query.offset(offset).limit(limit).all()
