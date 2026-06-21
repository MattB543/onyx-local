import {
  CRM_SORT_OPTIONS,
  DEFAULT_CRM_SORT_VALUE,
  sortValueToParams,
} from "./crmOptions";

describe("CRM_SORT_OPTIONS", () => {
  it("has exactly four options with the expected values and labels", () => {
    expect(CRM_SORT_OPTIONS).toEqual([
      { value: "created_asc", label: "Created asc" },
      { value: "created_desc", label: "Created desc" },
      { value: "updated_asc", label: "Updated asc" },
      { value: "updated_desc", label: "Updated desc" },
    ]);
  });

  it("defaults to updated_desc to preserve current ordering", () => {
    expect(DEFAULT_CRM_SORT_VALUE).toBe("updated_desc");
  });
});

describe("sortValueToParams", () => {
  it("maps created_asc", () => {
    expect(sortValueToParams("created_asc")).toEqual({
      sortBy: "created_at",
      sortDir: "asc",
    });
  });

  it("maps created_desc", () => {
    expect(sortValueToParams("created_desc")).toEqual({
      sortBy: "created_at",
      sortDir: "desc",
    });
  });

  it("maps updated_asc", () => {
    expect(sortValueToParams("updated_asc")).toEqual({
      sortBy: "updated_at",
      sortDir: "asc",
    });
  });

  it("maps updated_desc", () => {
    expect(sortValueToParams("updated_desc")).toEqual({
      sortBy: "updated_at",
      sortDir: "desc",
    });
  });
});
