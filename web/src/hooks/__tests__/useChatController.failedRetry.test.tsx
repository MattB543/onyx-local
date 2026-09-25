/**
 * Controller-level tests for "Retry with" (a regeneration) and the send that
 * follows it: after a failed retry the send continues from the earlier
 * answer, never as a regeneration of the user message and never from a node
 * off the backend's mainline.
 */
import React, { PropsWithChildren } from "react";
import { act, renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReadonlyURLSearchParams } from "next/navigation";
import englishMessages from "@/i18n/messages/en.json";
import useChatController from "@/hooks/useChatController";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { BackendMessage, ChatFileType, Message } from "@/app/app/interfaces";
import {
  patchMessageToBeLatest,
  processRawChatHistory,
  type PacketType,
  type SendMessageParams,
} from "@/app/app/services/lib";
import { enqueueBranchSelection } from "@/app/app/services/branchSelection";
import {
  getLatestMessageChain,
  setMessageAsLatest,
} from "@/app/app/services/messageTree";
import type { LlmManager } from "@/lib/hooks";
import type { ProjectFile } from "@/lib/projects/types";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";

type SendMessageImpl = (
  params: SendMessageParams
) => AsyncGenerator<PacketType, void, unknown>;

const mockSendMessage = jest.fn<
  AsyncGenerator<PacketType, void, unknown>,
  [SendMessageParams]
>();

jest.mock("@/app/app/services/lib", () => ({
  ...jest.requireActual("@/app/app/services/lib"),
  sendMessage: (params: SendMessageParams) => mockSendMessage(params),
  createChatSession: jest.fn(),
  updateLlmOverrideForChatSession: jest.fn(),
  nameChatSession: jest.fn().mockResolvedValue({ ok: true }),
  getAvailableContextTokens: jest.fn().mockResolvedValue(null),
}));

