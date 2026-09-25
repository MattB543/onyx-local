import { Message } from "@/app/app/interfaces";
import {
  getChainEndError,
  inferSavedErrorCode,
} from "@/sections/chat/chainEndError";

let nextNodeId = 1;

function buildMessage(overrides: Partial<Message>): Message {
  return {
    nodeId: nextNodeId++,
    message: "",
    type: "assistant",
    files: [],
    toolCall: null,
    parentNodeId: null,
    packets: [],
    ...overrides,
  };
}

// A user message and its replies. The last reply is the active child.
function buildTurn(replies: Partial<Message>[]): {
  tree: Map<number, Message>;
  chain: Message[];
  replies: Message[];
} {
  const user = buildMessage({ type: "user", messageId: 1 });
  const built = replies.map((reply) =>
    buildMessage({ parentNodeId: user.nodeId, ...reply })
  );
  user.childrenNodeIds = built.map((r) => r.nodeId);
  user.latestChildNodeId = built.at(-1)?.nodeId ?? null;
  const tree = new Map<number, Message>(
    [user, ...built].map((m) => [m.nodeId, m])
  );
  const active = built.at(-1);
  return { tree, chain: active ? [user, active] : [user], replies: built };
}

const reloadedError: Partial<Message> = {
  type: "error",
  message: "Error from Opus 5.5: access denied",
  modelDisplayName: "Opus 5.5",
  overridden_model: "opus-5.5",
  timeSent: "2026-09-23T21:30:00Z",
};

describe("getChainEndError", () => {
  it("returns a reloaded single-model error, which carries a model name", () => {
    const { tree, chain, replies } = buildTurn([reloadedError]);
    expect(getChainEndError(chain, tree)).toBe(replies[0]);
  });

  it("returns a live single-model error", () => {
    const { tree, chain, replies } = buildTurn([
      { type: "error", message: "The response ended unexpectedly." },
    ]);
    expect(getChainEndError(chain, tree)).toBe(replies[0]);
  });

  it("returns an errored retry, which has its own time_sent", () => {
    const { tree, chain, replies } = buildTurn([
      {
        messageId: 2,
        modelDisplayName: "GPT",
        timeSent: "2026-09-23T21:00:00Z",
      },
      reloadedError,
    ]);
    expect(getChainEndError(chain, tree)).toBe(replies[1]);
  });

  it("skips an error inside a live multi-model turn", () => {
    const { tree, chain } = buildTurn([
      { modelDisplayName: "GPT", overridden_model: "gpt" },
      { type: "error", message: "boom", modelDisplayName: "Opus 5.5" },
    ]);
    expect(getChainEndError(chain, tree)).toBeNull();
  });

  it("skips an error inside a reloaded multi-model turn", () => {
    const { tree, chain } = buildTurn([
      {
        messageId: 2,
        modelDisplayName: "GPT",
        timeSent: reloadedError.timeSent,
      },
      reloadedError,
    ]);
    expect(getChainEndError(chain, tree)).toBeNull();
  });

  it("returns null when the chain does not end with an error", () => {
    const { tree, chain } = buildTurn([{ messageId: 2, message: "Hi" }]);
    expect(getChainEndError(chain, tree)).toBeNull();
    expect(getChainEndError([], tree)).toBeNull();
  });
});

describe("inferSavedErrorCode", () => {
  it.each([
    [
      "Error from us.anthropic.claude-opus-5-5: API connection error: Failed to connect to the API.",
      "CONNECTION_ERROR",
    ],
    [
      "Error from Opus 5.5: Permission denied: Model access is denied due to IAM user ...",
      "PERMISSION_DENIED",
    ],
    [
      "Error from gpt-oss:120b: Request timed out: the provider did not respond.",
      "CONNECTION_ERROR",
    ],
    ["Error from GPT: openai rate limit: slow down", "RATE_LIMIT"],
    ["Error from GPT: openai quota exceeded: check billing", "BUDGET_EXCEEDED"],
    [
      "Error from Opus: bedrock service error (HTTP 503): busy",
      "SERVICE_UNAVAILABLE",
    ],
    [
      "Error from Bedrock: Claude: Permission denied: Model access is denied",
      "PERMISSION_DENIED",
    ],
    ["Error from GPT: Bad request: Permission denied: nested", "BAD_REQUEST"],
  ])("reads the category of %s", (text, code) => {
    expect(inferSavedErrorCode(text)).toBe(code);
  });

  it("gives no code to unknown or unsaved text", () => {
    expect(
      inferSavedErrorCode("Error from GPT: The model stopped unexpectedly.")
    ).toBeUndefined();
    expect(
      inferSavedErrorCode("API connection error: Failed to connect to the API.")
    ).toBeUndefined();
    expect(inferSavedErrorCode("")).toBeUndefined();
  });
});
