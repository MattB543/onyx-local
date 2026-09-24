import { Message } from "@/app/app/interfaces";
import {
  applyPreferredResponse,
  chooseImplicitPreferred,
  getErrorTipMultiModelGroup,
  getMultiModelChildren,
  getUnresolvedMultiModelTurn,
} from "@/app/app/message/multiModel";
import {
  getLastSuccessfulMessageId,
  getLatestMessageChain,
} from "@/app/app/services/messageTree";

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

// Builds a multi-model turn: one response per entry of `models`, in panel
// layout order (first model last). `timeSent` marks a reloaded turn; leave it
// out for replies created live in the browser.
function buildTurn(
  tree: Map<number, Message>,
  models: (string | { model: string; type: "error" })[],
  options: { parent?: Message; preferredModel?: string; timeSent?: string } = {}
): { userMessage: Message; responses: Message[] } {
  const userMessage = buildMessage({
    type: "user",
    parentNodeId: options.parent?.nodeId ?? null,
    messageId: nextNodeId * 100,
  });
  const responses = models.map((entry) => {
    const model = typeof entry === "string" ? entry : entry.model;
    return buildMessage({
      type: typeof entry === "string" ? "assistant" : "error",
      parentNodeId: userMessage.nodeId,
      messageId: nextNodeId * 100,
      overridden_model: model,
      modelDisplayName: model,
      timeSent: options.timeSent,
    });
  });
  userMessage.childrenNodeIds = responses.map((r) => r.nodeId);
  const preferred = responses.find(
    (r) => r.overridden_model === options.preferredModel
  );
  userMessage.preferredResponseId = preferred?.messageId ?? null;
  userMessage.latestChildNodeId =
    preferred?.nodeId ?? responses.at(-1)?.nodeId ?? null;
  if (options.parent) {
    options.parent.childrenNodeIds = [
      ...(options.parent.childrenNodeIds ?? []),
      userMessage.nodeId,
    ];
    options.parent.latestChildNodeId = userMessage.nodeId;
  }
  tree.set(userMessage.nodeId, userMessage);
  responses.forEach((r) => tree.set(r.nodeId, r));
  return { userMessage, responses };
}

// Adds a retry reply to `userMessage` and makes it the active child, as a
// regeneration does.
function addRetry(
  tree: Map<number, Message>,
  userMessage: Message,
  overrides: Partial<Message> = {}
): Message {
  const retry = buildMessage({
    parentNodeId: userMessage.nodeId,
    messageId: nextNodeId * 100,
    ...overrides,
  });
  userMessage.childrenNodeIds = [
    ...(userMessage.childrenNodeIds ?? []),
    retry.nodeId,
  ];
  userMessage.latestChildNodeId = retry.nodeId;
  tree.set(retry.nodeId, retry);
  return retry;
}

// A reloaded single-model reply: the backend stores the model on every reply.
function reloadedReply(model: string, timeSent: string): Partial<Message> {
  return { modelDisplayName: model, timeSent };
}

// The production chain walk, so tests exercise the same traversal onSubmit
// feeds the helpers.
const chainOf = getLatestMessageChain;

beforeEach(() => {
  nextNodeId = 1;
});

