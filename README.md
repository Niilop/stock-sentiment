# Stock News Sentiment Analysis

Fetches financial news articles for selected stock tickers, scores them with FinBERT, and produces an LLM-generated sentiment summary for any chosen timeframe.

The backend is built on a [FastAPI template](https://github.com/Niilop/My-FastAPI-template) — auth, RAG, chat, and data catalog features come from there and are not covered here.

---

## How it works

1. **Fetch news** — pull historical articles from the Alpaca Markets API for one or more tickers and store them in PostgreSQL.
2. **Score sentiment** — run [ProsusAI/FinBERT](https://huggingface.co/ProsusAI/finbert) over each article's headline and summary to label it `positive`, `negative`, or `neutral`. The model (~440 MB) is downloaded on first use and cached locally under `ml_models/finbert/`.
3. **Summarize a timeframe** — select a ticker and date range in the UI; the backend builds a prompt from every stored article in that window and sends it to the configured LLM, which returns a structured analysis.

---

## Setup

### Prerequisites
- Docker + Docker Compose
- Alpaca Markets account (free tier works) — for the news API
- API key for at least one LLM provider (Anthropic, OpenAI, or Gemini)

### Configuration

Copy `.envexample` to `.env` and fill in the values:

```
ALPACA_API_KEY=
ALPACA_SECRET_KEY=

LLM_PROVIDER=anthropic          # anthropic | openai | gemini
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6

POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=ds_playground
DATABASE_URL=postgresql://postgres:postgres@db:5432/ds_playground
```

### Run

```bash
docker compose up --build
```

| Service  | URL                    |
|----------|------------------------|
| Frontend | http://localhost:8501  |
| API docs | http://localhost:8000/docs |

On first startup the backend runs Alembic migrations automatically. FinBERT is downloaded the first time sentiment scoring is triggered.

---

## API endpoints

### News

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/news/fetch` | Fetch historical news for a list of tickers (background job) |
| `GET`  | `/news/` | Query stored articles, optionally filtered by ticker |
| `GET`  | `/news/tickers` | List all ticker symbols that have stored articles |
| `POST` | `/news/stream/start` | Start a real-time news stream |
| `POST` | `/news/stream/stop` | Stop a running stream |

`POST /news/fetch` body:
```json
{ "tickers": ["AAPL", "MSFT"], "start": "2024-01-01T00:00:00" }
```

### Sentiment scoring

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sentiment/run` | Score unscored articles with FinBERT (background job) |
| `POST` | `/sentiment/summary` | Build a prompt from stored articles and return an LLM analysis |

`POST /sentiment/summary` body:
```json
{ "ticker": "AAPL", "start": "2024-01-01T00:00:00", "end": "2024-03-31T23:59:59" }
```

Response:
```json
{
  "ticker": "AAPL",
  "start": "...",
  "end": "...",
  "articles_found": 45,
  "sentiment_breakdown": { "positive": 20, "negative": 10, "neutral": 12, "unscored": 3 },
  "summary": "Overall sentiment for AAPL was positive, driven by..."
}
```

Background jobs can be polled at `GET /jobs/{job_id}`.

---

## Typical workflow

1. Register and log in via the sidebar.
2. Trigger `POST /news/fetch` to pull articles for your tickers of interest.
3. Run `POST /sentiment/run` to score them with FinBERT (use `["*"]` for all tickers).
4. Open the **Sentiment Analysis** section in the UI, pick a ticker and date range, and click **Analyze Sentiment**.
