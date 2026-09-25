import {
  branchSelectionsSettled,
  enqueueBranchSelection,
} from "@/app/app/services/branchSelection";

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve: (value: T) => void = () => {};
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("branch selection queue", () => {
  it("sends a session's switches one at a time, in call order", async () => {
    const order: string[] = [];
    const first = deferred<string>();
    const a = enqueueBranchSelection("s1", () => {
      order.push("start a");
      return first.promise;
    });
    const b = enqueueBranchSelection("s1", async () => {
      order.push("start b");
      return "b";
    });
    await Promise.resolve();
    expect(order).toEqual(["start a"]);

    first.resolve("a");
    expect(await a).toBe("a");
    expect(await b).toBe("b");
    expect(order).toEqual(["start a", "start b"]);
  });

  it("does not let a failed switch block the next one or a send", async () => {
    jest.spyOn(console, "error").mockImplementation(() => {});
    const failed = enqueueBranchSelection("s2", async () => {
      throw new Error("offline");
    });
    const next = enqueueBranchSelection("s2", async () => "next");

    expect(await failed).toBeNull();
    expect(await next).toBe("next");
    await expect(branchSelectionsSettled("s2")).resolves.toBeUndefined();
  });

  it("settles only after every switch enqueued so far", async () => {
    const pending = deferred<void>();
    void enqueueBranchSelection("s3", () => pending.promise);
    let settled = false;
    void branchSelectionsSettled("s3").then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);

    pending.resolve();
    await branchSelectionsSettled("s3");
    expect(settled).toBe(true);
  });

  it("keeps sessions independent", async () => {
    const blocked = deferred<void>();
    void enqueueBranchSelection("s4", () => blocked.promise);

    await expect(
      enqueueBranchSelection("s5", async () => "free")
    ).resolves.toBe("free");
    blocked.resolve();
  });
});
