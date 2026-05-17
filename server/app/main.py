from fastapi import FastAPI

app = FastAPI(title="TradingAgents Dashboard API")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
