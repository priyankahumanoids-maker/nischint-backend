# Telemetry Router
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.schemas.telemetry import TelemetryCreate, TelemetryResponse
from app.services import telemetry_service

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post("", response_model=TelemetryResponse, status_code=status.HTTP_201_CREATED)
async def ingest_telemetry(
    telemetry_create: TelemetryCreate,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Ingest telemetry data from a device.
    
    Automatically triggers incident creation for:
    - metric_type="sos" → critical severity incident
    - metric_type="fall_detected" → high severity incident
    """
    # Phase 7C-6 legacy containment: this historical endpoint has no device
    # credential binding. Preserve non-emergency telemetry compatibility, but
    # never allow an unauthenticated device identifier to manufacture SOS/fall
    # incidents. Current mobile safety flows use authenticated /wearable/event
    # and /sensors/fall instead.
    if telemetry_create.metric_type in {"sos", "fall_detected"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Legacy telemetry cannot create emergency incidents; use an "
                "authenticated wearable/sensor safety endpoint"
            ),
        )

    try:
        telemetry = await telemetry_service.ingest_telemetry(session, telemetry_create)
        return telemetry
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
