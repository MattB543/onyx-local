import { findRenderer } from "./renderMessageComponent";
import { CrmToolRenderer } from "./timeline/renderers/crm/CrmToolRenderer";
import { ReasoningRenderer } from "./timeline/renderers/reasoning/ReasoningRenderer";
import { Packet, PacketType } from "../../services/streamingModels";

function packet(type: PacketType): Packet {
  return {
    placement: { turn_index: 0, tab_index: 0 },
    obj: { type },
  } as unknown as Packet;
}

const CRM_START_TYPES: [string, PacketType][] = [
  ["crm search", PacketType.CRM_SEARCH_TOOL_START],
  ["crm create", PacketType.CRM_CREATE_TOOL_START],
  ["crm update", PacketType.CRM_UPDATE_TOOL_START],
  ["crm log interaction", PacketType.CRM_LOG_INTERACTION_TOOL_START],
  ["crm list", PacketType.CRM_LIST_TOOL_START],
  ["crm get", PacketType.CRM_GET_TOOL_START],
  ["calendar search", PacketType.CALENDAR_SEARCH_TOOL_START],
];

describe("findRenderer - CRM/Calendar tools", () => {
  it.each(CRM_START_TYPES)(
    "returns CrmToolRenderer for a %s start packet",
    (_label, startType) => {
      expect(findRenderer({ packets: [packet(startType)] })).toBe(
        CrmToolRenderer
      );
    }
  );

  it.each(CRM_START_TYPES)(
    "returns CrmToolRenderer for a completed %s group",
    (_label, startType) => {
      const deltaType = `${startType.replace(
        /_start$/,
        ""
      )}_delta` as PacketType;
      const packets = [
        packet(startType),
        packet(deltaType),
        packet(PacketType.SECTION_END),
      ];
      expect(findRenderer({ packets })).toBe(CrmToolRenderer);
    }
  );

  it("still returns ReasoningRenderer for a SECTION_END-only group", () => {
    expect(findRenderer({ packets: [packet(PacketType.SECTION_END)] })).toBe(
      ReasoningRenderer
    );
  });

  it("still returns ReasoningRenderer for a reasoning group", () => {
    const packets = [
      packet(PacketType.REASONING_START),
      packet(PacketType.REASONING_DELTA),
      packet(PacketType.SECTION_END),
    ];
    expect(findRenderer({ packets })).toBe(ReasoningRenderer);
  });
});
