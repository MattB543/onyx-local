import { dateRangeToParams } from "./CrmDateRangeFilter";

describe("dateRangeToParams", () => {
  const from = new Date(2026, 0, 1, 9, 30); // Jan 1 2026, local
  const to = new Date(2026, 0, 31, 9, 30); // Jan 31 2026, local

  it("maps field=created to only created_* keys", () => {
    const result = dateRangeToParams({ field: "created", from, to });
    expect(result.created_after).toBeDefined();
    expect(result.created_before).toBeDefined();
    expect(result.updated_after).toBeUndefined();
    expect(result.updated_before).toBeUndefined();
  });

  it("maps field=updated to only updated_* keys", () => {
    const result = dateRangeToParams({ field: "updated", from, to });
    expect(result.updated_after).toBeDefined();
    expect(result.updated_before).toBeDefined();
    expect(result.created_after).toBeUndefined();
    expect(result.created_before).toBeUndefined();
  });

  it("returns undefined bounds when from/to are null", () => {
    const result = dateRangeToParams({
      field: "created",
      from: null,
      to: null,
    });
    expect(result.created_after).toBeUndefined();
    expect(result.created_before).toBeUndefined();
  });

  it("maps the 'from' bound to the start of the local day (00:00:00.000)", () => {
    const result = dateRangeToParams({ field: "created", from, to: null });
    const parsed = new Date(result.created_after as string);
    expect(parsed.getHours()).toBe(0);
    expect(parsed.getMinutes()).toBe(0);
    expect(parsed.getSeconds()).toBe(0);
    expect(parsed.getMilliseconds()).toBe(0);
    expect(parsed.getFullYear()).toBe(2026);
    expect(parsed.getMonth()).toBe(0);
    expect(parsed.getDate()).toBe(1);
  });

  it("maps the 'to' bound to the end of the local day (23:59:59.999)", () => {
    const result = dateRangeToParams({ field: "created", from: null, to });
    const parsed = new Date(result.created_before as string);
    expect(parsed.getHours()).toBe(23);
    expect(parsed.getMinutes()).toBe(59);
    expect(parsed.getSeconds()).toBe(59);
    expect(parsed.getMilliseconds()).toBe(999);
    expect(parsed.getFullYear()).toBe(2026);
    expect(parsed.getMonth()).toBe(0);
    expect(parsed.getDate()).toBe(31);
  });

  it("emits valid ISO 8601 strings", () => {
    const result = dateRangeToParams({ field: "updated", from, to });
    expect(result.updated_after).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/
    );
    expect(result.updated_before).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/
    );
  });
});
