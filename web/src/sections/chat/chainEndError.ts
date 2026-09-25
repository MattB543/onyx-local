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

// A saved model error reads "Error from <model>: <message>", where <message>
// starts with the category text of litellm_exception_to_error_msg in
// backend/onyx/llm/utils.py. Keep these prefixes in sync with it.
const SAVED_ERROR_START = "Error from ";
const ERROR_CODE_BY_MESSAGE_PREFIX: ReadonlyArray<[RegExp, string]> = [
  [/^API connection error:/, "CONNECTION_ERROR"],
  [/^Request timed out:/, "CONNECTION_ERROR"],
  [/^Permission denied:/, "PERMISSION_DENIED"],
  [/^Authentication failed:/, "AUTH_ERROR"],
  [/^Context window exceeded:/, "CONTEXT_TOO_LONG"],
  [/^Content policy violation:/, "CONTENT_POLICY"],
  [/^Bad request:/, "BAD_REQUEST"],
  [/^Resource not found:/, "NOT_FOUND"],
  [/^Budget exceeded:/, "BUDGET_EXCEEDED"],
  [/^[^:]* quota exceeded:/, "BUDGET_EXCEEDED"],
  [/^[^:]* rate limit( exceeded)?:/, "RATE_LIMIT"],
  [/^[^:]* rejected the request with 503 /, "SERVICE_UNAVAILABLE"],
  [/^[^:]* service error \(HTTP 503\):/, "SERVICE_UNAVAILABLE"],
  [/^API error:/, "API_ERROR"],
];

/** The error code of a reloaded model error. Only the live stream carries
 *  the code, so a reload infers it from the saved text to show the same
 *  heading. Unknown text gets no code (the generic heading). */
export function inferSavedErrorCode(errorText: string): string | undefined {
  if (!errorText.startsWith(SAVED_ERROR_START)) return undefined;
  // The model name can contain ": " too (e.g. "Bedrock: Claude"), so try the
  // text after each ": " in order and take the first known category.
  let separator = errorText.indexOf(": ", SAVED_ERROR_START.length);
  while (separator !== -1) {
    const message = errorText.slice(separator + 2);
    const match = ERROR_CODE_BY_MESSAGE_PREFIX.find(([prefix]) =>
      prefix.test(message)
    );
    if (match) return match[1];
    separator = errorText.indexOf(": ", separator + 2);
  }
  return undefined;
}
