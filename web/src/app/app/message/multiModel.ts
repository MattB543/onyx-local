import { Message } from "@/app/app/interfaces";
import { MultiModelResponse } from "@/app/app/message/interfaces";

// The model that produced a message. Error responses carry the model that
// failed, so they count for attribution too.
export function messageModelName(msg: Message): string | null {
  if (msg.type !== "assistant" && msg.type !== "error") return null;
  return msg.overridden_model || msg.modelDisplayName || null;
}

function isModelTagged(msg: Message): boolean {
  return (
    (msg.type === "assistant" || msg.type === "error") &&
    Boolean(msg.modelDisplayName || msg.overridden_model)
  );
}

// The child the chain walk continues through: the latest child, else the
// newest child.
function getActiveChild(
  userMessage: Message,
  messageTree: Map<number, Message>
): Message | undefined {
  const childIds = userMessage.childrenNodeIds ?? [];
  const latestId = userMessage.latestChildNodeId;
  const activeId =
    latestId != null && childIds.includes(latestId)
      ? latestId
      : childIds.at(-1);
  return activeId == null ? undefined : messageTree.get(activeId);
}

// The model-tagged children grouped by time_sent, oldest group first, each in
// child order. Every reply carries its model, so the tag alone can't tell a
// multi-model turn from a retry. The backend reserves one turn's replies in
// one transaction, so they share a time_sent, and each retry gets its own.
// Live replies have no time_sent yet and group together; a live retry has no
// model tag.
function getModelGroups(
  userMessage: Message,
  messageTree: Map<number, Message>
): Message[][] {
  const groups = new Map<string | undefined, Message[]>();
  for (const id of userMessage.childrenNodeIds ?? []) {
    const msg = messageTree.get(id);
    if (!msg || !isModelTagged(msg)) continue;
    groups.set(msg.timeSent, [...(groups.get(msg.timeSent) ?? []), msg]);
  }
  return Array.from(groups.values());
}

function isUsableResponse(msg: Message): boolean {
  return msg.type === "assistant" && msg.messageId != null;
}

// Model-tagged children (2+) of a multi-model turn, in layout order: the
// active child's group. Null when the active child is not in a group of 2+.
export function getMultiModelChildren(
  userMessage: Message,
  messageTree: Map<number, Message>
): Message[] | null {
  if ((userMessage.childrenNodeIds ?? []).length < 2) return null;

  const active = getActiveChild(userMessage, messageTree);
  if (!active || !isModelTagged(active)) return null;

  const group = getModelGroups(userMessage, messageTree).find((g) =>
    g.includes(active)
  );
  return group && group.length >= 2 ? group : null;
}

// The multi-model group a send continues from when the chain ends in an
// error. That is the active group (a panel errored). A failed retry is in no
// group of 2+, so then it is the group with the preferred response, else the
// newest group of 2+ with a usable response.
export function getErrorTipMultiModelGroup(
  userMessage: Message,
  messageTree: Map<number, Message>
): Message[] | null {
  const active = getMultiModelChildren(userMessage, messageTree);
  if (active) return active;
  const groups = getModelGroups(userMessage, messageTree).filter(
    (g) => g.length >= 2 && g.some(isUsableResponse)
  );
  const preferredId = userMessage.preferredResponseId;
  return (
    groups.find(
      (g) => preferredId != null && g.some((m) => m.messageId === preferredId)
    ) ??
    groups.at(-1) ??
    null
  );
}

// The reply a send continues from when the chain ends in an error reply of
// `userMessage`: the preferred response, else the newest usable reply. A
// failed retry leaves the replies before it. Null when there are none, as
// after a failed send.
export function getErrorTurnFallbackReply(
  userMessage: Message,
  messageTree: Map<number, Message>
): Message | null {
  const replies = (userMessage.childrenNodeIds ?? [])
    .map((id) => messageTree.get(id))
    .filter((m): m is Message => m !== undefined && isUsableResponse(m));
  return (
    replies.find((m) => m.messageId === userMessage.preferredResponseId) ??
    replies.at(-1) ??
    null
  );
}

// Group a user message's sibling responses into multi-model panels.
// `modelProviderLookup` maps model → provider slug for icons and may be
// empty (e.g. the shared view). `getModelIcon` then falls back to the name.
export function getMultiModelResponses(
  userMessage: Message,
  messageTree: Map<number, Message>,
  modelProviderLookup: Map<string, string>
): MultiModelResponse[] | null {
  const multiModelChildren = getMultiModelChildren(userMessage, messageTree);
  if (!multiModelChildren) return null;

  return multiModelChildren.map((msg, idx): MultiModelResponse => {
    const modelVersion =
      msg.overridden_model || msg.modelDisplayName || "Model";
    const provider = modelProviderLookup.get(modelVersion) ?? "";
    const displayName = msg.modelDisplayName || modelVersion;
    const isError = msg.type === "error";
    return {
      modelIndex: idx,
      provider,
      modelName: modelVersion,
      displayName,
      packets: msg.packets || [],
      packetCount: msg.packetCount || msg.packets?.length || 0,
      nodeId: msg.nodeId,
      messageId: msg.messageId,
      currentFeedback: msg.currentFeedback,
      isGenerating: msg.is_generating || false,
      errorMessage: isError ? msg.message : null,
      errorCode: isError ? msg.errorCode : null,
      isRetryable: isError ? msg.isRetryable : undefined,
      errorStackTrace: isError ? msg.stackTrace : null,
      errorDetails: isError ? msg.errorDetails : null,
    };
  });
}

