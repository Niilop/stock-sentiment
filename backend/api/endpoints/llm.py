import json
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from models.schemas import SummaryRequest, SummaryResponse
from services.llm_service import summarize_text, summarize_text_stream
from services.auth_service import decode_token
from core.rate_limit import limiter

router = APIRouter(prefix="/llm", tags=["AI Solutions"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def require_auth(token: str = Depends(oauth2_scheme)):
    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token_data

@router.post("/summarize", response_model=SummaryResponse)
@limiter.limit("5/minute")
def run_summarization(request: Request, body: SummaryRequest, _: dict = Depends(require_auth)):
    try:
        result = summarize_text(body.text)
        return SummaryResponse(summary=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/summarize/stream")
@limiter.limit("5/minute")
async def run_summarization_stream(request: Request, body: SummaryRequest, _: dict = Depends(require_auth)):
    async def event_generator():
        try:
            async for chunk in summarize_text_stream(body.text):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps('[ERROR] ' + str(e))}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")