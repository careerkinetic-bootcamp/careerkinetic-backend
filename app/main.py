import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.routers import auth

app = FastAPI(title="CareerKinetic Backend API")


@app.on_event("startup")
async def startup_event():
    from app.core.database import Base, engine
    from app.models.domain import User  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    body = b""
    try:
        body = await request.body()
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "traceback": tb,
            "request_body": body.decode(errors="ignore"),
        },
    )


app.include_router(auth.router, prefix="/api/auth")


@app.get("/")
def health_check():
    return {"status": "ok"}
