import {
  buildUserStopPacket,
  getUnfinishedModelIndices,
  resolveStreamEnd,
  shouldKeepConsuming,
} from "./streamEnd";
import { Packet, PacketType, StopReason } from "./streamingModels";

function packet(type: PacketType, modelIndex?: number | null): Packet {
  return {
    placement: { turn_index: 0, model_index: modelIndex },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    obj: { type } as any,
  };
}

const answering = [
  packet(PacketType.MESSAGE_START),
  packet(PacketType.MESSAGE_DELTA),
];
const finished = [...answering, packet(PacketType.STOP)];

function abortedSignal(): AbortSignal {
  const controller = new AbortController();
  controller.abort();
  return controller.signal;
}

describe("shouldKeepConsuming", () => {
  const live = new AbortController().signal;

  it("keeps consuming while the producer runs or packets are queued", () => {
    expect(
      shouldKeepConsuming({ isComplete: false, isEmpty: () => true }, live)
    ).toBe(true);
    expect(
      shouldKeepConsuming({ isComplete: true, isEmpty: () => false }, live)
    ).toBe(true);
    expect(
      shouldKeepConsuming({ isComplete: true, isEmpty: () => true }, live)
    ).toBe(false);
  });

  it("stops at once after an abort, even with packets still queued", () => {
    // The loop does not pop packets after an abort, so waiting for an empty
    // queue here would spin forever and freeze the tab.
    expect(
      shouldKeepConsuming(
        { isComplete: false, isEmpty: () => false },
        abortedSignal()
      )
    ).toBe(false);
  });
});

describe("getUnfinishedModelIndices", () => {
  it("returns models with no STOP and no error of their own", () => {
    expect(
      getUnfinishedModelIndices([finished, answering, []], new Set())
    ).toEqual([1, 2]);
  });

  it("skips models that already errored", () => {
    expect(
      getUnfinishedModelIndices([answering, answering], new Set([0]))
    ).toEqual([1]);
  });

  it("counts a global STOP (no model_index) as each model's end", () => {
    const withGlobalStop = [...answering, packet(PacketType.STOP, null)];
    expect(
      getUnfinishedModelIndices([withGlobalStop, withGlobalStop], new Set())
    ).toEqual([]);
  });
});

describe("resolveStreamEnd", () => {
  const ENDED = "ended unexpectedly";
  const base = {
    aborted: false,
    stopRequested: false,
    erroredModelIndices: new Set<number>(),
    transportError: null,
    endedUnexpectedlyError: ENDED,
  };

  it("does nothing when every model finished", () => {
    expect(
      resolveStreamEnd({ ...base, packetsPerModel: [finished, finished] })
    ).toEqual({ stopped: [], errored: [], errorMessage: ENDED });
  });

  it("errors only the unfinished model when the stream ends early", () => {
    expect(
      resolveStreamEnd({
        ...base,
        packetsPerModel: [finished, answering, answering],
        erroredModelIndices: new Set([2]),
      })
    ).toEqual({ stopped: [], errored: [1], errorMessage: ENDED });
  });

  it("errors a single model that got no STOP", () => {
    expect(resolveStreamEnd({ ...base, packetsPerModel: [answering] })).toEqual(
      { stopped: [], errored: [0], errorMessage: ENDED }
    );
  });

  it("keeps finished models and errors the rest on a transport failure", () => {
    expect(
      resolveStreamEnd({
        ...base,
        transportError: "network error",
        packetsPerModel: [finished, answering],
      })
    ).toEqual({ stopped: [], errored: [1], errorMessage: "network error" });
  });

  it("errors every model on a transport failure before any packet", () => {
    expect(
      resolveStreamEnd({
        ...base,
        transportError: "HTTP error! status: 500",
        packetsPerModel: [[], []],
      })
    ).toEqual({
      stopped: [],
      errored: [0, 1],
      errorMessage: "HTTP error! status: 500",
    });
  });

  it("keeps a finished single model when the transport fails after STOP", () => {
    expect(
      resolveStreamEnd({
        ...base,
        transportError: "network error",
        packetsPerModel: [finished],
      })
    ).toEqual({ stopped: [], errored: [], errorMessage: "network error" });
  });

  it("never marks an aborted stream", () => {
    expect(
      resolveStreamEnd({
        ...base,
        aborted: true,
        transportError: "AbortError",
        packetsPerModel: [answering, []],
      })
    ).toEqual({ stopped: [], errored: [], errorMessage: "AbortError" });
  });

  it("closes a stopped send as stopped, even on a transport failure", () => {
    for (const transportError of [null, "network error"]) {
      expect(
        resolveStreamEnd({
          ...base,
          stopRequested: true,
          transportError,
          packetsPerModel: [finished, answering],
        })
      ).toMatchObject({ stopped: [1], errored: [] });
    }
  });
});

describe("buildUserStopPacket", () => {
  it("builds a STOP with the user-cancelled reason", () => {
    const stop = buildUserStopPacket();
    expect(stop.obj).toEqual({
      type: PacketType.STOP,
      stop_reason: StopReason.USER_CANCELLED,
    });
    expect(getUnfinishedModelIndices([[stop]], new Set())).toEqual([]);
  });
});
