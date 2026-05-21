from fastapi import APIRouter

from app.schemas.common import HealthResponse

router = APIRouter()


@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")
