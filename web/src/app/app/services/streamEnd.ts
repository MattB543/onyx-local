import { isStreamingComplete } from "@/app/app/services/packetUtils";
import { Packet, StopReason } from "@/app/app/services/streamingModels";

interface PacketQueue {
  isComplete: boolean;
  isEmpty(): boolean;
}

/** An aborted send stops at once: its queue is never drained, so waiting for
 *  it to empty would spin the consume loop without yielding. */
export function shouldKeepConsuming(
  queue: PacketQueue,
  signal: AbortSignal
): boolean {
  if (signal.aborted) return false;
  return !queue.isComplete || !queue.isEmpty();
}

/** Models that have neither a STOP packet nor an error of their own. */
export function getUnfinishedModelIndices(
  packetsPerModel: Packet[][],
  erroredModelIndices: ReadonlySet<number>
): number[] {
  const unfinished: number[] = [];
  packetsPerModel.forEach((packets, idx) => {
    if (!erroredModelIndices.has(idx) && !isStreamingComplete(packets)) {
      unfinished.push(idx);
    }
  });
  return unfinished;
}

export interface StreamEndInput {
  aborted: boolean;
  stopRequested: boolean;
  packetsPerModel: Packet[][];
  erroredModelIndices: ReadonlySet<number>;
  /** Why the transport failed (HTTP error, dropped connection), if it did. */
  transportError: string | null;
  /** The error for a stream that closed cleanly but too early. */
  endedUnexpectedlyError: string;
}

export interface StreamEndOutcome {
  /** Models to close as stopped by the user. */
  stopped: number[];
  /** Models to mark as errored with `errorMessage`. */
  errored: number[];
  errorMessage: string;
}

/** Decides what to do with each model when a fresh send's stream closes,
 *  cleanly or with a transport failure. A model with a STOP or an error of
 *  its own keeps its panel. The others close as stopped when the user
 *  stopped the send, else as errored. An abort (navigation away) changes
 *  nothing: the backend run goes on and the next load of the chat resumes
 *  it. */
export function resolveStreamEnd({
  aborted,
  stopRequested,
  packetsPerModel,
  erroredModelIndices,
  transportError,
  endedUnexpectedlyError,
}: StreamEndInput): StreamEndOutcome {
  const errorMessage = transportError ?? endedUnexpectedlyError;
  if (aborted) return { stopped: [], errored: [], errorMessage };
  const unfinished = getUnfinishedModelIndices(
    packetsPerModel,
    erroredModelIndices
  );
  return stopRequested
    ? { stopped: unfinished, errored: [], errorMessage }
    : { stopped: [], errored: unfinished, errorMessage };
}

/** The same STOP the backend sends when the user stops a run. */
export function buildUserStopPacket(): Packet {
  return {
    placement: { turn_index: 0 },
    obj: { type: "stop", stop_reason: StopReason.USER_CANCELLED },
  };
}
