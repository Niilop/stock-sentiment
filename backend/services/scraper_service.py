# backend/services/scraper_service.py
import asyncio
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest
from alpaca.data.live.news import NewsDataStream

from models.database import StockNews

# Silence alpaca's noisy websocket retry logger
logging.getLogger("alpaca").setLevel(logging.ERROR)

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

# Set up a module-level logger
log = logging.getLogger(__name__)

def start_news_stream(
    tickers: list[str],
    db_factory,
    api_key: str,
    secret_key: str,
) -> str:
    """
    Starts a background WebSocket stream for the given tickers and persists incoming articles.
    
    This function ensures only one active stream exists per unique set of tickers.
    It offloads database writes to a separate thread to prevent blocking the 
    WebSocket's asynchronous event loop.

    Args:
        tickers: A list of stock ticker symbols to subscribe to.
        db_factory: A callable that returns a new SQLAlchemy Session.
        api_key: Alpaca API key.
        secret_key: Alpaca Secret key.

    Returns:
        str: A unique stream key (comma-separated, sorted tickers) identifying the stream.

    Raises:
        RuntimeError: If the stream fails to initialize or connects and crashes immediately.
    """
    
    # Create a consistent, unique key for this specific combination of tickers
    stream_key = ",".join(sorted(t.upper() for t in tickers))

    # Thread-safe check to prevent duplicate streams for the same tickers
    with _stream_lock:
        if stream_key in _active_streams:
            log.info(f"Stream for {stream_key} is already running.")
            return stream_key

        # Initialize the official Alpaca SDK client
        news_stream = NewsDataStream(api_key, secret_key)

        async def handle_article(article):
            """
            Callback triggered by the Alpaca SDK whenever a new article arrives.
            Because this runs in the WebSocket's async event loop, we must not block it.
            """
            
            def save_to_db():
                """Synchronous database operations running safely in a background thread."""
                db: Session = db_factory()
                try:
                    alpaca_id = str(article.id)
                    
                    # Check if we already processed this article to avoid duplicates
                    exists = db.query(StockNews).filter(StockNews.alpaca_id == alpaca_id).first()
                    if not exists:
                        # Extract the primary ticker, defaulting to "UNKNOWN" if none exist
                        primary_ticker = article.symbols[0] if article.symbols else "UNKNOWN"
                        
                        # Build and insert the new record
                        new_article = StockNews(
                            alpaca_id=alpaca_id,
                            ticker=primary_ticker,
                            headline=article.headline,
                            summary=getattr(article, "summary", "") or "",
                            url=article.url,
                            source=article.source,
                            author=getattr(article, "author", "") or "",
                            symbols=list(article.symbols) if article.symbols else [],
                            published_at=article.created_at,
                        )
                        db.add(new_article)
                        db.commit()
                        log.debug(f"Saved new article: {article.headline}")
                        
                except Exception as e:
                    db.rollback()
                    log.error(f"Failed to save article {article.id} to database: {e}", exc_info=True)
                finally:
                    db.close()
            
            # Offload the blocking database write to a separate thread
            # This keeps the WebSocket ping/pong heartbeat alive
            await asyncio.to_thread(save_to_db)

        # Register the callback and subscribe to the requested tickers
        upper_tickers = [t.upper() for t in tickers]
        news_stream.subscribe_news(handle_article, *upper_tickers)

        def stream_worker():
            """
            The target function for the background thread. 
            It runs the SDK's blocking event loop and cleans up if it exits.
            """
            try:
                log.info(f"Connecting to Alpaca news stream for: {stream_key}")
                # The SDK's run() method handles its own connection and standard retries
                news_stream.run()
            except Exception as exc:
                log.error(f"News stream '{stream_key}' encountered a fatal error: {exc}", exc_info=True)
            finally:
                # Ensure the stream is removed from the registry when it stops
                with _stream_lock:
                    _active_streams.pop(stream_key, None)
                log.info(f"News stream '{stream_key}' has been fully shut down.")

        # Launch the stream in a daemon thread so it does not block the main application exit
        thread = threading.Thread(
            target=stream_worker, 
            daemon=True, 
            name=f"news-stream-{stream_key}"
        )
        thread.start()

        # Wait briefly to catch instant failures (like connection limits or bad auth)
        thread.join(timeout=4.0)
        if not thread.is_alive():
            raise RuntimeError(f"Stream '{stream_key}' failed to start. Check your API credentials and connection limits.")

        # Register the successful stream
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