export interface UnresolvedMultiModelTurn {
  userMessage: Message;
  responses: Message[];
}

// The multi-model turn a new message would continue from, when the user
// never picked a preferred response or the chain ends in an error.
// `chain` is the tree's latest chain.
export function getUnresolvedMultiModelTurn(
  chain: Message[],
  messageTree: Map<number, Message>
): UnresolvedMultiModelTurn | null {
  const lastUserMsg = [...chain].reverse().find((m) => m.type === "user");
  if (!lastUserMsg) return null;
  const responses =
    chain.at(-1)?.type === "error"
      ? getErrorTipMultiModelGroup(lastUserMsg, messageTree)
      : lastUserMsg.preferredResponseId == null
        ? getMultiModelChildren(lastUserMsg, messageTree)
        : null;
  return responses ? { userMessage: lastUserMsg, responses } : null;
}

// The model of the most recent preferred response before `excludeNodeId`'s
// turn, or null when no earlier turn has a preference.
function findPriorPreferredModel(
  chain: Message[],
  messageTree: Map<number, Message>,
  excludeNodeId: number
): string | null {
  const priorUserMsg = [...chain]
    .reverse()
    .find(
      (m) =>
        m.type === "user" &&
        m.nodeId !== excludeNodeId &&
        m.preferredResponseId != null
    );
  if (!priorUserMsg) return null;
  const priorPreferred = (priorUserMsg.childrenNodeIds ?? [])
    .map((id) => messageTree.get(id))
    .find((child) => child?.messageId === priorUserMsg.preferredResponseId);
  return (
    priorPreferred?.overridden_model || priorPreferred?.modelDisplayName || null
  );
}

// The response in view per turn (user message nodeId), written by the panel
// view's narrow-screen carousel and read at send time. An entry exists only
// while the carousel shows one response at a time.
const mostVisibleResponseByTurn = new Map<number, number>();

export function setMostVisibleResponseId(
  userNodeId: number,
  responseMessageId: number | null
): void {
  if (responseMessageId == null) {
    mostVisibleResponseByTurn.delete(userNodeId);
  } else {
    mostVisibleResponseByTurn.set(userNodeId, responseMessageId);
  }
}

export function getMostVisibleResponseId(userNodeId: number): number | null {
  return mostVisibleResponseByTurn.get(userNodeId) ?? null;
}

// The response a send assumes as preferred: the response in view on narrow
// screens, else the turn's own earlier pick (kept after a failed retry), else
// the prior turn's preferred model when it answered this turn too, else the
// first model (right-most, last child). Errors never assumed.
export function chooseImplicitPreferred(
  chain: Message[],
  messageTree: Map<number, Message>,
  turn: UnresolvedMultiModelTurn,
  visibleResponseId: number | null = null
): Message | null {
  const candidates = turn.responses.filter(isUsableResponse);
  for (const id of [visibleResponseId, turn.userMessage.preferredResponseId]) {
    const picked = id != null && candidates.find((r) => r.messageId === id);
    if (picked) return picked;
  }
  const priorModel = findPriorPreferredModel(
    chain,
    messageTree,
    turn.userMessage.nodeId
  );
  const match = priorModel
    ? candidates.find(
        (r) => (r.overridden_model || r.modelDisplayName) === priorModel
      )
    : undefined;
  return match ?? candidates.at(-1) ?? null;
}

// preferredResponseId and latestChildNodeId move together, as in the backend's
// set_preferred_response. A disagreeing local chain walk breaks the next send.
// Null clears the preference and leaves the chain tip alone.
export function applyPreferredResponse(
  tree: Map<number, Message>,
  userNodeId: number,
  response: Pick<Message, "messageId" | "nodeId"> | null
): Map<number, Message> | null {
  const userMsg = tree.get(userNodeId);
  if (!userMsg) return null;
  const updated = new Map(tree);
  updated.set(
    userNodeId,
    response
      ? {
          ...userMsg,
          preferredResponseId: response.messageId,
          latestChildNodeId: response.nodeId,
        }
      : { ...userMsg, preferredResponseId: undefined }
  );
  return updated;
}
