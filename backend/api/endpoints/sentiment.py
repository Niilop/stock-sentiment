# backend/api/endpoints/sentiment.py
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from api.endpoints.auth import get_current_user
from core.database import get_db
from models.database import BackgroundJob, User
from models.schemas import SentimentRunRequest, JobSubmitResponse
from services import sentiment_service
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
