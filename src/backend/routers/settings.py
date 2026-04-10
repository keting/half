from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import GlobalSetting
from auth import get_current_user, require_admin

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/polling")
async def get_polling_settings(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Get global polling settings."""
    settings = db.query(GlobalSetting).filter(
        GlobalSetting.key.in_([
            "polling_interval_min",
            "polling_interval_max",
            "polling_start_delay_minutes",
            "polling_start_delay_seconds",
        ])
    ).all()

    result = {}
    for setting in settings:
        try:
            result[setting.key] = int(setting.value)
        except (ValueError, TypeError):
            result[setting.key] = setting.value

    return result


def _validate_global_polling_payload(payload: dict) -> dict:
    """Coerce + validate a global polling settings payload.

    Returns a dict of {key: int_value} for the keys present in the payload.
    Raises HTTPException with details on the first failure.
    """
    allowed_keys = {
        "polling_interval_min",
        "polling_interval_max",
        "polling_start_delay_minutes",
        "polling_start_delay_seconds",
    }
    coerced: dict = {}
    for key, value in payload.items():
        if key not in allowed_keys:
            raise HTTPException(status_code=400, detail=f"Invalid setting key: {key}")
        try:
            coerced[key] = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{key} must be an integer")

    if "polling_interval_min" in coerced:
        v = coerced["polling_interval_min"]
        if v < 1 or v > 600:
            raise HTTPException(status_code=400, detail="polling_interval_min must be 1-600 seconds")
    if "polling_interval_max" in coerced:
        v = coerced["polling_interval_max"]
        if v < 1 or v > 600:
            raise HTTPException(status_code=400, detail="polling_interval_max must be 1-600 seconds")
    if "polling_interval_min" in coerced and "polling_interval_max" in coerced:
        if coerced["polling_interval_min"] > coerced["polling_interval_max"]:
            raise HTTPException(
                status_code=400,
                detail="polling_interval_min must be <= polling_interval_max",
            )
    if "polling_start_delay_minutes" in coerced:
        v = coerced["polling_start_delay_minutes"]
        if v < 0 or v > 60:
            raise HTTPException(status_code=400, detail="polling_start_delay_minutes must be 0-60")
    if "polling_start_delay_seconds" in coerced:
        v = coerced["polling_start_delay_seconds"]
        if v < 0 or v > 59:
            raise HTTPException(status_code=400, detail="polling_start_delay_seconds must be 0-59")

    return coerced


@router.put("/polling")
async def update_polling_settings(
    settings_data: dict,
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
):
    """Update global polling settings."""
    coerced = _validate_global_polling_payload(settings_data)

    # Cross-field validation including currently-stored values: even if the
    # client only updates one of min/max, the resulting state must satisfy
    # min <= max.
    if ("polling_interval_min" in coerced) ^ ("polling_interval_max" in coerced):
        existing = db.query(GlobalSetting).filter(
            GlobalSetting.key.in_(["polling_interval_min", "polling_interval_max"])
        ).all()
        existing_map = {s.key: int(s.value) for s in existing}
        merged_min = coerced.get("polling_interval_min", existing_map.get("polling_interval_min", 15))
        merged_max = coerced.get("polling_interval_max", existing_map.get("polling_interval_max", 30))
        if merged_min > merged_max:
            raise HTTPException(
                status_code=400,
                detail="polling_interval_min must be <= polling_interval_max",
            )

    for key, value in coerced.items():
        setting = db.query(GlobalSetting).filter(GlobalSetting.key == key).first()
        if not setting:
            setting = GlobalSetting(key=key, value=str(value))
            db.add(setting)
        else:
            setting.value = str(value)

    db.commit()
    return {"message": "Settings updated successfully"}
