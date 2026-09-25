/**
 * The error a failed "Retry with" leaves at the end of the chat pages back to
 * the turn's earlier answers.
 */
import React from "react";
import { fireEvent, render, screen, within } from "@tests/setup/test-utils";
import ChatUI from "@/sections/chat/ChatUI";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { Message } from "@/app/app/interfaces";
import type { MinimalAgent } from "@/lib/agents/types";
import type { LlmManager } from "@/lib/hooks";

// The chat's messages render elsewhere; this covers only the chain-end error.
jest.mock("@/app/app/message/HumanMessage", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/app/message/messageComponents/AgentMessage", () => ({
  __esModule: true,
  default: ({ nodeId }: { nodeId: number }) => (
    <div data-testid="agent-message">{nodeId}</div>
  ),
}));
jest.mock("@/app/app/message/MultiModelResponseView", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/components/chat/DynamicBottomSpacer", () => ({
  __esModule: true,
  default: () => null,
}));

const SESSION_ID = "session-1";

function message(overrides: Partial<Message> & { nodeId: number }): Message {
  return {
    messageId: overrides.nodeId,
    message: "",
    type: "assistant",
    files: [],
    toolCall: null,
    parentNodeId: null,
    packets: [],
    ...overrides,
  };
}

// "Name one color." answered "Blue" (255), then a failed retry (256).
function loadFailedRetry(childrenNodeIds: number[]) {
  const tree = new Map<number, Message>([
    [
      253,
      message({
        nodeId: 253,
        type: "system",
        childrenNodeIds: [254],
        latestChildNodeId: 254,
      }),
    ],
    [
      254,
      message({
        nodeId: 254,
        type: "user",
        parentNodeId: 253,
        childrenNodeIds,
        latestChildNodeId: 256,
      }),
    ],
    [255, message({ nodeId: 255, parentNodeId: 254, message: "Blue" })],
    [
      256,
      message({
        nodeId: 256,
        type: "error",
        parentNodeId: 254,
        message: "API connection error",
      }),
    ],
  ]);
  const store = useChatSessionStore.getState();
  store.updateSessionMessageTree(SESSION_ID, tree);
  store.setUncaughtError(SESSION_ID, "API connection error");
}

function renderChat(onMessageSelection: (nodeId: number) => void) {
  return render(
    <ChatUI
      activeAgent={{ id: 0 } as MinimalAgent}
      llmManager={{ llmProviders: [], currentLlm: {} } as unknown as LlmManager}
      setPresentingDocument={jest.fn()}
      onMessageSelection={onMessageSelection}
      stopGenerating={jest.fn()}
      onSubmit={jest.fn()}
      deepResearchEnabled={false}
      currentMessageFiles={[]}
      onResubmit={jest.fn()}
    />
  );
}

beforeEach(() => {
  useChatSessionStore.setState({ currentSessionId: null, sessions: new Map() });
  useChatSessionStore.getState().setCurrentSession(SESSION_ID);
});

describe("chain-end error switcher", () => {
  it("pages from a failed retry back to the earlier answer", () => {
    loadFailedRetry([255, 256]);
    const onMessageSelection = jest.fn((nodeId: number) => {
      const store = useChatSessionStore.getState();
      const tree = new Map(store.sessions.get(SESSION_ID)!.messageTree);
      tree.set(254, { ...tree.get(254)!, latestChildNodeId: nodeId });
      store.updateSessionMessageTree(SESSION_ID, tree);
    });
    renderChat(onMessageSelection);

    const switcher = screen.getByTestId("ChatUI/error-switcher");
    expect(switcher).toHaveTextContent("2/2");
    const [previous] = within(switcher).getAllByRole("button");
    fireEvent.click(previous!);

    expect(onMessageSelection).toHaveBeenCalledWith(255);
    // The earlier answer renders, not the retry's error.
    expect(
      useChatSessionStore.getState().sessions.get(SESSION_ID)?.uncaughtError
    ).toBeNull();
    expect(screen.getByTestId("agent-message")).toHaveTextContent("255");
    expect(screen.queryByTestId("ChatUI/error-switcher")).toBeNull();
  });

  it("has no switcher after a failed send", () => {
    loadFailedRetry([256]);
    renderChat(jest.fn());

    expect(screen.getByText("API connection error")).toBeInTheDocument();
    expect(screen.queryByTestId("ChatUI/error-switcher")).toBeNull();
  });
});
