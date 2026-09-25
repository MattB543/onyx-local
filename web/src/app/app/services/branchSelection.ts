// Branch switches a chat session sends to the backend: the pager's
// set-message-as-latest and the preferred-response picks. They run one at a
// time in call order, and a send waits for them before it posts. A switch
// that landed after a newer one, or after the send, would move the backend's
// mainline off the branch the user continued, hiding the new message after a
// reload.
//
// Best effort: a failed switch never blocks the ones after it or a send. The
// backend adopts the branch of the parent a send names anyway.
const pendingBySession = new Map<string, Promise<void>>();

export function enqueueBranchSelection<T>(
  sessionId: string,
  write: () => Promise<T>
): Promise<T | null> {
  const previous = pendingBySession.get(sessionId) ?? Promise.resolve();
  const result = previous.then(write).catch((error: unknown) => {
    console.error("Failed to save the selected branch:", error);
    return null;
  });
  const settled = result.then(() => undefined);
  pendingBySession.set(sessionId, settled);
  // Drop the entry once idle, unless a newer switch replaced it.
  void settled.then(() => {
    if (pendingBySession.get(sessionId) === settled) {
      pendingBySession.delete(sessionId);
    }
  });
  return result;
}

// Resolves once every switch enqueued for the session so far has settled.
export function branchSelectionsSettled(sessionId: string): Promise<void> {
  return pendingBySession.get(sessionId) ?? Promise.resolve();
}
