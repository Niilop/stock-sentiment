# backend/api/endpoints/sentiment.py
from collections import defaultdict

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from api.endpoints.auth import get_current_user
from core.database import get_db
from models.database import BackgroundJob, SentimentAnalysis, StockNews, User
from models.schemas import (
    SentimentRunRequest,
    JobSubmitResponse,
    SentimentSummaryRequest,
    SentimentSummaryResponse,
    SentimentHistoryItem,
    SentimentBreakdown,
    WeeklyScore,
)
from services import sentiment_service, llm_service
from services.job_service import create_job, run_job

router = APIRouter(prefix="/sentiment", tags=["sentiment"])


@router.post("/run", response_model=JobSubmitResponse)
def run_sentiment(
    body: SentimentRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Score all unscored articles for the given tickers and write sentiment to DB.
    Use tickers=["*"] to process every unscored article.
    Returns a job_id you can poll at GET /jobs/{job_id}.
    """
    tickers = body.tickers

    job = create_job(db, current_user.id, "sentiment_run")
    job_id = job.id

    def task(bg_db):
        def on_progress(current: int, total: int):
            row = bg_db.get(BackgroundJob, job_id)
            if row:
                row.result = {"progress": {"current": current, "total": total}}
                bg_db.commit()

        return sentiment_service.run_for_tickers(
            tickers=tickers, db=bg_db, on_progress=on_progress
        )

    background_tasks.add_task(run_job, job_id, task)

    return JobSubmitResponse(job_id=job.id, status=job.status)


@router.post("/summary", response_model=SentimentSummaryResponse)
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

    _score_map = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}
    weekly_buckets: dict[str, list[float]] = defaultdict(list)
    for article in articles:
        if article.sentiment in _score_map:
            week_key = article.published_at.strftime("%G-W%V")
            weekly_buckets[week_key].append(_score_map[article.sentiment])
    weekly_sentiment = [
        WeeklyScore(week=k, avg_score=round(sum(v) / len(v), 3))
        for k, v in sorted(weekly_buckets.items())
    ]

    articles_text = "\n".join(lines)
    llm_summary = llm_service.analyze_sentiment_timeframe(
        ticker=ticker,
        start=body.start,
        end=body.end,
        articles_text=articles_text,
        article_count=len(articles),
    )

    record = SentimentAnalysis(
        user_id=current_user.id,
        ticker=ticker,
        start=body.start,
        end=body.end,
        articles_found=len(articles),
        sentiment_breakdown=breakdown.model_dump(),
        weekly_sentiment=[w.model_dump() for w in weekly_sentiment],
        summary=llm_summary,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return SentimentSummaryResponse.model_validate(record)


@router.get("/history", response_model=list[SentimentHistoryItem])
def get_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's past sentiment analyses, newest first."""
    return (
        db.query(SentimentAnalysis)
        .filter(SentimentAnalysis.user_id == current_user.id)
        .order_by(SentimentAnalysis.created_at.desc())
        .all()
    )


@router.get("/history/{analysis_id}", response_model=SentimentSummaryResponse)
def get_history_item(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a single saved sentiment analysis by id."""
    record = db.query(SentimentAnalysis).filter(
        SentimentAnalysis.id == analysis_id,
        SentimentAnalysis.user_id == current_user.id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return SentimentSummaryResponse.model_validate(record)


@router.delete("/history/{analysis_id}", status_code=204)
def delete_history_item(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a saved sentiment analysis by id."""
    record = db.query(SentimentAnalysis).filter(
        SentimentAnalysis.id == analysis_id,
        SentimentAnalysis.user_id == current_user.id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    db.delete(record)
    db.commit()
