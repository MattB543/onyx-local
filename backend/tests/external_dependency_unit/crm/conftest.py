"""Fixtures for CRM tests against a real, migrated Postgres.

These tests rely on the CRM updated_at triggers (migration 39db7165c7ac), so the
database must be migrated first: `alembic -x schemas=public upgrade head`.
"""

from collections.abc import Generator
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import CrmAttendeeRole, CrmInteractionType
from onyx.db.models import (
    CrmContact,
    CrmInteraction,
    CrmInteractionAttendee,
    CrmOrganization,
    CrmTag,
    User,
    User__UserGroup,
)
from tests.external_dependency_unit.conftest import create_test_user

CRM_TRIGGERS = {
    "crm_contact_set_updated_at",
    "crm_organization_set_updated_at",
    "crm_interaction_set_updated_at",
    "crm_contact__tag_touch_parent",
    "crm_organization__tag_touch_parent",
    "crm_contact_owner_touch_parent",
    "crm_interaction_touch_related_ins_del",
    "crm_interaction_touch_related_upd",
    "crm_interaction_attendee_touch_related",
    "crm_contact_touch_organization_ins_del",
    "crm_contact_touch_organization_upd",
}

StampedModel = type[CrmContact] | type[CrmOrganization] | type[CrmInteraction]

# Children first, so no delete waits on a cascade from a later one.
_CLEANUP_ORDER = (CrmInteraction, CrmContact, CrmOrganization, CrmTag)


@pytest.fixture(scope="module", autouse=True)
def _require_crm_triggers() -> None:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    with get_session_with_current_tenant() as session:
        found = set(
            session.scalars(
                text(
                    "SELECT t.tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE NOT t.tgisinternal AND n.nspname = current_schema()"
                )
            )
        )
    missing = CRM_TRIGGERS - found
    if missing:
        pytest.fail(
            f"CRM triggers missing: {sorted(missing)}. "
            "Run `alembic -x schemas=public upgrade head` on the test database."
        )


def db_clock(db_session: Session) -> datetime:
    return db_session.execute(text("SELECT clock_timestamp()")).scalar_one()


def stamp(db_session: Session, model: StampedModel, record_id: UUID) -> datetime:
    """The committed-or-flushed updated_at, bypassing the identity map."""
    return db_session.execute(
        select(model.updated_at).where(model.id == record_id)
    ).scalar_one()


class CrmRecords:
    """Creates committed CRM rows with unique names and deletes them afterwards."""

    def __init__(self, db_session: Session) -> None:
        self._db = db_session
        self._suffix = uuid4().hex[:8]
        self._created: list[tuple[type, UUID]] = []
        self._user_ids: list[UUID] = []
        self._counter = 0

    def _name(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix} {self._suffix}-{self._counter}"

    def _commit(self, record: Any) -> Any:
        self._db.add(record)
        self._db.commit()
        self._created.append((type(record), record.id))
        return record

    def track(self, model: type, record_id: UUID | str) -> None:
        """Delete a row created outside this helper (e.g. by a tool) on cleanup."""
        self._created.append((model, UUID(str(record_id))))

    def org(self, **fields: Any) -> CrmOrganization:
        fields.setdefault("name", self._name("CRM Test Org"))
        return self._commit(CrmOrganization(**fields))

    def contact(self, **fields: Any) -> CrmContact:
        fields.setdefault("first_name", self._name("Contact"))
        fields.setdefault("status", "lead")
        return self._commit(CrmContact(**fields))

    def tag(self) -> CrmTag:
        return self._commit(CrmTag(name=self._name("crm-test-tag")))

    def interaction(
        self,
        *,
        attendee_contact_ids: list[UUID] | None = None,
        attendee_user_ids: list[UUID] | None = None,
        **fields: Any,
    ) -> CrmInteraction:
        fields.setdefault("title", self._name("Interaction"))
        fields.setdefault("type", CrmInteractionType.NOTE)
        interaction = CrmInteraction(**fields)
        self._db.add(interaction)
        self._db.flush()
        for contact_id in attendee_contact_ids or []:
            self._db.add(
                CrmInteractionAttendee(
                    interaction_id=interaction.id,
                    contact_id=contact_id,
                    role=CrmAttendeeRole.ATTENDEE,
                )
            )
        for user_id in attendee_user_ids or []:
            self._db.add(
                CrmInteractionAttendee(
                    interaction_id=interaction.id,
                    user_id=user_id,
                    role=CrmAttendeeRole.ATTENDEE,
                )
            )
        return self._commit(interaction)

    def user(self) -> User:
        user = create_test_user(
            self._db, f"crm_user_{self._suffix}", assign_default_group=False
        )
        self._user_ids.append(user.id)
        return user

    def cleanup(self) -> None:
        self._db.rollback()
        for model in _CLEANUP_ORDER:
            ids = [rid for rtype, rid in self._created if rtype is model]
            if ids:
                self._db.execute(delete(model).where(model.id.in_(ids)))
        if self._user_ids:
            self._db.execute(
                delete(User__UserGroup).where(
                    User__UserGroup.user_id.in_(self._user_ids)
                )
            )
            self._db.execute(
                delete(User).where(User.__table__.c.id.in_(self._user_ids))
            )
        self._db.commit()


@pytest.fixture
def crm(db_session: Session) -> Generator[CrmRecords, None, None]:
    records = CrmRecords(db_session)
    try:
        yield records
    finally:
        records.cleanup()
