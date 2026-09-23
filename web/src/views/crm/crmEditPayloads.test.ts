import {
  buildContactPatchBody,
  buildOrganizationPatchBody,
  ContactEditValues,
  nullableText,
  OrganizationEditValues,
} from "./crmEditPayloads";

const CONTACT: ContactEditValues = {
  first_name: " Ada ",
  last_name: "Lovelace",
  email: "ada@example.com",
  phone: "555-0100",
  title: "Analyst",
  location: "London",
  linkedin_url: "https://linkedin.com/in/ada",
  status: "active",
  category: "Journalist",
  party_affiliation: "Independent",
  us_state: "CA",
  principal: "Sen. Jane Smith",
  principal_contact_id: "official-1",
  owner_ids: ["u1", "u2"],
  source: "manual",
  notes: "Met at conference",
  organization_id: "org-1",
  organization_name: "Acme",
};

const ORGANIZATION: OrganizationEditValues = {
  name: " Acme ",
  website: "https://acme.test",
  type: "partner",
  sector: "Energy",
  location: "Berlin",
  size: "50",
  notes: "Key partner",
};

describe("nullableText", () => {
  it("trims non-empty text", () => {
    expect(nullableText("  Journalist ")).toBe("Journalist");
  });

  it("maps empty and whitespace-only text to null", () => {
    expect(nullableText("")).toBeNull();
    expect(nullableText("   ")).toBeNull();
  });
});

describe("buildContactPatchBody", () => {
  it("sends trimmed values and merges preserved owners", () => {
    expect(buildContactPatchBody(CONTACT, ["u2", "hidden"])).toEqual({
      first_name: "Ada",
      last_name: "Lovelace",
      email: "ada@example.com",
      phone: "555-0100",
      title: "Analyst",
      location: "London",
      linkedin_url: "https://linkedin.com/in/ada",
      status: "active",
      category: "Journalist",
      party_affiliation: "Independent",
      us_state: "CA",
      principal: "Sen. Jane Smith",
      principal_contact_id: "official-1",
      owner_ids: ["u1", "u2", "hidden"],
      source: "manual",
      notes: "Met at conference",
      organization_id: "org-1",
    });
  });

  it("sends explicit nulls for cleared optional text so PATCH clears them", () => {
    const cleared: ContactEditValues = {
      ...CONTACT,
      email: "",
      phone: " ",
      title: "",
      location: "",
      linkedin_url: "",
      category: "",
      party_affiliation: "",
      us_state: "",
      principal: "",
      principal_contact_id: "",
      notes: "  ",
      organization_id: "",
    };
    const body = buildContactPatchBody(cleared, []);
    // Round-trip through JSON: undefined keys would vanish, nulls survive.
    const sent = JSON.parse(JSON.stringify(body));
    for (const key of [
      "email",
      "phone",
      "title",
      "location",
      "linkedin_url",
      "category",
      "party_affiliation",
      "us_state",
      "principal",
      "principal_contact_id",
      "notes",
      "organization_id",
    ]) {
      expect(sent).toHaveProperty(key, null);
    }
  });

  it("omits an unset source instead of sending null", () => {
    const body = buildContactPatchBody({ ...CONTACT, source: "" }, []);
    expect(JSON.parse(JSON.stringify(body))).not.toHaveProperty("source");
  });
});

describe("buildOrganizationPatchBody", () => {
  it("sends trimmed values", () => {
    expect(buildOrganizationPatchBody(ORGANIZATION)).toEqual({
      name: "Acme",
      website: "https://acme.test",
      type: "partner",
      sector: "Energy",
      location: "Berlin",
      size: "50",
      notes: "Key partner",
    });
  });

  it("sends explicit nulls for cleared optional text", () => {
    const body = buildOrganizationPatchBody({
      ...ORGANIZATION,
      website: "",
      sector: "",
      location: " ",
      size: "",
      notes: "",
    });
    const sent = JSON.parse(JSON.stringify(body));
    for (const key of ["website", "sector", "location", "size", "notes"]) {
      expect(sent).toHaveProperty(key, null);
    }
  });

  it("omits an unset type instead of sending null", () => {
    const body = buildOrganizationPatchBody({ ...ORGANIZATION, type: "" });
    expect(JSON.parse(JSON.stringify(body))).not.toHaveProperty("type");
  });
});
