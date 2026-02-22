"use client";

import { JSX } from "react";

import { BlinkingDot } from "@/app/app/message/BlinkingDot";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import {
  CalendarToolPacket,
  CrmToolPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import Text from "@/refresh-components/texts/Text";

import { SvgUser } from "@opal/icons";

function getCrmToolLabel(packetType: PacketType): string {
  switch (packetType) {
    case PacketType.CRM_SEARCH_TOOL_START:
      return "CRM Search";
    case PacketType.CRM_CREATE_TOOL_START:
      return "CRM Create";
    case PacketType.CRM_UPDATE_TOOL_START:
      return "CRM Update";
    case PacketType.CRM_LOG_INTERACTION_TOOL_START:
      return "CRM Log Interaction";
    case PacketType.CALENDAR_SEARCH_TOOL_START:
      return "Calendar Search";
    default:
      return "CRM";
  }
}

function getDeltaType(startType: PacketType): PacketType | null {
  switch (startType) {
    case PacketType.CRM_SEARCH_TOOL_START:
      return PacketType.CRM_SEARCH_TOOL_DELTA;
    case PacketType.CRM_CREATE_TOOL_START:
      return PacketType.CRM_CREATE_TOOL_DELTA;
    case PacketType.CRM_UPDATE_TOOL_START:
      return PacketType.CRM_UPDATE_TOOL_DELTA;
    case PacketType.CRM_LOG_INTERACTION_TOOL_START:
      return PacketType.CRM_LOG_INTERACTION_TOOL_DELTA;
    case PacketType.CALENDAR_SEARCH_TOOL_START:
      return PacketType.CALENDAR_SEARCH_TOOL_DELTA;
    default:
      return null;
  }
}

function formatPayloadKey(key: string): string {
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function summarizePayloadValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "None";
  }
  if (typeof value === "string") {
    return value.length > 160 ? `${value.slice(0, 160)}...` : value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return "No items";
    }
    const preview = value
      .slice(0, 2)
      .map((item) => {
        if (item === null || item === undefined) {
          return "None";
        }
        if (typeof item === "string" || typeof item === "number") {
          return String(item);
        }
        if (typeof item === "object") {
          const objectItem = item as Record<string, unknown>;
          if (typeof objectItem["title"] === "string") {
            return objectItem["title"] as string;
          }
          if (typeof objectItem["name"] === "string") {
            return objectItem["name"] as string;
          }
          return "Item";
        }
        return "Item";
      })
      .join(", ");
    const remainder = value.length > 2 ? ` (+${value.length - 2} more)` : "";
    return `${preview}${remainder}`;
  }

  if (typeof value === "object") {
    const objectValue = value as Record<string, unknown>;
    if (typeof objectValue["title"] === "string") {
      return objectValue["title"] as string;
    }
    if (typeof objectValue["name"] === "string") {
      return objectValue["name"] as string;
    }
    return `${Object.keys(objectValue).length} fields`;
  }

  return String(value);
}

function renderPayload(payload: Record<string, unknown>): JSX.Element {
  const entries = Object.entries(payload);

  if (entries.length === 0) {
    return (
      <Text as="p" text03 className="text-sm">
        No tool payload returned.
      </Text>
    );
  }

  return (
    <div className="flex flex-col gap-1 rounded-08 border border-border-subtle p-2">
      {entries.map(([key, value]) => (
        <div
          key={key}
          className="flex items-start justify-between gap-4 rounded-06 bg-background-tint-01 px-2 py-1"
        >
          <Text as="p" secondaryBody text03 className="shrink-0">
            {formatPayloadKey(key)}
          </Text>
          <Text as="p" secondaryBody text02 className="text-right">
            {summarizePayloadValue(value)}
          </Text>
        </div>
      ))}
    </div>
  );
}

/**
 * CrmToolRenderer - Renders CRM built-in tool execution state.
 */
export const CrmToolRenderer: MessageRenderer<
  CrmToolPacket | CalendarToolPacket,
  Record<string, never>
> = ({ packets, stopPacketSeen, renderType, children }) => {
  const firstPacket = packets[0];
  const startType = firstPacket?.obj.type as PacketType | undefined;

  if (!startType) {
    return children([
      {
        icon: SvgUser,
        status: null,
        content: <div />,
        supportsCollapsible: false,
        timelineLayout: "timeline",
      },
    ]);
  }

  const deltaType = getDeltaType(startType);
  const label = getCrmToolLabel(startType);
  const deltaPacket =
    deltaType !== null
      ? packets.find((packet) => packet.obj.type === deltaType)
      : undefined;
  const payload =
    deltaPacket &&
    "payload" in deltaPacket.obj &&
    typeof deltaPacket.obj.payload === "object"
      ? deltaPacket.obj.payload
      : null;

  const content = payload ? (
    renderPayload(payload as Record<string, unknown>)
  ) : !stopPacketSeen ? (
    <BlinkingDot />
  ) : (
    <Text as="p" text03 className="text-sm">
      No tool payload returned.
    </Text>
  );

  if (renderType === RenderType.HIGHLIGHT) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: true,
        timelineLayout: "content",
        content: (
          <div className="flex flex-col">
            <Text as="p" text02 className="text-sm mb-1">
              {label}
            </Text>
            {content}
          </div>
        ),
      },
    ]);
  }

  return children([
    {
      icon: SvgUser,
      status: label,
      supportsCollapsible: true,
      timelineLayout: "timeline",
      content,
    },
  ]);
};
