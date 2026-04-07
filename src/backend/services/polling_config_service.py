import random
from sqlalchemy.orm import Session
from models import GlobalSetting, Project


def get_global_polling_settings(db: Session) -> dict:
    """Get global polling settings from database."""
    settings = db.query(GlobalSetting).filter(
        GlobalSetting.key.in_([
            "polling_interval_min",
            "polling_interval_max",
            "polling_start_delay_minutes",
            "polling_start_delay_seconds",
        ])
    ).all()

    result = {
        "polling_interval_min": 15,  # default 15 seconds
        "polling_interval_max": 30,  # default 30 seconds
        "polling_start_delay_minutes": 0,  # default 0 minutes
        "polling_start_delay_seconds": 0,  # default 0 seconds
    }

    for setting in settings:
        try:
            value = int(setting.value)
            if setting.key in result:
                result[setting.key] = value
        except (ValueError, TypeError):
            pass

    return result


def get_project_polling_settings(db: Session, project: Project) -> dict:
    """Get effective polling settings for a project (project-level overrides global)."""
    global_settings = get_global_polling_settings(db)

    return {
        "polling_interval_min": project.polling_interval_min if project.polling_interval_min is not None else global_settings["polling_interval_min"],
        "polling_interval_max": project.polling_interval_max if project.polling_interval_max is not None else global_settings["polling_interval_max"],
        "polling_start_delay_minutes": project.polling_start_delay_minutes if project.polling_start_delay_minutes is not None else global_settings["polling_start_delay_minutes"],
        "polling_start_delay_seconds": project.polling_start_delay_seconds if project.polling_start_delay_seconds is not None else global_settings["polling_start_delay_seconds"],
    }


def get_random_polling_interval(db: Session, project: Project) -> int:
    """Get a random polling interval in seconds for a project."""
    settings = get_project_polling_settings(db, project)
    min_interval = settings["polling_interval_min"]
    max_interval = settings["polling_interval_max"]

    # Ensure min <= max
    if min_interval > max_interval:
        min_interval, max_interval = max_interval, min_interval

    return random.randint(min_interval, max_interval) * 1000  # convert to milliseconds for JavaScript


def get_polling_start_delay_ms(db: Session, project: Project) -> int:
    """Get the polling start delay in milliseconds for a project."""
    settings = get_project_polling_settings(db, project)
    total_seconds = settings["polling_start_delay_minutes"] * 60 + settings["polling_start_delay_seconds"]
    return total_seconds * 1000  # convert to milliseconds for JavaScript
