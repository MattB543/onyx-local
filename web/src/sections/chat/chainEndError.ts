import { Message } from "@/app/app/interfaces";
import { getMultiModelChildren } from "@/app/app/message/multiModel";

/** The error message that ends the chain, when no multi-model panel shows
 *  it. Every reply carries its model name, so only the turn grouping can
 *  tell a single-model error from a panel error. */
export function getChainEndError(
  messages: Message[],
  messageTree: Map<number, Message> | undefined
): Message | null {
  const last = messages[messages.length - 1];
  if (last?.type !== "error") return null;
  const parent =
    last.parentNodeId != null ? messageTree?.get(last.parentNodeId) : undefined;
  if (parent && messageTree && getMultiModelChildren(parent, messageTree)) {
    return null;
  }
  return last;
}
