import { render, screen } from "@tests/setup/test-utils";
import { RenderType } from "@/app/app/message/messageComponents/interfaces";
import { CrmToolRenderer } from "@/app/app/message/messageComponents/timeline/renderers/crm/CrmToolRenderer";
import type {
  CalendarToolPacket,
  CrmToolPacket,
} from "@/app/app/services/streamingModels";
import type { JsonObject } from "@/lib/json";

const placement = { turn_index: 0, tab_index: 0 };

function crmGetPackets(payload: JsonObject | null): CrmToolPacket[] {
  const start: CrmToolPacket = {
    placement,
    obj: { type: "crm_get_tool_start" },
  };
  if (payload === null) {
    return [start];
  }
  return [start, { placement, obj: { type: "crm_get_tool_delta", payload } }];
}

function renderTool(packets: (CrmToolPacket | CalendarToolPacket)[]) {
  return render(
    <CrmToolRenderer
      packets={packets}
      state={{}}
      onComplete={() => {}}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen
    >
      {(results) => (
        <div>
          {results.map((result, index) => (
            <div key={index}>{result.content}</div>
          ))}
        </div>
      )}
    </CrmToolRenderer>
  );
}

describe("CrmToolRenderer", () => {
  it("shows a failed call's whole error as an error row", () => {
    // Longer than the 160 characters a payload field shows.
    const message = `Attendees could not be resolved: ${"x".repeat(200)}`;
    renderTool(crmGetPackets({ error: message }));

    expect(screen.getByText("Error")).toBeInTheDocument();
    const row = screen.getByText(message);
    expect(row.closest(".bg-status-error-01")).not.toBeNull();
    expect(
      screen.queryByText("No tool payload returned.")
    ).not.toBeInTheDocument();
  });

  it("shows a Calendar Search error the same way", () => {
    renderTool([
      { placement, obj: { type: "calendar_search_tool_start" } },
      {
        placement,
        obj: {
          type: "calendar_search_tool_delta",
          payload: { error: "Please provide at least one filter." },
        },
      },
    ]);

    expect(
      screen.getByText("Please provide at least one filter.")
    ).toBeInTheDocument();
  });

  it("still lists the fields of a successful payload", () => {
    renderTool(crmGetPackets({ status: "ok", entity_type: "contact" }));

    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
  });

  it("falls back when the call ended without a delta", () => {
    renderTool(crmGetPackets(null));

    expect(screen.getByText("No tool payload returned.")).toBeInTheDocument();
  });
});
