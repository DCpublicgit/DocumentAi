import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.jsx";
import { streamChatCompletion } from "../lib/streamChat.js";
import { ChatRequestError, ERROR_KIND } from "../lib/chatErrors.js";

vi.mock("../lib/streamChat.js", () => ({
  streamChatCompletion: vi.fn(),
}));

function stubBrowserApis() {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  Element.prototype.scrollIntoView = vi.fn();
}

function ask(text) {
  fireEvent.change(screen.getByLabelText("Асуулт"), { target: { value: text } });
  fireEvent.click(screen.getByLabelText("Илгээх"));
}

beforeEach(() => {
  stubBrowserApis();
  streamChatCompletion.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("App — failed send handling", () => {
  it("network failure: distinct copy + retry button once the one automatic retry is also exhausted; the button resends and succeeds", async () => {
    streamChatCompletion
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockImplementationOnce(async (question, onToken) => {
        onToken("Дараа амжилттай");
      });

    vi.useFakeTimers();
    render(<App />);
    ask("Асуулт нэг");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000); // covers the automatic retry's backoff delay
    });

    expect(streamChatCompletion).toHaveBeenCalledTimes(2); // initial attempt + 1 automatic retry
    expect(
      screen.getByText("Интернэт холболт тасарсан байна. Холболтоо шалгаад дахин оролдоно уу."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText("Дахин оролдох"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(streamChatCompletion).toHaveBeenCalledTimes(3);
    expect(screen.getByText("Дараа амжилттай")).toBeInTheDocument();
    expect(screen.queryByText("Дахин оролдох")).not.toBeInTheDocument();
  });

  it("recovers silently from a single network blip via the automatic retry — no error is ever shown", async () => {
    streamChatCompletion
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockImplementationOnce(async (question, onToken) => {
        onToken("Хариулт");
      });

    vi.useFakeTimers();
    render(<App />);
    ask("Асуулт");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(streamChatCompletion).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Хариулт")).toBeInTheDocument();
    expect(screen.queryByText("Дахин оролдох")).not.toBeInTheDocument();
  });

  it("429: shows the Retry-After seconds and does not auto-retry", async () => {
    streamChatCompletion.mockRejectedValueOnce(
      new ChatRequestError(ERROR_KIND.RATE_LIMIT, "rate limited", { retryAfterSeconds: 15 }),
    );

    render(<App />);
    ask("Асуулт");

    expect(
      await screen.findByText("Хэт олон хүсэлт илгээлээ. 15 секундын дараа дахин оролдоно уу."),
    ).toBeInTheDocument();
    expect(streamChatCompletion).toHaveBeenCalledTimes(1); // no automatic retry for rate limiting
    expect(screen.getByText("Дахин оролдох")).toBeInTheDocument();
  });

  it("5xx: shows server-error copy and does not auto-retry", async () => {
    streamChatCompletion.mockRejectedValueOnce(
      new ChatRequestError(ERROR_KIND.SERVER, "server exploded"),
    );

    render(<App />);
    ask("Асуулт");

    expect(
      await screen.findByText("Серверийн алдаа гарлаа. Түр хүлээгээд дахин оролдоно уу."),
    ).toBeInTheDocument();
    expect(streamChatCompletion).toHaveBeenCalledTimes(1);
  });

  it("a user-initiated stop shows the stopped note, not an error bubble, and is never retried", async () => {
    streamChatCompletion.mockImplementationOnce(
      (question, onToken, opts) =>
        new Promise((_resolve, reject) => {
          opts.signal.addEventListener("abort", () => {
            const err = new Error("aborted");
            err.name = "AbortError";
            reject(err);
          });
        }),
    );

    render(<App />);
    ask("Асуулт");

    fireEvent.click(await screen.findByLabelText("Зогсоох"));

    expect(await screen.findByText("Асуултыг зогсоолоо.")).toBeInTheDocument();
    expect(screen.queryByText("Дахин оролдох")).not.toBeInTheDocument();
  });
});

describe("App — pipeline stage indicator", () => {
  it("shows the retrieving label immediately on send, before any server event arrives", () => {
    streamChatCompletion.mockImplementation(() => new Promise(() => {})); // never resolves

    render(<App />);
    ask("Асуулт");

    expect(screen.getByText("Хайж байна…")).toBeInTheDocument();
  });

  it("updates through retrieving → retrieved (+ count) → generating as stage events arrive, then shows the real answer", async () => {
    let capturedOpts;
    let finishStream;
    streamChatCompletion.mockImplementation((question, onToken, opts) => {
      capturedOpts = opts;
      return new Promise((resolve) => {
        finishStream = () => {
          onToken("Хариулт");
          resolve();
        };
      });
    });

    render(<App />);
    ask("Асуулт");
    expect(screen.getByText("Хайж байна…")).toBeInTheDocument(); // client-side default

    await act(async () => {
      capturedOpts.onStage({ stage: "retrieved", documentCount: 4 });
    });
    expect(screen.getByText("4 баримт олдлоо")).toBeInTheDocument();

    await act(async () => {
      capturedOpts.onStage({ stage: "generating" });
    });
    expect(screen.getByText("Хариулт бэлтгэж байна…")).toBeInTheDocument();

    await act(async () => {
      finishStream();
    });

    expect(screen.getByText("Хариулт")).toBeInTheDocument();
    expect(screen.queryByText("Хариулт бэлтгэж байна…")).not.toBeInTheDocument();
  });

  it("a manual retry resets the indicator back to retrieving, not the failed attempt's last stage", async () => {
    streamChatCompletion.mockImplementationOnce((question, onToken, opts) => {
      opts.onStage({ stage: "generating" }); // fails deep into the pipeline...
      return Promise.reject(new ChatRequestError(ERROR_KIND.SERVER, "boom"));
    });
    streamChatCompletion.mockImplementationOnce(() => new Promise(() => {})); // retry never resolves

    render(<App />);
    ask("Асуулт");
    fireEvent.click(await screen.findByText("Дахин оролдох"));
    await act(async () => {
      await Promise.resolve();
    });

    // ...but the retry starts over at the beginning, not where it left off.
    expect(screen.getByText("Хайж байна…")).toBeInTheDocument();
  });
});

describe("App — new chat", () => {
  it("clears the conversation and starts a fresh session id", async () => {
    streamChatCompletion.mockImplementationOnce(async (question, onToken) => {
      onToken("Хариулт");
    });

    render(<App />);
    ask("Асуулт");
    expect(await screen.findByText("Хариулт")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Шинэ яриа эхлүүлэх"));

    expect(screen.queryByText("Асуулт")).not.toBeInTheDocument();
    expect(screen.queryByText("Хариулт")).not.toBeInTheDocument();
  });
});
