import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from models import User

logger = logging.getLogger("half.feishu")

DEFAULT_NOTIFY_EVENTS = ["completed", "timeout", "project_completed"]
ALLOWED_NOTIFY_EVENTS = {"completed", "timeout", "project_completed"}


@dataclass
class NotificationEvent:
    event_type: str
    project_name: str
    task_name: Optional[str] = field(default=None)
    detail: Optional[str] = field(default=None)


@dataclass(frozen=True)
class FeishuDestination:
    webhook_url: str
    notify_events: frozenset[str]


def _normalize_notify_events(raw_events: str | None) -> list[str]:
    try:
        notify_events = json.loads(raw_events) if raw_events else DEFAULT_NOTIFY_EVENTS
        if not isinstance(notify_events, list):
            notify_events = DEFAULT_NOTIFY_EVENTS
    except (json.JSONDecodeError, TypeError):
        notify_events = DEFAULT_NOTIFY_EVENTS

    normalized = [event for event in notify_events if event in ALLOWED_NOTIFY_EVENTS]
    if notify_events and not normalized:
        return DEFAULT_NOTIFY_EVENTS
    return normalized


def get_feishu_settings(user: User) -> dict:
    """Read Feishu notification settings from the current user record."""
    webhook_url = (user.feishu_webhook_url or "").strip()
    notify_events = _normalize_notify_events(user.feishu_notify_events_json)

    return {"webhook_url": webhook_url, "notify_events": notify_events}


def get_feishu_destination_for_user(db: Session, user_id: int) -> FeishuDestination | None:
    user = db.query(User).filter(User.id == user_id, User.status == "active").first()
    if user is None:
        return None

    settings = get_feishu_settings(user)
    webhook_url = settings["webhook_url"]
    if not webhook_url:
        return None

    return FeishuDestination(
        webhook_url=webhook_url,
        notify_events=frozenset(settings["notify_events"]),
    )


async def dispatch_notifications(db: Session, user_id: int, notifications: list[NotificationEvent]) -> int:
    """Send generated notifications to one user's Feishu webhook subscription."""
    if not notifications:
        return 0

    destination = get_feishu_destination_for_user(db, user_id)
    if destination is None:
        return 0

    deliveries = []
    for event in notifications:
        if event.event_type in destination.notify_events:
            deliveries.append(send_feishu_notification(destination.webhook_url, event))

    if not deliveries:
        return 0

    await asyncio.gather(*deliveries)
    return len(deliveries)


_CARD_COLORS = {
    "completed": "green",
    "timeout": "orange",
    "project_completed": "green",
}

_CARD_TITLES = {
    "completed": "任务完成",
    "timeout": "任务超时",
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