describe("getMultiModelChildren", () => {
  it("returns model-tagged assistant and error children in order", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, [
      "gpt-5",
      { model: "claude-opus-5", type: "error" },
    ]);
    expect(getMultiModelChildren(userMessage, tree)).toEqual(responses);
  });

  it("ignores turns without two model-tagged children", () => {
    const tree = new Map<number, Message>();
    const userMessage = buildMessage({ type: "user" });
    const regenerated = [
      buildMessage({ type: "assistant", parentNodeId: userMessage.nodeId }),
      buildMessage({ type: "assistant", parentNodeId: userMessage.nodeId }),
    ];
    userMessage.childrenNodeIds = regenerated.map((r) => r.nodeId);
    tree.set(userMessage.nodeId, userMessage);
    regenerated.forEach((r) => tree.set(r.nodeId, r));
    expect(getMultiModelChildren(userMessage, tree)).toBeNull();
  });

  const T1 = "2026-09-23T21:30:00.123456+00:00";
  const T2 = "2026-09-23T21:31:10.654321+00:00";

  it("groups a reloaded multi-model turn by its shared time_sent", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, ["gpt-5", "gemini-3"], {
      timeSent: T1,
    });
    expect(getMultiModelChildren(userMessage, tree)).toEqual(responses);
  });

  it("treats a reloaded retry of a single-model turn as a retry", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, ["gpt-5"], {
      timeSent: T1,
    });
    addRetry(tree, userMessage, reloadedReply("claude-opus-5", T2));
    expect(getMultiModelChildren(userMessage, tree)).toBeNull();

    // Switching back to the first reply keeps the single-model layout.
    userMessage.latestChildNodeId = responses[0]!.nodeId;
    expect(getMultiModelChildren(userMessage, tree)).toBeNull();
  });

  it("keeps the multi-model group of a turn that was retried later", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, ["gpt-5", "gemini-3"], {
      timeSent: T1,
    });
    addRetry(tree, userMessage, reloadedReply("claude-opus-5", T2));
    // The retry is active: it renders alone.
    expect(getMultiModelChildren(userMessage, tree)).toBeNull();

    // Switching back to a panel reply shows the original group only.
    userMessage.latestChildNodeId = responses[0]!.nodeId;
    expect(getMultiModelChildren(userMessage, tree)).toEqual(responses);
  });

  it("shows a multi-model retry group side by side", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, ["gpt-5", "gemini-3"], {
      timeSent: T1,
    });
    const retries = [
      addRetry(tree, userMessage, reloadedReply("claude-opus-5", T2)),
      addRetry(tree, userMessage, reloadedReply("gpt-5", T2)),
    ];
    expect(getMultiModelChildren(userMessage, tree)).toEqual(retries);

    userMessage.latestChildNodeId = responses[1]!.nodeId;
    expect(getMultiModelChildren(userMessage, tree)).toEqual(responses);
  });

  describe("without time_sent (live replies)", () => {
    it("groups a live multi-model turn", () => {
      const tree = new Map<number, Message>();
      const { userMessage, responses } = buildTurn(tree, ["gpt-5", "gemini-3"]);
      expect(getMultiModelChildren(userMessage, tree)).toEqual(responses);
    });

    it("renders a live retry of a reloaded multi-model turn alone", () => {
      const tree = new Map<number, Message>();
      const { userMessage, responses } = buildTurn(
        tree,
        ["gpt-5", "gemini-3"],
        { timeSent: T1 }
      );
      // A live single-model reply has no model tag and no time_sent.
      addRetry(tree, userMessage);
      expect(getMultiModelChildren(userMessage, tree)).toBeNull();

      userMessage.latestChildNodeId = responses[0]!.nodeId;
      expect(getMultiModelChildren(userMessage, tree)).toEqual(responses);
    });

    it("renders a live retry of a live multi-model turn alone", () => {
      const tree = new Map<number, Message>();
      const { userMessage, responses } = buildTurn(tree, ["gpt-5", "gemini-3"]);
      addRetry(tree, userMessage);
      expect(getMultiModelChildren(userMessage, tree)).toBeNull();

      userMessage.latestChildNodeId = responses[0]!.nodeId;
      expect(getMultiModelChildren(userMessage, tree)).toEqual(responses);
    });

    it("never groups a live retry with a reloaded reply", () => {
      const tree = new Map<number, Message>();
      const { userMessage } = buildTurn(tree, ["gpt-5"], { timeSent: T1 });
      addRetry(tree, userMessage, { modelDisplayName: "claude-opus-5" });
      expect(getMultiModelChildren(userMessage, tree)).toBeNull();
    });
  });

  it("falls back to the newest child when the latest child is unset", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, ["gpt-5", "gemini-3"], {
      timeSent: T1,
    });
    userMessage.latestChildNodeId = null;
    expect(getMultiModelChildren(userMessage, tree)).toEqual(responses);
  });
});

describe("getUnresolvedMultiModelTurn", () => {
  it("returns null when a retry of a multi-model turn is active", () => {
    const tree = new Map<number, Message>();
    const { userMessage } = buildTurn(tree, ["gpt-5", "gemini-3"], {
      timeSent: "2026-09-23T21:30:00+00:00",
    });
    addRetry(
      tree,
      userMessage,
      reloadedReply("claude-opus-5", "2026-09-23T21:31:00+00:00")
    );
    expect(getUnresolvedMultiModelTurn(chainOf(tree), tree)).toBeNull();
  });

  it("finds the last turn when no preferred response is set", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, [
      "gpt-5",
      "claude-opus-5",
    ]);
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree);
    expect(turn?.userMessage).toBe(userMessage);
    expect(turn?.responses).toEqual(responses);
  });

  it("returns null once a preferred response exists", () => {
    const tree = new Map<number, Message>();
    buildTurn(tree, ["gpt-5", "claude-opus-5"], {
      preferredModel: "gpt-5",
    });
    expect(getUnresolvedMultiModelTurn(chainOf(tree), tree)).toBeNull();
  });

  it("returns null for single-model turns", () => {
    const tree = new Map<number, Message>();
    buildTurn(tree, ["gpt-5"]);
    expect(getUnresolvedMultiModelTurn(chainOf(tree), tree)).toBeNull();
  });
});

