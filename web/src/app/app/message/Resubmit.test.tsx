import { act, render, screen } from "@tests/setup/test-utils";
import { ErrorBanner } from "@/app/app/message/Resubmit";
import { RATE_LIMITED_ERROR_CODE } from "@/app/app/interfaces";

describe("rate-limit error banner", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-07-28T12:00:00Z"));
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test("updates when the reset time is reached", () => {
    render(
      <ErrorBanner
        error="You've reached the usage budget for your account."
        errorCode={RATE_LIMITED_ERROR_CODE}
        details={{ reset_at: "2026-07-28T12:00:30Z" }}
      />
    );

    expect(screen.getByText(/Resets in 1 minute/)).toBeInTheDocument();

    act(() => {
      jest.advanceTimersByTime(30_000);
    });

    expect(screen.getByText("You can try again now.")).toBeInTheDocument();
  });
});

describe("error banner heading", () => {
  const savedError =
    "Error from us.anthropic.claude-opus-5-5: API connection error: Failed to connect to the API.";

  test("a reloaded error gets the heading of its saved category", () => {
    render(<ErrorBanner error={savedError} />);
    expect(screen.getByText("Connection Error")).toBeInTheDocument();
  });

  test("a streamed error code wins over the text", () => {
    render(<ErrorBanner error={savedError} errorCode="PERMISSION_DENIED" />);
    expect(screen.getByText("Permission Denied")).toBeInTheDocument();
  });

  test("unknown text keeps the generic heading", () => {
    render(<ErrorBanner error="Something broke." />);
    expect(screen.getByText("Error")).toBeInTheDocument();
  });
});

describe("error banner resubmit", () => {
  const accessDenied =
    "Error from us.anthropic.claude-opus-5-5: Permission denied: Model access is denied.";

  test("a live access error keeps resubmit with a pick-another-model hint", () => {
    render(
      <ErrorBanner
        error="Permission denied: Model access is denied."
        errorCode="PERMISSION_DENIED"
        isRetryable={false}
        resubmit={() => {}}
      />
    );
    expect(
      screen.getByText("Pick another model, then try again.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeVisible();
  });

  test("the reloaded access error shows the same", () => {
    render(<ErrorBanner error={accessDenied} resubmit={() => {}} />);
    expect(
      screen.getByText("Pick another model, then try again.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeVisible();
  });

  test("other non-retryable errors still hide resubmit", () => {
    render(
      <ErrorBanner
        error="Context window exceeded: too long."
        errorCode="CONTEXT_TOO_LONG"
        isRetryable={false}
        resubmit={() => {}}
      />
    );
    expect(screen.queryByRole("button", { name: "Regenerate" })).toBeNull();
  });

  test("retryable errors keep the generic text", () => {
    render(
      <ErrorBanner
        error="API connection error: Failed to connect to the API."
        errorCode="CONNECTION_ERROR"
        resubmit={() => {}}
      />
    );
    expect(
      screen.getByText("There was an error with the response.")
    ).toBeInTheDocument();
  });
});
