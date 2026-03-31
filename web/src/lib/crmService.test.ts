import {
  deleteCrmContact,
  deleteCrmInteraction,
  deleteCrmOrganization,
  deleteContactProfilePicture,
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
    expect(request?.body).toBeInstanceOf(FormData);
    expect((request?.body as FormData).get("file")).toBe(file);
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