describe("chooseImplicitPreferred", () => {
  it("keeps the model preferred in the previous turn", () => {
    const tree = new Map<number, Message>();
    const first = buildTurn(tree, ["gemini-3", "gpt-5"], {
      preferredModel: "gemini-3",
    });
    const second = buildTurn(tree, ["gemini-3", "gpt-5"], {
      parent: first.responses[0],
    });
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBe(
      second.responses[0]
    );
  });

  it("falls back to the first model (last child) without a prior preference", () => {
    const tree = new Map<number, Message>();
    const { responses } = buildTurn(tree, ["gemini-3", "gpt-5"]);
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBe(
      responses[1]
    );
  });

  it("falls back to the first model when the prior model did not answer this turn", () => {
    const tree = new Map<number, Message>();
    const first = buildTurn(tree, ["gemini-3", "gpt-5"], {
      preferredModel: "gemini-3",
    });
    const second = buildTurn(tree, ["claude-opus-5", "gpt-5"], {
      parent: first.responses[0],
    });
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBe(
      second.responses[1]
    );
  });

  it("prefers the response in view over the prior turn's model", () => {
    const tree = new Map<number, Message>();
    const first = buildTurn(tree, ["gemini-3", "gpt-5"], {
      preferredModel: "gemini-3",
    });
    const second = buildTurn(tree, ["gemini-3", "gpt-5"], {
      parent: first.responses[0],
    });
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(
      chooseImplicitPreferred(
        chainOf(tree),
        tree,
        turn,
        second.responses[1]!.messageId!
      )
    ).toBe(second.responses[1]);
  });

  it("ignores a visible id that matches no candidate", () => {
    const tree = new Map<number, Message>();
    const { responses } = buildTurn(tree, ["gemini-3", "gpt-5"]);
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn, 999999)).toBe(
      responses[1]
    );
  });

  it("never assumes an errored response", () => {
    const tree = new Map<number, Message>();
    const { responses } = buildTurn(tree, [
      "gemini-3",
      { model: "gpt-5", type: "error" },
    ]);
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBe(
      responses[0]
    );
  });

  it("returns null when every response errored", () => {
    const tree = new Map<number, Message>();
    buildTurn(tree, [
      { model: "gemini-3", type: "error" },
      { model: "gpt-5", type: "error" },
    ]);
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBeNull();
  });
});

// A multi-model turn, a retry with another model that failed, then a new
// send. The send must continue from a panel of the original group.
describe("sending after a failed retry of a multi-model turn", () => {
  const T1 = "2026-09-23T21:30:00.123456+00:00";
  const T2 = "2026-09-23T21:31:10.654321+00:00";

  // The parent message id the next send uses, after the implicit pick.
  function nextSendParentId(tree: Map<number, Message>): number | null {
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree);
    if (!turn) return getLastSuccessfulMessageId(tree);
    const chosen = chooseImplicitPreferred(chainOf(tree), tree, turn);
    const updated = chosen
      ? applyPreferredResponse(tree, turn.userMessage.nodeId, chosen)
      : null;
    return getLastSuccessfulMessageId(updated ?? tree);
  }

  it("continues from a panel after reload", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, ["gpt-5", "gemini-3"], {
      timeSent: T1,
    });
    addRetry(tree, userMessage, {
      type: "error",
      modelDisplayName: "claude-opus-5",
      timeSent: T2,
    });
    // The failed retry still renders alone.
    expect(getMultiModelChildren(userMessage, tree)).toBeNull();
    expect(getErrorTipMultiModelGroup(userMessage, tree)).toEqual(responses);
    // Without the pick, the send would use the user message as parent.
    expect(getLastSuccessfulMessageId(tree)).toBe(userMessage.messageId);
    expect(nextSendParentId(tree)).toBe(responses[1]!.messageId);
  });

  it("continues from a panel without reload", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, ["gpt-5", "gemini-3"]);
    // A live single-model error has no model tag and no time_sent.
    addRetry(tree, userMessage, { type: "error" });
    expect(getMultiModelChildren(userMessage, tree)).toBeNull();
    expect(getErrorTipMultiModelGroup(userMessage, tree)).toEqual(responses);
    expect(nextSendParentId(tree)).toBe(responses[1]!.messageId);
  });

  it("keeps the turn's earlier pick", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, ["gpt-5", "gemini-3"], {
      timeSent: T1,
      preferredModel: "gpt-5",
    });
    addRetry(tree, userMessage, {
      type: "error",
      modelDisplayName: "claude-opus-5",
      timeSent: T2,
    });
    expect(nextSendParentId(tree)).toBe(responses[0]!.messageId);
  });

  it("finds no group after a failed retry of a single-model turn", () => {
    const tree = new Map<number, Message>();
    const { userMessage } = buildTurn(tree, ["gpt-5"], { timeSent: T1 });
    addRetry(tree, userMessage, {
      type: "error",
      modelDisplayName: "claude-opus-5",
      timeSent: T2,
    });
    expect(getErrorTipMultiModelGroup(userMessage, tree)).toBeNull();
    expect(getUnresolvedMultiModelTurn(chainOf(tree), tree)).toBeNull();
  });
});
