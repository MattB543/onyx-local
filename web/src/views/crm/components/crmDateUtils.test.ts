import {
  fromDatetimeLocalInputValue,
  toDatetimeLocalInputValue,
} from "./crmDateUtils";

describe("toDatetimeLocalInputValue", () => {
  it("returns empty string for null/undefined/empty", () => {
    expect(toDatetimeLocalInputValue(null)).toBe("");
    expect(toDatetimeLocalInputValue(undefined)).toBe("");
    expect(toDatetimeLocalInputValue("")).toBe("");
  });

  it("returns empty string for an invalid date", () => {
    expect(toDatetimeLocalInputValue("not-a-date")).toBe("");
  });

  it("formats a datetime as local wall-clock YYYY-MM-DDTHH:mm", () => {
    // Build an ISO string from a known local datetime so the test is
    // independent of the machine timezone.
    const local = new Date(2024, 0, 2, 15, 4); // Jan 2 2024, 15:04 local
    const result = toDatetimeLocalInputValue(local.toISOString());
    expect(result).toBe("2024-01-02T15:04");
  });
});

describe("fromDatetimeLocalInputValue", () => {
  it("returns null for empty input", () => {
    expect(fromDatetimeLocalInputValue("")).toBeNull();
  });

  it("returns null for an invalid input", () => {
    expect(fromDatetimeLocalInputValue("not-a-date")).toBeNull();
  });

  it("converts a local datetime-local value to an ISO/UTC string", () => {
    const iso = fromDatetimeLocalInputValue("2024-01-02T15:04");
    expect(iso).not.toBeNull();
    // The produced ISO string should parse back to the same wall-clock time.
    const parsed = new Date(iso as string);
    expect(parsed.getFullYear()).toBe(2024);
    expect(parsed.getMonth()).toBe(0);
    expect(parsed.getDate()).toBe(2);
    expect(parsed.getHours()).toBe(15);
    expect(parsed.getMinutes()).toBe(4);
  });
});

describe("round-trip", () => {
  it("preserves wall-clock time through to/from conversion", () => {
    const local = new Date(2023, 6, 14, 9, 30); // Jul 14 2023, 09:30 local
    const inputValue = toDatetimeLocalInputValue(local.toISOString());
    const iso = fromDatetimeLocalInputValue(inputValue);
    const roundTripped = toDatetimeLocalInputValue(iso);
    expect(roundTripped).toBe(inputValue);
  });
});
