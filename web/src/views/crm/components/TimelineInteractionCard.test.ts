import type {
  CrmInteraction,
  CrmInteractionAttendee,
} from "@/app/app/crm/crmService";

import { getInteractionPeople } from "./TimelineInteractionCard";

function attendee(
  fields: Partial<CrmInteractionAttendee>
): CrmInteractionAttendee {
  return {
    id: 1,
    user_id: null,
    contact_id: null,
    display_name: null,
    role: "attendee",
    created_at: "2026-09-23T00:00:00Z",
    ...fields,
  };
}

function interaction(fields: Partial<CrmInteraction>): CrmInteraction {
  return {
    id: "i-1",
    contact_id: null,
    contact_name: null,
    organization_id: null,
    organization_name: null,
    logged_by: null,
    type: "meeting",
    title: "Meeting",
    summary: null,
    occurred_at: null,
    created_at: "2026-09-23T00:00:00Z",
    updated_at: "2026-09-23T00:00:00Z",
    attendees: [],
    ...fields,
  };
}

describe("getInteractionPeople", () => {
  it("shows the primary contact once when it is also an attendee", () => {
    const people = getInteractionPeople(
      interaction({
        contact_id: "c-jane",
        contact_name: "Jane Smith",
        attendees: [
          // A different display name must not bring the contact back twice.
          attendee({ contact_id: "c-jane", display_name: "Jane Q. Smith" }),
          attendee({ id: 2, user_id: "u-matt", display_name: "Matt" }),
        ],
      })
    );

    expect(people).toEqual(["Jane Smith", "Matt"]);
  });

  it("removes repeated names across the primary contact and attendees", () => {
    const people = getInteractionPeople(
      interaction({
        contact_id: "c-jane",
        contact_name: "Jane Smith",
        attendees: [
          attendee({ contact_id: "c-other", display_name: "Jane Smith" }),
          attendee({ id: 2, contact_id: "c-bob", display_name: "Bob Lee" }),
          attendee({ id: 3, contact_id: "c-bob2", display_name: "Bob Lee" }),
        ],
      })
    );

    expect(people).toEqual(["Jane Smith", "Bob Lee"]);
  });

  it("keeps user attendees when there is no primary contact", () => {
    const people = getInteractionPeople(
      interaction({
        attendees: [attendee({ user_id: "u-matt" })],
      }),
      new Map([["u-matt", "matt@example.com"]])
    );

    expect(people).toEqual(["matt@example.com"]);
  });

  it("uses the attendee row when the primary contact has no name", () => {
    const people = getInteractionPeople(
      interaction({
        contact_id: "c-jane",
        contact_name: null,
        attendees: [attendee({ contact_id: "c-jane" })],
      }),
      undefined,
      new Map([["c-jane", "Jane Smith"]])
    );

    expect(people).toEqual(["Jane Smith"]);
  });
});
