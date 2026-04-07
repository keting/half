import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import routers.settings as settings_router


class PollingSettingsValidationTests(unittest.TestCase):
    def test_settings_router_imports(self):
        self.assertEqual(settings_router.router.prefix, "/api/settings")

    def test_validate_global_polling_payload_accepts_valid_values(self):
        payload = {
            "polling_interval_min": 15,
            "polling_interval_max": 30,
            "polling_start_delay_minutes": 2,
            "polling_start_delay_seconds": 30,
        }
        coerced = settings_router._validate_global_polling_payload(payload)
        self.assertEqual(coerced, payload)

    def test_validate_global_polling_payload_rejects_invalid_range(self):
        with self.assertRaises(Exception) as ctx:
            settings_router._validate_global_polling_payload({
                "polling_interval_min": 31,
                "polling_interval_max": 30,
            })
        self.assertIn("polling_interval_min must be <= polling_interval_max", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
