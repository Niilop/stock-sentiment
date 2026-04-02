# backend/services/sentiment_service.py
import logging
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from models.database import StockNews

log = logging.getLogger(__name__)

# ── Model config ──────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MODEL_DIR = _PROJECT_ROOT / "ml_models" / "finbert"
_MODEL_NAME = "ProsusAI/finbert"
_MAX_LENGTH = 512

# Module-level singleton — loaded once, reused for every call
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification

    if not _MODEL_DIR.exists():
        log.info("Downloading %s to %s (~440 MB, one-time) …", _MODEL_NAME, _MODEL_DIR)
        tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME, use_fast=False)
        model = AutoModelForSequenceClassification.from_pretrained(_MODEL_NAME)
        _MODEL_DIR.mkdir(parents=True, exist_ok=True)
        tokenizer.save_pretrained(_MODEL_DIR)
        model.save_pretrained(_MODEL_DIR)
    else:
        log.info("Loading FinBERT from %s", _MODEL_DIR)

    tokenizer = AutoTokenizer.from_pretrained(str(_MODEL_DIR), use_fast=False)
    model = AutoModelForSequenceClassification.from_pretrained(str(_MODEL_DIR))
    _pipeline = pipeline(
        "text-classification",
        model=model,
        tokenizer=tokenizer,
        truncation=True,
        max_length=_MAX_LENGTH,
    )
    return _pipeline


def _build_text(article: StockNews) -> str:
    """Compose the text that FinBERT will classify for a single article."""
    headline = article.headline or ""
    summary = article.summary or ""
    return f"{headline}. {summary}".strip()


# ── Public API ────────────────────────────────────────────────────────────────

def score_one(article: StockNews, db: Session) -> str:
    """
    Run FinBERT on a single StockNews row, write the label back, and commit.

    Designed to be called directly from the live stream handler immediately
    after a new article is saved, so sentiment is stored in real time.

    Returns the sentiment label ('positive', 'negative', or 'neutral').
    """
    pipe = _get_pipeline()
    text = _build_text(article)
    result = pipe(text)[0]
    label: str = result["label"].lower()

    article.sentiment = label
    db.commit()
    log.debug("Scored article %s → %s", article.alpaca_id, label)
    return label


def run_for_tickers(
    tickers: list[str],
    db: Session,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """
    Score all unscored articles for the given tickers and write results to DB.

    Pass tickers=["*"] to process every unscored article regardless of ticker.

    Returns a summary dict::
        {
            "processed": int,
            "skipped": int,          # already had a sentiment
            "tickers": {"AAPL": {"processed": N, "skipped": M}, ...}
        }
    """
    pipe = _get_pipeline()

    query = db.query(StockNews).filter(StockNews.sentiment.is_(None))

    wildcard = tickers == ["*"]
    if not wildcard:
        upper = [t.upper() for t in tickers]
        query = query.filter(StockNews.ticker.in_(upper))

    articles = query.order_by(StockNews.published_at.desc()).all()
    total = len(articles)

    summary: dict = {"processed": 0, "skipped": 0, "tickers": {}}

    for i, article in enumerate(articles, 1):
        ticker = article.ticker
        bucket = summary["tickers"].setdefault(ticker, {"processed": 0, "skipped": 0})

        text = _build_text(article)
        result = pipe(text)[0]
        label: str = result["label"].lower()

        article.sentiment = label
        db.commit()
        bucket["processed"] += 1
        summary["processed"] += 1

        if on_progress:
            on_progress(i, total)

    return summary
