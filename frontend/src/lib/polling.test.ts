import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isTerminalRepositoryStatus, startPolling } from "./polling";

describe("isTerminalRepositoryStatus", () => {
  it("is terminal for completed and failed", () => {
    expect(isTerminalRepositoryStatus("completed")).toBe(true);
    expect(isTerminalRepositoryStatus("failed")).toBe(true);
  });

  it("is not terminal for in-progress statuses", () => {
    for (const status of ["pending", "cloning", "parsing", "embedding"]) {
      expect(isTerminalRepositoryStatus(status)).toBe(false);
    }
  });
});

describe("startPolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("fetches immediately on start", async () => {
    const fetchValue = vi.fn().mockResolvedValue({ status: "pending" });
    const onUpdate = vi.fn();

    startPolling({
      fetchValue,
      isTerminal: () => false,
      intervalMs: 1000,
      onUpdate,
    });
    await vi.waitFor(() => expect(fetchValue).toHaveBeenCalledTimes(1));

    expect(onUpdate).toHaveBeenCalledWith({ status: "pending" });
  });

  it("polls again after intervalMs while not terminal", async () => {
    const fetchValue = vi.fn().mockResolvedValue({ status: "pending" });
    const onUpdate = vi.fn();

    startPolling({
      fetchValue,
      isTerminal: () => false,
      intervalMs: 1000,
      onUpdate,
    });
    await vi.waitFor(() => expect(fetchValue).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchValue).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchValue).toHaveBeenCalledTimes(3);
  });

  it("stops polling once isTerminal returns true", async () => {
    let call = 0;
    const fetchValue = vi.fn().mockImplementation(() => {
      call += 1;
      return Promise.resolve({ status: call >= 2 ? "completed" : "pending" });
    });
    const onUpdate = vi.fn();

    startPolling({
      fetchValue,
      isTerminal: (v: { status: string }) => v.status === "completed",
      intervalMs: 1000,
      onUpdate,
    });
    await vi.waitFor(() => expect(fetchValue).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchValue).toHaveBeenCalledTimes(2);
    expect(onUpdate).toHaveBeenLastCalledWith({ status: "completed" });

    // no further polling after reaching a terminal state
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchValue).toHaveBeenCalledTimes(2);
  });

  it("stops and reports via onError when fetchValue rejects, without retrying", async () => {
    const error = new Error("network down");
    const fetchValue = vi.fn().mockRejectedValue(error);
    const onUpdate = vi.fn();
    const onError = vi.fn();

    startPolling({
      fetchValue,
      isTerminal: () => false,
      intervalMs: 1000,
      onUpdate,
      onError,
    });
    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith(error));

    expect(onUpdate).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchValue).toHaveBeenCalledTimes(1); // never retried
  });

  it("the returned stop function prevents further polling", async () => {
    const fetchValue = vi.fn().mockResolvedValue({ status: "pending" });
    const onUpdate = vi.fn();

    const stop = startPolling({
      fetchValue,
      isTerminal: () => false,
      intervalMs: 1000,
      onUpdate,
    });
    await vi.waitFor(() => expect(fetchValue).toHaveBeenCalledTimes(1));

    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchValue).toHaveBeenCalledTimes(1);
  });

  it("stop() called mid-flight prevents the in-flight result from scheduling another poll", async () => {
    let resolveFetch: (value: { status: string }) => void;
    const fetchValue = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve;
        }),
    );
    const onUpdate = vi.fn();

    const stop = startPolling({
      fetchValue,
      isTerminal: () => false,
      intervalMs: 1000,
      onUpdate,
    });
    expect(fetchValue).toHaveBeenCalledTimes(1);

    stop();
    resolveFetch!({ status: "pending" });
    await vi.advanceTimersByTimeAsync(5000);

    expect(onUpdate).not.toHaveBeenCalled();
    expect(fetchValue).toHaveBeenCalledTimes(1);
  });
});
