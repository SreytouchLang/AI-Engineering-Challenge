from __future__ import annotations

from fastapi import FastAPI

from app.review.router import router as review_router
from app.telephony.webhooks import router as telephony_router

app = FastAPI(title="Pretty Good AI Voice Tester")
app.include_router(telephony_router)
app.include_router(review_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Pretty Good AI voice tester is running."}
