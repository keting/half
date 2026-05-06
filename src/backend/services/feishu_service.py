import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from models import GlobalSetting

logger = logging.getLogger("half.feishu")

FEISHU_WEBHOOK_URL_KEY = "feishu_webhook_url"
FEISHU_NOTIFY_EVENTS_KEY = "feishu_notify_events"
DEFAULT_NOTIFY_EVENTS = ["completed", "timeout", "project_completed"]
ALLOWED_NOTIFY_EVENTS = {"completed", "timeout", "error", "project_completed"}


@dataclass
class NotificationEvent:
    event_type: str
    project_name: str
    task_name: Optional[str] = field(default=None)
    detail: Optional[str] = field(default=None)


def get_feishu_settings(db: Session) -> dict:
    """Read Feishu notification settings from GlobalSetting table."""
    rows = db.query(GlobalSetting).filter(
        GlobalSetting.key.in_([FEISHU_WEBHOOK_URL_KEY, FEISHU_NOTIFY_EVENTS_KEY])
    ).all()
    result = {r.key: r.value for r in rows}

    webhook_url = result.get(FEISHU_WEBHOOK_URL_KEY, "")

    raw_events = result.get(FEISHU_NOTIFY_EVENTS_KEY)
    try:
        notify_events = json.loads(raw_events) if raw_events else DEFAULT_NOTIFY_EVENTS
        if not isinstance(notify_events, list):
            notify_events = DEFAULT_NOTIFY_EVENTS
    except (json.JSONDecodeError, TypeError):
        notify_events = DEFAULT_NOTIFY_EVENTS

    return {"webhook_url": webhook_url, "notify_events": notify_events}


_CARD_COLORS = {
    "completed": "green",
    "timeout": "orange",
    "error": "red",
    "project_completed": "green",
}

_CARD_TITLES = {
    "completed": "任务完成",
    "timeout": "任务超时",
    "error": "任务报错",
    "project_completed": "项目完成",
}


def _build_card(event: NotificationEvent) -> dict:
    color = _CARD_COLORS.get(event.event_type, "blue")
    title = _CARD_TITLES.get(event.event_type, "HALF 通知")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [f"**项目**：{event.project_name}"]
    if event.task_name:
        lines.append(f"**任务**：{event.task_name}")
    if event.detail:
        lines.append(f"**详情**：{event.detail}")
    lines.append(f"**时间**：{now_str}")

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"HALF · {title}"},
            "template": color,
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "\n".join(lines),
                },
            }
        ],
    }


async def send_feishu_notification(webhook_url: str, event: NotificationEvent) -> None:
    """POST an interactive card to the Feishu custom bot webhook.

    Exceptions are caught and logged as warnings so that a Feishu delivery
    failure never disrupts the polling loop.
    """
    payload = {
        "msg_type": "interactive",
        "card": _build_card(event),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code != 200:
                logger.warning(
                    "Feishu webhook returned non-200: %s %s",
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception as exc:
        logger.warning("Failed to send Feishu notification (%s): %s", event.event_type, exc)
