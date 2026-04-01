# backend/services/scraper_service.py
import threading
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest
from alpaca.data.live.news import NewsDataStream

from models.database import StockNews

# ─── Active stream registry ───────────────────────────────────────────────────
_active_streams: dict[str, NewsDataStream] = {}
_stream_lock = threading.Lock()


# ─── Historical fetch ─────────────────────────────────────────────────────────

def fetch_historical_news(
    tickers: list[str],
    db: Session,
    api_key: str,
    secret_key: str,
    start: datetime | None = None,
) -> dict:
    """
    Fetch news for each ticker one at a time and insert into the database.
    Returns a summary dict with counts per ticker.
    """
    if start is None:
        start = datetime.now(timezone.utc) - timedelta(days=30)

    client = NewsClient(api_key, secret_key)
    results: dict = {"total_fetched": 0, "total_skipped": 0, "tickers": {}}

    for ticker in tickers:
        ticker = ticker.upper()
        request_params = NewsRequest(symbols=ticker, start=start)
        news_page = client.get_news(request_params)

        fetched = 0
        skipped = 0

        # NewsSet.data is a dict[symbol, list[News]] — flatten all articles
        articles = [a for articles_list in news_page.data.values() for a in articles_list]
        for article in articles:
            alpaca_id = str(article.id)
            exists = db.query(StockNews).filter(StockNews.alpaca_id == alpaca_id).first()
            if exists:
                skipped += 1
                continue

            db.add(StockNews(
                alpaca_id=alpaca_id,
                ticker=ticker,
                headline=article.headline,
                summary=getattr(article, "summary", "") or "",
                url=article.url,
                source=article.source,
                author=getattr(article, "author", "") or "",
                symbols=list(article.symbols) if article.symbols else [],
                published_at=article.created_at,
            ))
            fetched += 1

        db.commit()
        results["tickers"][ticker] = {"fetched": fetched, "skipped": skipped}
        results["total_fetched"] += fetched
        results["total_skipped"] += skipped

        # Respect Alpaca free-tier rate limits between tickers
        time.sleep(0.35)

    return results


# ─── Real-time stream ─────────────────────────────────────────────────────────

def start_news_stream(
    tickers: list[str],
    db_factory,
    api_key: str,
    secret_key: str,
) -> str:
    """
    Start a WebSocket stream for the given tickers and persist incoming articles.
    Returns a stream_key (sorted comma-separated tickers) that can be used to stop
    the stream later.  If a stream for the same key is already running, returns the
    existing key without starting a duplicate.
    """
    stream_key = ",".join(sorted(t.upper() for t in tickers))

    with _stream_lock:
        if stream_key in _active_streams:
            return stream_key

        news_stream = NewsDataStream(api_key, secret_key)

        async def handle_article(article):
            db: Session = db_factory()
            try:
                alpaca_id = str(article.id)
                exists = db.query(StockNews).filter(StockNews.alpaca_id == alpaca_id).first()
                if not exists:
                    db.add(StockNews(
                        alpaca_id=alpaca_id,
                        ticker=article.symbols[0] if article.symbols else "UNKNOWN",
                        headline=article.headline,
                        summary=getattr(article, "summary", "") or "",
                        url=article.url,
                        source=article.source,
                        author=getattr(article, "author", "") or "",
                        symbols=list(article.symbols) if article.symbols else [],
                        published_at=article.created_at,
                    ))
                    db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

        upper_tickers = [t.upper() for t in tickers]
        news_stream.subscribe_news(handle_article, *upper_tickers)

        thread = threading.Thread(target=news_stream.run, daemon=True)
        thread.start()

        _active_streams[stream_key] = news_stream

    return stream_key


def stop_news_stream(stream_key: str) -> bool:
    """Stop a running stream. Returns True if it was found and stopped."""
    with _stream_lock:
        stream = _active_streams.pop(stream_key, None)
        if stream is None:
            return False
        try:
            stream.close()
        except Exception:
            pass
        return True


def list_active_streams() -> list[str]:
    """Return stream keys of all currently running streams."""
    with _stream_lock:
        return list(_active_streams.keys())
