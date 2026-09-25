/**
 * Switching chats while another chat streams: the chat the user opens must
 * load its own messages, a load that finishes after the user moved on must
 * not take over the chat on screen, and a load never resumes a run that a
 * local send is already streaming.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReadonlyURLSearchParams } from "next/navigation";
import useChatSessionController from "@/hooks/useChatSessionController";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  BackendChatSession,
  BackendMessage,
  ChatSessionSharedStatus,
  Message,
} from "@/app/app/interfaces";
import { resumeStream } from "@/app/app/services/lib";

jest.mock("@/app/app/services/lib", () => ({
  ...jest.requireActual("@/app/app/services/lib"),
  nameChatSession: jest.fn().mockResolvedValue({ ok: true }),
  patchMessageToBeLatest: jest.fn(),
  resumeStream: jest.fn(),
}));

jest.mock("@/lib/projects/svc", () => ({
  getSessionProjectTokenCount: jest.fn().mockResolvedValue(0),
  getProjectFilesForSession: jest.fn().mockResolvedValue([]),
}));

jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({
    setIncognitoEnabled: jest.fn(),
    setIncognitoSessionId: jest.fn(),
  }),
}));

const mockResumeStream = resumeStream as jest.Mock;

const STREAMING_ID = "streaming-chat";
const OTHER_ID = "other-chat";
const A_ID = "chat-a";

function backendMessage(
  message_id: number,
  message_type: "user" | "assistant",
  parent_message: number | null,
  latest_child_message: number | null
): BackendMessage {
  return {
    message_id,
    message_type,
    research_type: null,
    parent_message,
    latest_child_message,
    message: `${message_type} ${message_id}`,
    rephrased_query: null,
    context_docs: null,
    time_sent: "2026-09-24T14:00:00Z",
    overridden_model: "",
    alternate_assistant_id: null,
    chat_session_id: OTHER_ID,
    citations: null,
    files: [],
    tool_call: null,
    current_feedback: null,
    sub_questions: [],
    comments: null,
    parentMessageId: null,
    refined_answer_improvement: null,
    is_agentic: null,
    preferred_response_id: null,
    model_display_name: null,
    error: null,
  };
}

function backendSession(
  chatSessionId: string,
  overrides: Partial<BackendChatSession> = {}
): BackendChatSession {
  return {
    chat_session_id: chatSessionId,
    description: "Other chat",
    persona_id: 0,
    persona_name: "",
    messages: [
      backendMessage(1, "user", null, 2),
      backendMessage(2, "assistant", 1, null),
    ],
    time_created: "2026-09-24T14:00:00Z",
    time_updated: "2026-09-24T14:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    packets: [[]],
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  } as unknown as Response;
}

function deferredResponse(): {
  promise: Promise<Response>;
  resolve: (response: Response) => void;
} {
  let resolve: (response: Response) => void = () => {};
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const streamingTree = new Map<number, Message>([
  [
    -1,
    {
      nodeId: -1,
      message: "Write a story",
      type: "user",
      files: [],
      toolCall: null,
      parentNodeId: null,
      packets: [],
    } as Message,
  ],
]);

function renderSessionController(initialSessionId: string) {
  const onSubmit = jest.fn().mockResolvedValue(undefined);
  const props = {
    existingChatSessionId: initialSessionId as string | null,
    searchParams: new URLSearchParams() as unknown as ReadonlyURLSearchParams,
    setSelectedDocuments: jest.fn(),
    setCurrentMessageFiles: jest.fn(),
    chatSessionIdRef: { current: initialSessionId as string | null },
    loadedIdSessionRef: { current: initialSessionId as string | null },
    chatInputBarRef: { current: null },
    isInitialLoad: { current: false },
    submitOnLoadPerformed: { current: false },
    refreshChatSessions: jest.fn(),
    onSubmit,
  };
  const hook = renderHook(
    ({ sessionId }: { sessionId: string | null }) =>
      useChatSessionController({ ...props, existingChatSessionId: sessionId }),
    { initialProps: { sessionId: initialSessionId as string | null } }
  );
  return hook;
}

beforeEach(() => {
  mockResumeStream.mockReset();
  useChatSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
  });
  const store = useChatSessionStore.getState();
  store.updateSessionAndMessageTree(STREAMING_ID, new Map(streamingTree));
  store.updateChatState(STREAMING_ID, "streaming");
});

describe("useChatSessionController session switch", () => {
  it("loads the opened chat while another chat is streaming", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(backendSession(OTHER_ID)));
    const { rerender } = renderSessionController(STREAMING_ID);
    // The streaming chat is already in the store, so it is not re-fetched.
    expect(global.fetch).not.toHaveBeenCalled();

    rerender({ sessionId: OTHER_ID });

    await waitFor(() => {
      const other = useChatSessionStore.getState().sessions.get(OTHER_ID);
      expect(other?.messageTree.size).toBe(2);
    });
    const state = useChatSessionStore.getState();
    expect(state.currentSessionId).toBe(OTHER_ID);
    expect(state.sessions.get(OTHER_ID)?.isFetchingChatMessages).toBe(false);
    // The stream keeps its own session.
    const streaming = state.sessions.get(STREAMING_ID);
    expect(streaming?.chatState).toBe("streaming");
    expect(streaming?.messageTree.get(-1)?.message).toBe("Write a story");
  });

  it("keeps a streaming chat's tree when its own load returns mid-stream", async () => {
    const pending = deferredResponse();
    global.fetch = jest.fn((url: string) =>
      url.endsWith(STREAMING_ID)
        ? pending.promise
        : Promise.resolve(jsonResponse(backendSession(OTHER_ID)))
    ) as unknown as typeof fetch;
    useChatSessionStore.getState().updateChatState(STREAMING_ID, "input");
    const { rerender } = renderSessionController(OTHER_ID);
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get(OTHER_ID)?.isLoaded
      ).toBe(true)
    );
    rerender({ sessionId: STREAMING_ID });
    // A send starts in this chat before its load comes back.
    act(() => {
      useChatSessionStore.getState().updateChatState(STREAMING_ID, "streaming");
    });

    await act(async () => {
      pending.resolve(jsonResponse(backendSession(STREAMING_ID)));
    });

    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get(STREAMING_ID)
          ?.isFetchingChatMessages
      ).toBe(false)
    );
    const tree = useChatSessionStore
      .getState()
      .sessions.get(STREAMING_ID)?.messageTree;
    expect(tree?.size).toBe(1);
    expect(tree?.get(-1)?.message).toBe("Write a story");
  });

  it("ignores a load that finishes after the user went back", async () => {
    const pending = deferredResponse();
    global.fetch = jest.fn().mockReturnValue(pending.promise);
    const { rerender } = renderSessionController(STREAMING_ID);

    rerender({ sessionId: OTHER_ID });
    expect(global.fetch).toHaveBeenCalledTimes(1);
    rerender({ sessionId: STREAMING_ID });
    expect(useChatSessionStore.getState().currentSessionId).toBe(STREAMING_ID);

    const lateResponse = jsonResponse(backendSession(OTHER_ID));
    const readBody = jest.spyOn(lateResponse, "json");
    await act(async () => {
      pending.resolve(lateResponse);
    });
    await waitFor(() => expect(readBody).toHaveBeenCalled());
    await act(async () => {});

    const state = useChatSessionStore.getState();
    expect(state.currentSessionId).toBe(STREAMING_ID);
    expect(state.sessions.get(OTHER_ID)?.messageTree.size ?? 0).toBe(0);
  });

  it("ignores an earlier load of the same chat after A → B → A", async () => {
    const firstLoadOfA = deferredResponse();
    global.fetch = jest
      .fn()
      .mockReturnValueOnce(firstLoadOfA.promise)
      .mockResolvedValueOnce(jsonResponse(backendSession(OTHER_ID)))
      .mockResolvedValueOnce(jsonResponse(backendSession(A_ID)));
    const { result, rerender } = renderSessionController(A_ID);
    rerender({ sessionId: OTHER_ID });
    rerender({ sessionId: A_ID });
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get(A_ID)?.messageTree.size
      ).toBe(2)
    );

    await act(async () => {
      firstLoadOfA.resolve(jsonResponse({ detail: "gone" }, 404));
    });

    expect(result.current.sessionFetchError).toBeNull();
    const state = useChatSessionStore.getState();
    expect(state.currentSessionId).toBe(A_ID);
    expect(state.sessions.get(A_ID)?.messageTree.size).toBe(2);
    expect(state.sessions.get(A_ID)?.isFetchingChatMessages).toBe(false);
  });

  it("clears the fetching state when the body cannot be read", async () => {
    jest.spyOn(console, "error").mockImplementation(() => {});
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.reject(new Error("body stream already read")),
    });
    const { result } = renderSessionController(A_ID);

    await waitFor(() =>
      expect(result.current.sessionFetchError).not.toBeNull()
    );
    expect(result.current.sessionFetchError?.type).toBe("unknown");
    expect(
      useChatSessionStore.getState().sessions.get(A_ID)?.isFetchingChatMessages
    ).toBe(false);
    (console.error as jest.Mock).mockRestore();
  });

  it("does not resume a run that a local send is streaming", async () => {
    const pending = deferredResponse();
    global.fetch = jest.fn((url: string) =>
      url.endsWith(STREAMING_ID)
        ? pending.promise
        : Promise.resolve(jsonResponse(backendSession(OTHER_ID)))
    ) as unknown as typeof fetch;
    useChatSessionStore.getState().updateChatState(STREAMING_ID, "input");
    const { rerender } = renderSessionController(OTHER_ID);
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get(OTHER_ID)?.isLoaded
      ).toBe(true)
    );
    rerender({ sessionId: STREAMING_ID });
    act(() => {
      useChatSessionStore.getState().updateChatState(STREAMING_ID, "streaming");
    });

    await act(async () => {
      pending.resolve(
        jsonResponse(
          backendSession(STREAMING_ID, { current_run: { run_id: 2 } })
        )
      );
    });

    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get(STREAMING_ID)
          ?.isFetchingChatMessages
      ).toBe(false)
    );
    expect(mockResumeStream).not.toHaveBeenCalled();
    expect(
      useChatSessionStore.getState().sessions.get(STREAMING_ID)?.messageTree
        .size
    ).toBe(1);
  });

  it("resumes an in-flight run when no local send owns the chat", async () => {
    mockResumeStream.mockImplementation(async function* () {});
    global.fetch = jest
      .fn()
      .mockResolvedValue(
        jsonResponse(backendSession(A_ID, { current_run: { run_id: 2 } }))
      );
    renderSessionController(A_ID);

    await waitFor(() => expect(mockResumeStream).toHaveBeenCalledTimes(1));
    expect(mockResumeStream.mock.calls[0]?.[0]).toBe(A_ID);
  });
});