jest.mock("next/navigation", () => ({
  usePathname: () => "/app",
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock("@/hooks/useChatSessions", () => ({
  __esModule: true,
  default: () => ({
    refreshChatSessions: jest.fn(),
    addPendingChatSession: jest.fn(),
  }),
}));

jest.mock("@/lib/agents/hooks", () => ({
  ...jest.requireActual("@/lib/agents/hooks"),
  usePinnedAgents: () => ({ pinnedAgents: [], togglePinnedAgent: jest.fn() }),
}));

jest.mock("@/lib/projects/providers", () => ({
  ...jest.requireActual("@/lib/projects/providers"),
  useProjectsContext: () => ({
    fetchProjects: jest.fn().mockResolvedValue([]),
    refreshRecentFiles: jest.fn().mockResolvedValue(undefined),
    beginChatUpload: jest.fn(),
    beginUpload: jest.fn(),
    setCurrentMessageFiles: jest.fn(),
  }),
}));

jest.mock("@/lib/projects/hooks", () => ({
  ...jest.requireActual("@/lib/projects/hooks"),
  useActiveProject: () => null,
}));

jest.mock("@/providers/IncognitoProvider", () => ({
  ...jest.requireActual("@/providers/IncognitoProvider"),
  useIncognito: () => ({
    incognitoEnabledRef: { current: false },
    incognitoSessionId: null,
  }),
}));

jest.mock("@/lib/connectors/hooks", () => ({
  ...jest.requireActual("@/lib/connectors/hooks"),
  useAvailableSources: () => ({ availableSources: [], settled: true }),
}));

const SESSION_ID = "session-1";

const llmManager = {
  currentLlm: {
    name: "default",
    provider: "anthropic",
    modelName: "opus-4-6",
    modelConfigurationId: null,
  },
  temperature: 0,
  hasTemperatureOverride: false,
  persistOverrides: jest.fn().mockResolvedValue(undefined),
  // "Retry with" names a model by provider and model name, without an id.
  llmProviders: [
    {
      name: "bedrock",
      provider: "bedrock",
      model_configurations: [
        { id: 7, name: "5-5", effectiveDisplayName: "Claude Opus 5.5 (us)" },
      ],
    },
  ],
  hasAnyProvider: false,
  updateImageFilesPresent: jest.fn(),
} as unknown as LlmManager;

const toolConfiguration = {
  filters: {
    selectedSources: null,
    documentSets: [],
    tags: [],
    timeRange: null,
  },
  forcedToolId: null,
  disabledToolIds: [],
  handOffTo: jest.fn(),
} as unknown as ToolConfigurationHandle;

const RETRY_MODEL = { name: "bedrock", provider: "bedrock", modelName: "5-5" };

function raw(
  id: number,
  type: string,
  parent: number | null,
  latest: number | null,
  extra: Partial<BackendMessage> = {}
): BackendMessage {
  // SAFETY: tests fill only the fields processRawChatHistory reads.
  return {
    message_id: id,
    message_type: type,
    parent_message: parent,
    latest_child_message: latest,
    message: `msg ${id}`,
    time_sent: `2026-09-24T14:00:00.${id}Z`,
    files: [],
    error: null,
    ...extra,
  } as unknown as BackendMessage;
}

function loadTree(messages: BackendMessage[]) {
  useChatSessionStore.getState().updateSessionMessageTree(
    SESSION_ID,
    processRawChatHistory(
      messages,
      messages.map(() => [])
    )
  );
}

// Single-model turn as the backend returns it: "Name one color." -> "Blue".
function loadSingleModelTurn(userExtra: Partial<BackendMessage> = {}) {
  loadTree([
    raw(253, "system", null, 254),
    raw(254, "user", 253, 255, userExtra),
    raw(255, "assistant", 254, null, { model_display_name: "opus-4-6" }),
  ]);
}

// Multi-model turn: both replies were reserved in one transaction.
function loadMultiModelTurn() {
  const t = "2026-09-24T14:08:24.686Z";
  loadTree([
    raw(196, "system", null, 197),
    raw(197, "user", 196, 199),
    raw(198, "assistant", 197, null, {
      model_display_name: "Sonnet 4.6",
      time_sent: t,
    }),
    raw(199, "assistant", 197, null, {
      model_display_name: "Opus 4.6",
      time_sent: t,
    }),
  ]);
}

function packet(obj: Record<string, unknown>): PacketType {
  // SAFETY: test packets carry only the fields the controller reads.
  return {
    placement: { turn_index: 0, model_index: 0 },
    obj,
  } as unknown as PacketType;
}

function idInfo(userId: number, assistantId: number): PacketType {
  return {
    type: "message_id_info",
    user_message_id: userId,
    reserved_assistant_message_id: assistantId,
  } as PacketType;
}

function failingRetry(userId: number, assistantId: number): SendMessageImpl {
  return async function* () {
    yield idInfo(userId, assistantId);
    yield {
      error: "API connection error",
      stack_trace: null,
      error_code: "CONNECTION_ERROR",
      is_retryable: true,
      details: { model_index: 0 },
    } as unknown as PacketType;
  };
}

function answering(userId: number, assistantId: number): SendMessageImpl {
  return async function* () {
    yield idInfo(userId, assistantId);
    yield packet({ type: "message_start", content: "Answer" });
    yield packet({ type: "stop" });
  };
}

// Captures the next send's request.
function nextSend(impl: (userId: number, id: number) => SendMessageImpl) {
  const captured: { params?: SendMessageParams } = {};
  mockSendMessage.mockImplementationOnce((params) => {
    captured.params = params;
    return impl(900, 901)(params);
  });
  return captured;
}

function sessionTree(): Map<number, Message> {
  return (
    useChatSessionStore.getState().sessions.get(SESSION_ID)?.messageTree ??
    new Map()
  );
}

function fetchCalls(path: string): unknown[] {
  return (global.fetch as jest.Mock).mock.calls
    .filter(([url]) => url === path)
    .map(([, init]) => JSON.parse((init as RequestInit).body as string));
}

function renderController() {
  const wrapper = ({ children }: PropsWithChildren) => (
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      {children}
    </NextIntlClientProvider>
  );
  return renderHook(
    () =>
      useChatController({
        llmManager,
        toolConfiguration,
        activeAgent: undefined,
        availableAgents: [],
        existingChatSessionId: SESSION_ID,
        selectedDocuments: [],
        // SAFETY: the controller only calls get() and toString().
        searchParams:
          new URLSearchParams() as unknown as ReadonlyURLSearchParams,
        resetInputBar: jest.fn(),
      }),
    { wrapper }
  );
}

type Controller = ReturnType<typeof renderController>["result"];

// "Retry with" as ChatUI's regenerator issues it.
async function retryWith(
  result: Controller,
  userId: number,
  replyId: number,
  impl: SendMessageImpl
) {
  const user = sessionTree().get(userId)!;
  mockSendMessage.mockImplementationOnce(impl);
  await act(async () => {
    await result.current.onSubmit({
      message: user.message,
      currentMessageFiles: [],
      deepResearch: false,
      modelOverride: RETRY_MODEL,
      messageIdToResend: user.messageId,
      regenerationRequest: { messageId: replyId, parentMessage: user },
    });
  });
}

async function send(result: Controller, message: string) {
  await act(async () => {
    await result.current.onSubmit({
      message,
      currentMessageFiles: [],
      deepResearch: false,
    });
  });
}

function nodeByText(text: string): Message | undefined {
  return Array.from(sessionTree().values()).find((m) => m.message === text);
}

beforeEach(() => {
  mockSendMessage.mockReset();
  global.fetch = jest.fn().mockResolvedValue({ ok: true });
  useChatSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
  });
  useChatSessionStore.getState().setCurrentSession(SESSION_ID);
});

describe("Retry with", () => {
  it("regenerates from the user message and says so", async () => {
    loadSingleModelTurn();
    const { result } = renderController();
    const captured: { params?: SendMessageParams } = {};
    await retryWith(result, 254, 255, (params) => {
      captured.params = params;
      return answering(254, 256)(params);
    });

    expect(captured.params?.parentMessageId).toBe(254);
    expect(captured.params?.regenerate).toBe(true);
    // Saved on the reply, so its row and error text name the model.
    expect(captured.params?.modelDisplayName).toBe("Claude Opus 5.5 (us)");
  });

  it("keeps the saved error row's id after a failed retry", async () => {
    loadSingleModelTurn();
    const { result } = renderController();
    await retryWith(result, 254, 255, failingRetry(254, 256));

    const chain = getLatestMessageChain(sessionTree());
    expect(chain.map((m) => [m.messageId, m.type])).toEqual([
      [254, "user"],
      [256, "error"],
    ]);
    expect(sessionTree().get(254)?.childrenNodeIds).toHaveLength(2);
  });

  it("keeps the user message's attachments and replies", async () => {
    loadSingleModelTurn({
      files: [{ id: "file-1", type: ChatFileType.DOCUMENT, name: "a.txt" }],
    });
    const { result } = renderController();
    await retryWith(result, 254, 255, answering(254, 256));

    const user = sessionTree().get(254)!;
    expect(user.files.map((f) => f.id)).toEqual(["file-1"]);
    expect(user.childrenNodeIds).toHaveLength(2);
    expect(sessionTree().get(user.latestChildNodeId!)?.messageId).toBe(256);
  });
});

describe("sending after a failed Retry with", () => {
  it("continues a single-model chat from the earlier answer", async () => {
    loadSingleModelTurn();
    const { result } = renderController();
    await retryWith(result, 254, 255, failingRetry(254, 256));

    const captured = nextSend(answering);
    await send(result, "Name another color.");

    // Before: parent 255 while the backend's mainline ran through 256.
    expect(captured.params?.parentMessageId).toBe(255);
    expect(captured.params?.regenerate).toBe(false);
    expect(fetchCalls("/api/chat/set-message-as-latest")).toEqual([
      { message_id: 255 },
    ]);
    const chain = getLatestMessageChain(sessionTree());
    expect(chain.map((m) => m.messageId)).toEqual([254, 255, 900, 901]);
    expect(chain[2]?.message).toBe("Name another color.");
    // The failed retry is still a sibling the pager can reach.
    expect(
      sessionTree()
        .get(254)
        ?.childrenNodeIds?.map((id) => sessionTree().get(id)?.messageId)
    ).toEqual([255, 256]);
  });

  it("continues a multi-model chat from a panel of the original group", async () => {
    loadMultiModelTurn();
    const { result } = renderController();
    await retryWith(result, 197, 198, failingRetry(197, 207));

    const captured = nextSend(answering);
    await send(result, "And one about penguins.");

    // Before: parent 197, which the backend took as a regeneration.
    expect(captured.params?.parentMessageId).toBe(199);
    expect(captured.params?.regenerate).toBe(false);
    expect(fetchCalls("/api/chat/set-preferred-response")).toEqual([
      { user_message_id: 197, preferred_response_id: 199 },
    ]);
    const penguin = nodeByText("And one about penguins.");
    expect(penguin?.parentNodeId).toBe(199);
    expect(sessionTree().get(197)?.childrenNodeIds).toHaveLength(3);
  });

  it("continues from the answer the pager went back to", async () => {
    loadSingleModelTurn();
    const { result } = renderController();
    await retryWith(result, 254, 255, answering(254, 256));
    // The pager's local switch; the PUT is fire-and-forget.
    act(() => {
      useChatSessionStore
        .getState()
        .updateSessionMessageTree(
          SESSION_ID,
          setMessageAsLatest(sessionTree(), 255)
        );
    });

    const captured = nextSend(answering);
    await send(result, "Name another color.");

    expect(captured.params?.parentMessageId).toBe(255);
    expect(nodeByText("Name another color.")?.parentNodeId).toBe(255);
  });

  it("continues from the answer the error's pager went back to", async () => {
    loadSingleModelTurn();
    const { result } = renderController();
    await retryWith(result, 254, 255, failingRetry(254, 256));
    act(() => {
      useChatSessionStore
        .getState()
        .updateSessionMessageTree(
          SESSION_ID,
          setMessageAsLatest(sessionTree(), 255)
        );
    });

    const captured = nextSend(answering);
    await send(result, "Name another color.");

    expect(captured.params?.parentMessageId).toBe(255);
    expect(captured.params?.regenerate).toBe(false);
    expect(nodeByText("Name another color.")?.parentNodeId).toBe(255);
  });

  it("continues from the group the error's pager went back to", async () => {
    loadMultiModelTurn();
    const { result } = renderController();
    await retryWith(result, 197, 198, failingRetry(197, 207));
    act(() => {
      useChatSessionStore
        .getState()
        .updateSessionMessageTree(
          SESSION_ID,
          setMessageAsLatest(sessionTree(), 198)
        );
    });

    const captured = nextSend(answering);
    await send(result, "And one about penguins.");

    // The side-by-side turn is unresolved, so the send assumes the first
    // model's panel (the last child), as for any follow-up.
    expect(captured.params?.parentMessageId).toBe(199);
    expect(fetchCalls("/api/chat/set-preferred-response")).toEqual([
      { user_message_id: 197, preferred_response_id: 199 },
    ]);
  });

  it("replaces a reloaded user message that never got a reply", async () => {
    loadTree([
      raw(1, "system", null, 2),
      raw(2, "user", 1, 3),
      raw(3, "assistant", 2, 4),
      raw(4, "user", 3, null),
    ]);
    const { result } = renderController();

    const captured = nextSend(answering);
    await send(result, "Try again.");

    // Before: parent 4, a user message, which regenerated its reply.
    expect(captured.params?.parentMessageId).toBe(3);
    expect(nodeByText("Try again.")?.parentNodeId).toBe(3);
    expect(sessionTree().get(3)?.childrenNodeIds).toHaveLength(2);
  });

  it("still drops a failed send before resending", async () => {
    loadTree([raw(10, "system", null, null)]);
    const { result } = renderController();
    mockSendMessage.mockImplementationOnce(failingRetry(11, 12));
    await send(result, "first");

    const captured = nextSend(answering);
    await send(result, "second");

    // The root, as the tree placed it; the backend starts over from it.
    expect(captured.params?.parentMessageId).toBe(10);
    expect(nodeByText("first")).toBeUndefined();
    expect(getLatestMessageChain(sessionTree()).map((m) => m.message)).toEqual([
      "second",
      "",
    ]);
  });
});

// Every web send states whether it regenerates. The backend rejects a new
// message (false) sent against a user message.
// Codex P1: a pager switch still in flight when the user sends must land
// before the send's own switch, or it moves the mainline off the new turn.
describe("branch switches and sends", () => {
  it("lands a pending pager switch before the fallback switch and the send", async () => {
    // A reloaded failed retry, viewed on the earlier answer 255.
    loadTree([
      raw(253, "system", null, 254),
      raw(254, "user", 253, 255),
      raw(255, "assistant", 254, null),
      raw(256, "assistant", 254, null, { error: "API connection error" }),
    ]);
    const { result } = renderController();
    const events: string[] = [];
    let releasePagerPut: () => void = () => {};
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(init.body as string) : {};
      events.push(`${url} ${body.message_id ?? ""}`.trim());
      if (body.message_id === 256) {
        return new Promise((resolve) => {
          releasePagerPut = () => {
            events.push("pager switch to 256 saved");
            resolve({ ok: true });
          };
        });
      }
      return Promise.resolve({ ok: true });
    }) as unknown as typeof fetch;

    // The pager goes to the error; its PUT is still pending.
    act(() => {
      useChatSessionStore
        .getState()
        .updateSessionMessageTree(
          SESSION_ID,
          setMessageAsLatest(sessionTree(), 256)
        );
    });
    void enqueueBranchSelection(SESSION_ID, () => patchMessageToBeLatest(256));

    mockSendMessage.mockImplementationOnce((params) => {
      events.push(`send after ${params.parentMessageId}`);
      return answering(900, 901)(params);
    });
    let sent: Promise<void> = Promise.resolve();
    act(() => {
      sent = result.current.onSubmit({
        message: "Name another color.",
        currentMessageFiles: [],
        deepResearch: false,
      });
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    // Nothing overtakes the pending pager switch.
    expect(events).toEqual(["/api/chat/set-message-as-latest 256"]);

    releasePagerPut();
    await act(async () => {
      await sent;
    });
    expect(events).toEqual([
      "/api/chat/set-message-as-latest 256",
      "pager switch to 256 saved",
      "/api/chat/set-message-as-latest 255",
      "send after 255",
    ]);
  });
});

describe("the regenerate flag", () => {
  it("is false for an edit, which resends from the user's parent", async () => {
    loadSingleModelTurn();
    const { result } = renderController();

    const captured = nextSend(answering);
    await act(async () => {
      await result.current.onSubmit({
        message: "Name one shape.",
        messageIdToResend: 254,
        currentMessageFiles: [],
        deepResearch: false,
      });
    });

    expect(captured.params?.parentMessageId).toBe(253);
    expect(captured.params?.regenerate).toBe(false);
  });

  it("is false for Resubmit after an error, which keeps the file", async () => {
    loadTree([raw(10, "system", null, null)]);
    const { result } = renderController();
    mockSendMessage.mockImplementationOnce(failingRetry(11, 12));
    await act(async () => {
      await result.current.onSubmit({
        message: "What does this file say?",
        currentMessageFiles: [
          {
            id: "user-file-1",
            file_id: "file-1",
            name: "qa-raw-a.txt",
            chat_file_type: ChatFileType.PLAIN_TEXT,
            attachment_source: "recent",
          } as unknown as ProjectFile,
        ],
        deepResearch: false,
      });
    });

    // As AppPage's Resubmit sends it.
    const captured = nextSend(answering);
    await act(async () => {
      await result.current.onSubmit({
        message: "What does this file say?",
        currentMessageFiles: [],
        deepResearch: false,
        messageIdToResend: 11,
      });
    });

    expect(captured.params?.regenerate).toBe(false);
    // The root: the resent message replaces the first one.
    expect(captured.params?.parentMessageId).toBe(10);
    expect(captured.params?.fileDescriptors?.map((f) => f.id)).toEqual([
      "file-1",
    ]);
  });

  it("is left to the backend for a seeded chat's first reply", async () => {
    loadTree([raw(1, "system", null, 2), raw(2, "user", 1, null)]);
    const { result } = renderController();

    const captured = nextSend(answering);
    await act(async () => {
      await result.current.onSubmit({
        message: "msg 2",
        isSeededChat: true,
        currentMessageFiles: [],
        deepResearch: false,
      });
    });

    expect(captured.params?.parentMessageId).toBe(2);
    expect(captured.params?.regenerate).toBeUndefined();
  });

  it("is false for a follow-up to a multi-model turn with a failed panel", async () => {
    loadTree([raw(1, "system", null, null)]);
    const { result } = renderController();
    mockSendMessage.mockImplementationOnce(async function* () {
      yield {
        type: "multi_model_message_id_info",
        user_message_id: 2,
        responses: [
          { message_id: 3, model_name: "Opus 4.6" },
          { message_id: 4, model_name: "Opus 5.5" },
        ],
      } as unknown as PacketType;
      yield {
        placement: { turn_index: 0, model_index: 0 },
        obj: { type: "message_start", content: "Three lighthouses" },
      } as unknown as PacketType;
      yield {
        error: "API connection error",
        is_retryable: true,
        details: { model_index: 1 },
      } as unknown as PacketType;
      yield packet({ type: "stop" });
    });
    await act(async () => {
      await result.current.onSubmit({
        message: "Name three lighthouses.",
        currentMessageFiles: [],
        deepResearch: false,
        selectedModels: [
          {
            name: "bedrock",
            provider: "bedrock",
            modelName: "opus-4-6",
            modelConfigurationId: 1,
            displayName: "Opus 4.6",
          },
          {
            name: "bedrock",
            provider: "bedrock",
            modelName: "opus-5-5",
            modelConfigurationId: 2,
            displayName: "Opus 5.5",
          },
        ],
      });
    });

    const captured = nextSend(answering);
    await send(result, "Which of those is the oldest?");

    // R4: the answer continues from the panel that succeeded.
    expect(captured.params?.parentMessageId).toBe(3);
    expect(captured.params?.regenerate).toBe(false);
    expect(nodeByText("Name three lighthouses.")?.messageId).toBe(2);
  });
});
