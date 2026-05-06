import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import GlobalSetting
from auth import get_current_user, require_admin
from services.polling_config_service import get_global_polling_settings
from services.prompt_settings import (
    DEFAULT_PLAN_CO_LOCATION_GUIDANCE,
    get_plan_co_location_guidance,
    upsert_plan_co_location_guidance,
)
from services.feishu_service import (
    get_feishu_settings,
    FEISHU_WEBHOOK_URL_KEY,
    FEISHU_NOTIFY_EVENTS_KEY,
    ALLOWED_NOTIFY_EVENTS,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/polling")
async def get_polling_settings(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Get global polling settings."""
    return get_global_polling_settings(db)


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
        "task_timeout_minutes",
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
    if "task_timeout_minutes" in coerced:
        v = coerced["task_timeout_minutes"]
        if v < 1 or v > 120:
            raise HTTPException(status_code=400, detail="task_timeout_minutes must be 1-120 minutes")

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


@router.get("/prompt")
async def get_prompt_settings(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Get global prompt settings."""
    return {
        "co_location_guidance": get_plan_co_location_guidance(db),
        "default_co_location_guidance": DEFAULT_PLAN_CO_LOCATION_GUIDANCE,
    }


@router.put("/prompt")
async def update_prompt_settings(
    settings_data: dict,
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
):
    """Update global prompt settings."""
    if "co_location_guidance" not in settings_data:
        raise HTTPException(status_code=400, detail="co_location_guidance is required")
    try:
        guidance = upsert_plan_co_location_guidance(db, settings_data.get("co_location_guidance"))
    except ValueError:
        raise HTTPException(status_code=400, detail="co_location_guidance must not be empty")
    return {
        "co_location_guidance": guidance,
        "default_co_location_guidance": DEFAULT_PLAN_CO_LOCATION_GUIDANCE,
    }


_FEISHU_WEBHOOK_RE = re.compile(
    r'^https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9_-]+$'
)


@router.get("/feishu")
async def get_feishu_notification_settings(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Get Feishu notification settings."""
    return get_feishu_settings(db)


@router.put("/feishu")
async def update_feishu_notification_settings(
    settings_data: dict,
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
):
    """Update Feishu notification settings (admin only)."""
    webhook_url = settings_data.get("webhook_url", "")
    notify_events = settings_data.get("notify_events", [])

    if not isinstance(webhook_url, str):
        raise HTTPException(status_code=400, detail="webhook_url must be a string")
    if webhook_url and not _FEISHU_WEBHOOK_RE.match(webhook_url):
        raise HTTPException(
            status_code=400,
            detail="webhook_url must match https://open.feishu.cn/open-apis/bot/v2/hook/<token>",
        )
    if not isinstance(notify_events, list):
        raise HTTPException(status_code=400, detail="notify_events must be a list")
    invalid_events = [e for e in notify_events if e not in ALLOWED_NOTIFY_EVENTS]
    if invalid_events:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event types: {invalid_events}. Allowed: {sorted(ALLOWED_NOTIFY_EVENTS)}",
        )

    for key, value in [
        (FEISHU_WEBHOOK_URL_KEY, webhook_url),
        (FEISHU_NOTIFY_EVENTS_KEY, json.dumps(notify_events)),
    ]:
        setting = db.query(GlobalSetting).filter(GlobalSetting.key == key).first()
        if not setting:
            setting = GlobalSetting(key=key, value=value)
            db.add(setting)
        else:
            setting.value = value

    db.commit()
    return {"webhook_url": webhook_url, "notify_events": notify_events}
