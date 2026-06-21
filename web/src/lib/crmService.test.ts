import {
  deleteCrmContact,
  deleteCrmInteraction,
  deleteCrmOrganization,
  deleteContactProfilePicture,
  listCrmContacts,
  listCrmOrganizations,
  uploadContactProfilePicture,
} from "@/app/app/crm/crmService";

describe("CRM profile picture service", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  test("uploadContactProfilePicture posts form data to the upload endpoint", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ file_id: "file-123" }),
    } as Response);

    const file = new File(["avatar"], "avatar.png", { type: "image/png" });
    const result = await uploadContactProfilePicture("contact-123", file);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/user/crm/contacts/contact-123/upload-profile-picture",
      expect.objectContaining({
        method: "POST",
      })
    );

    const request = fetchSpy.mock.calls[0][1];
    expect(request).toBeDefined();
    const body = request!.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("file")).toBe(file);
    expect(result).toEqual({ file_id: "file-123" });
  });

  test("uploadContactProfilePicture throws when the upload fails", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 413,
    } as Response);

    const file = new File(["avatar"], "avatar.png", { type: "image/png" });

    await expect(
      uploadContactProfilePicture("contact-123", file)
    ).rejects.toThrow(
      "Upload CRM contact profile picture failed (Status: 413)"
    );
  });

  test("deleteContactProfilePicture sends a delete request to the profile-picture endpoint", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
    } as Response);

    await expect(
      deleteContactProfilePicture("contact-123")
    ).resolves.toBeUndefined();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/user/crm/contacts/contact-123/profile-picture",
      { method: "DELETE" }
    );
  });

  test("deleteCrmContact sends a delete request to the contact endpoint", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
    } as Response);

    await expect(deleteCrmContact("contact-123")).resolves.toBeUndefined();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/user/crm/contacts/contact-123",
      {
        method: "DELETE",
      }
    );
  });

  test("deleteCrmContact throws when the delete fails", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 403,
    } as Response);

    await expect(deleteCrmContact("contact-123")).rejects.toThrow(
      "Delete CRM contact failed (Status: 403)"
    );
  });

  test("deleteCrmOrganization sends a delete request to the organization endpoint", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
    } as Response);

    await expect(
      deleteCrmOrganization("organization-123")
    ).resolves.toBeUndefined();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/user/crm/organizations/organization-123",
      {
        method: "DELETE",
      }
    );
  });

  test("deleteCrmInteraction sends a delete request to the interaction endpoint", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
    } as Response);

    await expect(
      deleteCrmInteraction("interaction-123")
    ).resolves.toBeUndefined();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/user/crm/interactions/interaction-123",
      {
        method: "DELETE",
      }
    );
  });
});

describe("CRM list filter query params", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest.spyOn(global, "fetch");
    fetchSpy.mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total_items: 0 }),
    } as Response);
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  function calledUrl(): string {
    return fetchSpy.mock.calls[0][0] as string;
  }

  test("listCrmContacts emits tag_ids (repeated), date range, sort_by and sort_dir", async () => {
    await listCrmContacts({
      tag_ids: ["a", "b"],
      created_after: "2026-01-01T00:00:00.000Z",
      created_before: "2026-01-31T23:59:59.999Z",
      sort_by: "created_at",
      sort_dir: "asc",
    });

    const url = calledUrl();
    expect(url).toContain("/api/user/crm/contacts?");
    expect(url).toContain("tag_ids=a");
    expect(url).toContain("tag_ids=b");
    expect(url).toContain("created_after=2026-01-01T00%3A00%3A00.000Z");
    expect(url).toContain("created_before=2026-01-31T23%3A59%3A59.999Z");
    expect(url).toContain("sort_by=created_at");
    expect(url).toContain("sort_dir=asc");
  });

  test("listCrmContacts emits updated_* date params when provided", async () => {
    await listCrmContacts({
      updated_after: "2026-02-01T00:00:00.000Z",
      updated_before: "2026-02-28T23:59:59.999Z",
      sort_by: "updated_at",
      sort_dir: "desc",
    });

    const url = calledUrl();
    expect(url).toContain("updated_after=2026-02-01T00%3A00%3A00.000Z");
    expect(url).toContain("updated_before=2026-02-28T23%3A59%3A59.999Z");
    expect(url).toContain("sort_by=updated_at");
    expect(url).toContain("sort_dir=desc");
    expect(url).not.toContain("created_after");
  });

  test("listCrmOrganizations emits tag_ids (repeated), date range, sort_by and sort_dir", async () => {
    await listCrmOrganizations({
      tag_ids: ["x", "y"],
      updated_after: "2026-03-01T00:00:00.000Z",
      updated_before: "2026-03-31T23:59:59.999Z",
      sort_by: "updated_at",
      sort_dir: "desc",
    });

    const url = calledUrl();
    expect(url).toContain("/api/user/crm/organizations?");
    expect(url).toContain("tag_ids=x");
    expect(url).toContain("tag_ids=y");
    expect(url).toContain("updated_after=2026-03-01T00%3A00%3A00.000Z");
    expect(url).toContain("updated_before=2026-03-31T23%3A59%3A59.999Z");
    expect(url).toContain("sort_by=updated_at");
    expect(url).toContain("sort_dir=desc");
  });

  test("undefined filter params are omitted from the query string", async () => {
    await listCrmContacts({ q: "alice" });

    const url = calledUrl();
    expect(url).toContain("q=alice");
    expect(url).not.toContain("tag_ids");
    expect(url).not.toContain("created_after");
    expect(url).not.toContain("sort_dir");
  });
});
