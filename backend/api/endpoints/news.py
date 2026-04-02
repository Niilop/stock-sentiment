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
    SentimentSummaryRequest,
    SentimentSummaryResponse,
    SentimentBreakdown,
)
from services import scraper_service, llm_service
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


# ─── Sentiment summary for a timeframe ───────────────────────────────────────

@router.post("/sentiment-summary", response_model=SentimentSummaryResponse)
def sentiment_summary(
    body: SentimentSummaryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Pull all news for a ticker within the given timeframe, build a prompt from
    their headline / summary / sentiment labels, and return an LLM analysis.
    Articles without a sentiment score are included but marked as 'unscored'.
    """
    ticker = body.ticker.upper()

    articles = (
        db.query(StockNews)
        .filter(
            StockNews.ticker == ticker,
            StockNews.published_at >= body.start,
            StockNews.published_at <= body.end,
        )
        .order_by(StockNews.published_at.asc())
        .all()
    )

    if not articles:
        raise HTTPException(
            status_code=404,
            detail=f"No news articles found for {ticker} between {body.start.date()} and {body.end.date()}",
        )

    breakdown = SentimentBreakdown(positive=0, negative=0, neutral=0, unscored=0)
    lines: list[str] = []

    for article in articles:
        sentiment_label = article.sentiment or "unscored"
        match sentiment_label:
            case "positive":
                breakdown.positive += 1
            case "negative":
                breakdown.negative += 1
            case "neutral":
                breakdown.neutral += 1
            case _:
                breakdown.unscored += 1

        date_str = article.published_at.strftime("%Y-%m-%d")
        summary_text = article.summary.strip() if article.summary else ""
        line = f"[{date_str}] [{sentiment_label}] {article.headline}"
        if summary_text:
            line += f" — {summary_text}"
        lines.append(line)

    articles_text = "\n".join(lines)
    llm_summary = llm_service.analyze_sentiment_timeframe(
        ticker=ticker,
        start=body.start,
        end=body.end,
        articles_text=articles_text,
        article_count=len(articles),
    )

    return SentimentSummaryResponse(
        ticker=ticker,
        start=body.start,
        end=body.end,
        articles_found=len(articles),
        sentiment_breakdown=breakdown,
        summary=llm_summary,
    )


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
