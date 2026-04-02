"""
FinBERT sentiment test against real DB data.

Fetches 50 rows from stock_news, runs FinBERT, and prints timing stats.

Usage (from the project root):
    python tests/finbert_test.py

Dependencies:
    pip install transformers torch
    # CPU-only torch:
    # pip install torch --index-url https://download.pytorch.org/whl/cpu

Model is cached at <project_root>/ml_models/finbert/ after the first run.
"""

import sys
import time
from pathlib import Path

# Allow imports from the backend/ package root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
from core.database import SessionLocal
from models.database import StockNews

# ── Paths ─────────────────────────────────────────────────────────────────────
MODEL_DIR = PROJECT_ROOT / "ml_models" / "finbert"
MODEL_NAME = "ProsusAI/finbert"
MAX_LENGTH = 512
SAMPLE_SIZE = 50


# ── Model helpers ─────────────────────────────────────────────────────────────

def _ensure_model() -> Path:
    if not MODEL_DIR.exists():
        print(f"Downloading {MODEL_NAME} to {MODEL_DIR}  (~440 MB, one-time) …")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, use_fast=False)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        tokenizer.save_pretrained(MODEL_DIR)
        model.save_pretrained(MODEL_DIR)
        print("Saved.\n")
    else:
        print(f"Loading model from {MODEL_DIR}\n")
    return MODEL_DIR


# ── DB helpers ────────────────────────────────────────────────────────────────

def fetch_articles(n: int) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(StockNews.ticker, StockNews.headline, StockNews.summary)
            .order_by(StockNews.published_at.desc())
            .limit(n)
            .all()
        )
        return [
            {"ticker": r.ticker, "headline": r.headline, "summary": r.summary or ""}
            for r in rows
        ]
    finally:
        db.close()


def build_text(item: dict) -> str:
    return f"{item['headline']}. {item['summary']}".strip()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Fetching {SAMPLE_SIZE} articles from database …")
    articles = fetch_articles(SAMPLE_SIZE)
    if not articles:
        print("No articles found. Run the news scraper first.")
        return
    print(f"Got {len(articles)} articles.\n")

    model_path = _ensure_model()
    load_start = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), use_fast=False)
    model = AutoModelForSequenceClassification.from_pretrained(str(model_path))
    sentiment = pipeline(
        "text-classification",
        model=model,
        tokenizer=tokenizer,
        truncation=True,
        max_length=MAX_LENGTH,
    )
    load_elapsed = time.perf_counter() - load_start
    print(f"Model loaded in {load_elapsed:.2f}s\n")

    print(f"{'#':<4}  {'Ticker':<6}  {'Label':<9}  {'Score':>6}  {'Time':>7}  Headline")
    print("-" * 100)

    total_start = time.perf_counter()
    times = []

    for i, item in enumerate(articles, start=1):
        text = build_text(item)
        t0 = time.perf_counter()
        result = sentiment(text)[0]
        elapsed = time.perf_counter() - t0
        times.append(elapsed)

        label = result["label"].lower()
        score = result["score"]
        headline_preview = item["headline"][:60]

        print(
            f"{i:<4}  {item['ticker']:<6}  {label:<9}  {score:>6.3f}  "
            f"{elapsed*1000:>5.0f}ms  {headline_preview}"
        )

    total_elapsed = time.perf_counter() - total_start
    print("-" * 100)
    print(f"\nArticles processed : {len(articles)}")
    print(f"Total inference    : {total_elapsed*1000:.0f}ms")
    print(f"Average per item   : {total_elapsed/len(articles)*1000:.0f}ms")
    print(f"Min / Max          : {min(times)*1000:.0f}ms / {max(times)*1000:.0f}ms")


if __name__ == "__main__":
    main()
