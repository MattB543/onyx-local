/**
 * Controller-level tests for how a fresh send ends: a transport failure after
 * some models finished, a user stop whose STOP is lost, and an early EOF
 * followed by Resubmit.
 */
import React, { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReadonlyURLSearchParams } from "next/navigation";
import englishMessages from "@/i18n/messages/en.json";
import useChatController from "@/hooks/useChatController";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { ChatFileType, Message } from "@/app/app/interfaces";
import type { PacketType, SendMessageParams } from "@/app/app/services/lib";
import { SYSTEM_NODE_ID } from "@/app/app/services/messageTree";
import { UserFileStatus, type ProjectFile } from "@/lib/projects/types";
import type { LlmManager } from "@/lib/hooks";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import type { SelectedModel } from "@/sections/model-selector/MultiModelSelector";

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

const mockRefreshRecentFiles = jest.fn().mockResolvedValue(undefined);
jest.mock("@/lib/projects/providers", () => ({
  ...jest.requireActual("@/lib/projects/providers"),
  useProjectsContext: () => ({
    fetchProjects: jest.fn().mockResolvedValue([]),
    refreshRecentFiles: mockRefreshRecentFiles,
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
    modelName: "opus",
    modelConfigurationId: null,
  },
  temperature: 0,
  hasTemperatureOverride: false,
  persistOverrides: jest.fn().mockResolvedValue(undefined),
  llmProviders: [],
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

const models: SelectedModel[] = [
  {
    name: "a",
    provider: "anthropic",
    modelName: "model-a",
    modelConfigurationId: 1,
    displayName: "Model A",
  },
  {
    name: "b",
    provider: "openai",
    modelName: "model-b",
    modelConfigurationId: 2,
    displayName: "Model B",
  },
];

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve = () => {};
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function packet(modelIndex: number, obj: Record<string, unknown>): PacketType {
  // SAFETY: test packets carry only the fields the controller reads.
  return {
    placement: { turn_index: 0, model_index: modelIndex },
    obj,
  } as unknown as PacketType;
}

function sessionTree(): Map<number, Message> {
  return (
    useChatSessionStore.getState().sessions.get(SESSION_ID)?.messageTree ??
    new Map()
  );
}

function userNode(): Message | undefined {
  return Array.from(sessionTree().values()).find((m) => m.type === "user");
}

function replies(): Message[] {
  const user = userNode();
  return Array.from(sessionTree().values()).filter(
    (m) => user && m.parentNodeId === user.nodeId
  );
}

function reply(displayName: string): Message | undefined {
  return replies().find((m) => m.modelDisplayName === displayName);
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

// Model A answers and stops. Model B starts, then the transport fails once
// `failTransport` resolves.
function multiModelStreamThatFails(failTransport: Promise<void>) {
  const impl: SendMessageImpl = async function* () {
    yield {
      type: "multi_model_message_id_info",
      user_message_id: 10,
      responses: [
        { message_id: 11, model_name: "Model A" },
        { message_id: 12, model_name: "Model B" },
      ],
    };
    yield packet(0, { type: "message_start", content: "Answer A" });
    yield packet(0, { type: "stop" });
    yield packet(1, { type: "message_start", content: "Partial B" });
    await failTransport;
    throw new Error("network error");
  };
  mockSendMessage.mockImplementationOnce(impl);
}

beforeEach(() => {
  mockSendMessage.mockReset();
  mockRefreshRecentFiles.mockClear();
  global.fetch = jest.fn().mockResolvedValue({ ok: true });
  useChatSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
  });
  useChatSessionStore.getState().setCurrentSession(SESSION_ID);
});

describe("useChatController stream end", () => {
  it("errors only the unfinished panel when the transport fails", async () => {
    const failTransport = deferred();
    multiModelStreamThatFails(failTransport.promise);
    const { result } = renderController();

    let send: Promise<void> = Promise.resolve();
    act(() => {
      send = result.current.onSubmit({
        message: "question",
        currentMessageFiles: [],
        deepResearch: false,
        selectedModels: models,
      });
    });
    await waitFor(() =>
      expect(reply("Model B")?.packets.length ?? 0).toBeGreaterThan(0)
    );
    failTransport.resolve();
    await act(async () => {
      await send;
    });

    const a = reply("Model A");
    const b = reply("Model B");
    expect(a?.type).toBe("assistant");
    expect(a?.packets.some((p) => p.obj.type === "stop")).toBe(true);
    expect(b?.type).toBe("error");
    expect(b?.message).toBe("network error");
  });

  it("closes the unfinished panel as stopped after a user stop", async () => {
    const failTransport = deferred();
    multiModelStreamThatFails(failTransport.promise);
    const { result } = renderController();

    let send: Promise<void> = Promise.resolve();
    act(() => {
      send = result.current.onSubmit({
        message: "question",
        currentMessageFiles: [],
        deepResearch: false,
        selectedModels: models,
      });
    });
    await waitFor(() =>
      expect(reply("Model B")?.packets.length ?? 0).toBeGreaterThan(0)
    );
    await act(async () => {
      await result.current.stopGenerating();
    });
    failTransport.resolve();
    await act(async () => {
      await send;
    });

    const a = reply("Model A");
    const b = reply("Model B");
    expect(a?.type).toBe("assistant");
    expect(b?.type).toBe("assistant");
    expect(b?.packets.at(-1)?.obj).toEqual({
      type: "stop",
      stop_reason: "user_cancelled",
    });
  });

  it("keeps the user id and files after an early EOF, so Resubmit keeps them", async () => {
    const attachment: ProjectFile = {
      id: "user-file-1",
      name: "report.pdf",
      project_id: null,
      user_id: "user-1",
      file_id: "file-1",
      created_at: "2026-09-23T00:00:00Z",
      status: UserFileStatus.COMPLETED,
      file_type: "application/pdf",
      last_accessed_at: "2026-09-23T00:00:00Z",
      chat_file_type: ChatFileType.DOCUMENT,
      token_count: null,
      chunk_count: null,
      attachment_source: "recent",
    };
    const earlyEof: SendMessageImpl = async function* () {
      yield {
        type: "message_id_info",
        user_message_id: 20,
        reserved_assistant_message_id: 21,
      };
      yield packet(0, { type: "message_start", content: "Partial" });
    };
    mockSendMessage.mockImplementationOnce(earlyEof);
    const { result } = renderController();

    await act(async () => {
      await result.current.onSubmit({
        message: "summarize this",
        currentMessageFiles: [attachment],
        deepResearch: false,
      });
    });

    const user = userNode();
    expect(user?.messageId).toBe(20);
    expect(user?.files.map((f) => f.id)).toEqual(["file-1"]);
    expect(replies().map((m) => m.type)).toEqual(["error"]);

    // Resubmit as AppPage does it: the composer is already empty.
    let resubmitParams: SendMessageParams | undefined;
    const finished: SendMessageImpl = async function* (params) {
      resubmitParams = params;
      yield packet(0, { type: "stop" });
    };
    mockSendMessage.mockImplementationOnce(finished);
    await act(async () => {
      await result.current.onSubmit({
        message: user?.message ?? "",
        currentMessageFiles: [],
        deepResearch: false,
        messageIdToResend: user?.messageId,
      });
    });

    expect(resubmitParams?.fileDescriptors?.map((f) => f.id)).toEqual([
      "file-1",
    ]);
    // The original message was the first one, so it resends from the root.
    expect(resubmitParams?.parentMessageId).toBeNull();
    expect(sessionTree().get(SYSTEM_NODE_ID)).toBeDefined();
  });
});
