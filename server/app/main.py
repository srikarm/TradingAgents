from fastapi import FastAPI

from app.routers import me as me_router

app = FastAPI(title="TradingAgents Dashboard API")
app.include_router(me_router.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
