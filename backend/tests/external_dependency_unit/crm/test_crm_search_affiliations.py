"""crm_search tells the model who a contact works for: title, organization and
principal, loaded in one batch, with empty values and the rank left out."""

import json
from queue import Queue
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.db.crm import CrmContactAffiliation, get_contact_affiliations
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.tool_implementations.crm.crm_search_tool import CrmSearchTool
from tests.external_dependency_unit.crm.conftest import CrmRecords

PLACEMENT = Placement(turn_index=0, tab_index=0)
AFFILIATION_KEYS = {"title", "organization_name", "principal", "principal_contact_id"}


def test_get_contact_affiliations_loads_each_contact(
    db_session: Session, crm: CrmRecords
) -> None:
    org = crm.org()
    official = crm.contact(first_name="Sara", last_name="Official")
    staffer = crm.contact(
        title="Chief of Staff",
        organization_id=org.id,
        principal="Sara Official",
        principal_contact_id=official.id,
    )
    unlinked = crm.contact(principal="Rep. Someone Else")
    bare = crm.contact()

    affiliations = get_contact_affiliations(
        {staffer.id, unlinked.id, bare.id, uuid4()}, db_session
    )

    assert affiliations == {
        staffer.id: CrmContactAffiliation(
            title="Chief of Staff",
            organization_name=org.name,
            principal="Sara Official",
            principal_contact_id=official.id,
        ),
        unlinked.id: CrmContactAffiliation(
            title=None,
            organization_name=None,
            principal="Rep. Someone Else",
            principal_contact_id=None,
        ),
        bare.id: CrmContactAffiliation(
            title=None,
            organization_name=None,
            principal=None,
            principal_contact_id=None,
        ),
    }
    assert get_contact_affiliations(set(), db_session) == {}


def test_search_contacts_include_affiliation_without_rank(
    db_session: Session, crm: CrmRecords
) -> None:
    token = f"affil{uuid4().hex[:10]}"
    org = crm.org()
    official = crm.contact(first_name="Sara", last_name="Official")
    staffer = crm.contact(
        first_name=token,
        last_name="Staffer",
        title="Legislative Director",
        organization_id=org.id,
        principal="Sara Official",
        principal_contact_id=official.id,
    )
    bare = crm.contact(first_name=token, last_name="Bare", title="  ")
    interaction = crm.interaction(title=f"Meeting {token}")

    tool = CrmSearchTool(1, db_session, Emitter(Queue()))
    response = tool.run(placement=PLACEMENT, query=token)
    model_view: dict[str, Any] = json.loads(response.llm_facing_response)
    stored: dict[str, Any] = json.loads(str(response.rich_response))

    by_id = {row["entity_id"]: row for row in model_view["results"]}
    assert set(by_id) == {str(staffer.id), str(bare.id), str(interaction.id)}
    assert by_id[str(staffer.id)] | {"sort_at": None} == {
        "entity_type": "contact",
        "entity_id": str(staffer.id),
        "primary_text": f"{token} Staffer",
        "secondary_text": None,
        "sort_at": None,
        "title": "Legislative Director",
        "organization_name": org.name,
        "principal": "Sara Official",
        "principal_contact_id": str(official.id),
    }
    assert not AFFILIATION_KEYS & by_id[str(bare.id)].keys()
    assert not AFFILIATION_KEYS & by_id[str(interaction.id)].keys()
    for view in (model_view, stored):
        assert all("rank" not in row for row in view["results"])
