/**
 * The typewriter reveal lags the stream by design. A flush (the user stopped
 * the run) must show everything received at once, even when no animation
 * frame runs, as in a background tab.
 */
import { act, renderHook } from "@testing-library/react";
import { useTypewriter } from "@/hooks/useTypewriter";

const FULL = "word ".repeat(200);

type Props = {
  target: string;
  enabled: boolean;
  streamFinished: boolean;
  flush: boolean;
};

function renderTypewriter(initial: Props) {
  return renderHook(
    ({ target, enabled, streamFinished, flush }: Props) =>
      useTypewriter(target, enabled, streamFinished, flush),
    { initialProps: initial }
  );
}

describe("useTypewriter flush", () => {
  let frames: FrameRequestCallback[] = [];

  beforeEach(() => {
    frames = [];
    jest
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((cb: FrameRequestCallback) => {
        frames.push(cb);
        return frames.length;
      });
    jest.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  function runFrames(count: number) {
    for (let i = 0; i < count; i++) {
      const next = frames.shift();
      if (!next) return;
      act(() => next(performance.now()));
    }
  }

  it("lags the target while streaming", () => {
    const { result } = renderTypewriter({
      target: FULL,
      enabled: true,
      streamFinished: false,
      flush: false,
    });
    runFrames(5);
    expect(result.current.displayed.length).toBeGreaterThan(0);
    expect(result.current.displayed.length).toBeLessThan(FULL.length);
  });

  it("shows everything received at once on flush", () => {
    const { result, rerender } = renderTypewriter({
      target: FULL,
      enabled: true,
      streamFinished: false,
      flush: false,
    });
    runFrames(5);
    expect(result.current.displayed.length).toBeLessThan(FULL.length);

    rerender({
      target: FULL,
      enabled: false,
      streamFinished: true,
      flush: true,
    });

    expect(result.current.displayed).toBe(FULL);
    expect(result.current.isDraining).toBe(false);
  });

  it("flushes even when no animation frame ever runs", () => {
    const { result, rerender } = renderTypewriter({
      target: FULL,
      enabled: true,
      streamFinished: false,
      flush: false,
    });
    expect(result.current.displayed).toBe("");

    rerender({
      target: FULL,
      enabled: true,
      streamFinished: false,
      flush: true,
    });

    expect(result.current.displayed).toBe(FULL);
  });

  it("keeps showing the full target when it grows after a flush", () => {
    const { result, rerender } = renderTypewriter({
      target: FULL,
      enabled: true,
      streamFinished: false,
      flush: true,
    });
    expect(result.current.displayed).toBe(FULL);

    rerender({
      target: FULL + "tail",
      enabled: true,
      streamFinished: false,
      flush: true,
    });

    expect(result.current.displayed).toBe(FULL + "tail");
    runFrames(3);
    expect(result.current.displayed).toBe(FULL + "tail");
  });
});
