import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth import hash_password
from main import repair_legacy_project_owners
from models import Base, Project, User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class ProjectOwnerRepairTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def test_repair_assigns_admin_to_legacy_projects_without_owner(self):
        with self.SessionLocal() as db:
            admin = User(username="admin", password_hash=hash_password("Admin123"))
            db.add(admin)
            db.flush()
            legacy = Project(name="legacy-project", agent_ids_json="[]", created_by=None)
            owned = Project(name="owned-project", agent_ids_json="[]", created_by=admin.id)
            db.add_all([legacy, owned])
            db.commit()

            repair_legacy_project_owners(db, admin)

            db.refresh(legacy)
            db.refresh(owned)
            self.assertEqual(legacy.created_by, admin.id)
            self.assertEqual(owned.created_by, admin.id)


if __name__ == "__main__":
    unittest.main()
