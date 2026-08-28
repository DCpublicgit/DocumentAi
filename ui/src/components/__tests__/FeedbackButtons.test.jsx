import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FeedbackButtons from "../FeedbackButtons.jsx";
import { submitFeedback } from "../../lib/feedback.js";

vi.mock("../../lib/feedback.js", () => ({
  submitFeedback: vi.fn(() => Promise.resolve()),
}));

const baseProps = {
  messageId: "m1",
  conversationId: "c1",
  question: "Ажлын цаг хэд вэ?",
  answer: "09:00-18:00",
  retrievedChunkIds: ["a.txt::v1::0"],
  latencyMs: 1500,
};

beforeEach(() => {
  submitFeedback.mockClear();
});

describe("FeedbackButtons", () => {
  it("sends verdict=up immediately on thumbs-up, no follow-up shown", () => {
    render(<FeedbackButtons {...baseProps} />);

    fireEvent.click(screen.getByLabelText("Ашигтай хариулт"));

    expect(submitFeedback).toHaveBeenCalledTimes(1);
    expect(submitFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ ...baseProps, verdict: "up" }),
    );
    expect(screen.queryByText("Юу нь буруу байсан бэ?")).not.toBeInTheDocument();
  });

  it("sends verdict=down immediately on thumbs-down AND opens the follow-up", () => {
    render(<FeedbackButtons {...baseProps} />);

    fireEvent.click(screen.getByLabelText("Ашиггүй хариулт"));

    expect(submitFeedback).toHaveBeenCalledTimes(1);
    expect(submitFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ ...baseProps, verdict: "down" }),
    );
    expect(screen.getByText("Юу нь буруу байсан бэ?")).toBeInTheDocument();
  });

  it("submit is disabled until a reason is picked or text is entered", () => {
    render(<FeedbackButtons {...baseProps} />);
    fireEvent.click(screen.getByLabelText("Ашиггүй хариулт"));

    expect(screen.getByText("Илгээх")).toBeDisabled();

    fireEvent.click(screen.getByText("ойлгомжгүй"));

    expect(screen.getByText("Илгээх")).not.toBeDisabled();
  });

  it("submitting the follow-up sends a second feedback call with the reason", () => {
    render(<FeedbackButtons {...baseProps} />);
    fireEvent.click(screen.getByLabelText("Ашиггүй хариулт"));
    fireEvent.click(screen.getByText("олдсонгүй"));
    fireEvent.change(screen.getByPlaceholderText("Нэмэлт тайлбар (заавал биш)..."), {
      target: { value: "Хайсан ч олдсонгүй" },
    });

    fireEvent.click(screen.getByText("Илгээх"));

    expect(submitFeedback).toHaveBeenCalledTimes(2);
    expect(submitFeedback).toHaveBeenLastCalledWith(
      expect.objectContaining({
        verdict: "down",
        reason: "олдсонгүй",
        reasonText: "Хайсан ч олдсонгүй",
      }),
    );
    expect(screen.getByText("Санал хүсэлтэд баярлалаа.")).toBeInTheDocument();
  });

  it("submitting with only free text and no reason chosen is allowed", () => {
    render(<FeedbackButtons {...baseProps} />);
    fireEvent.click(screen.getByLabelText("Ашиггүй хариулт"));
    fireEvent.change(screen.getByPlaceholderText("Нэмэлт тайлбар (заавал биш)..."), {
      target: { value: "чөлөөт тайлбар" },
    });

    expect(screen.getByText("Илгээх")).not.toBeDisabled();
    fireEvent.click(screen.getByText("Илгээх"));

    expect(submitFeedback).toHaveBeenLastCalledWith(
      expect.objectContaining({ reason: null, reasonText: "чөлөөт тайлбар" }),
    );
  });

  it("skipping the follow-up closes it without a second submission", () => {
    render(<FeedbackButtons {...baseProps} />);
    fireEvent.click(screen.getByLabelText("Ашиггүй хариулт"));

    fireEvent.click(screen.getByText("Алгасах"));

    expect(submitFeedback).toHaveBeenCalledTimes(1); // only the bare down-vote
    expect(screen.queryByText("Юу нь буруу байсан бэ?")).not.toBeInTheDocument();
  });

  it("toggling thumbs-down off hides the follow-up without retracting the sent vote", () => {
    render(<FeedbackButtons {...baseProps} />);
    const downButton = screen.getByLabelText("Ашиггүй хариулт");
    fireEvent.click(downButton);
    fireEvent.click(downButton);

    expect(submitFeedback).toHaveBeenCalledTimes(1); // no retraction call
    expect(screen.queryByText("Юу нь буруу байсан бэ?")).not.toBeInTheDocument();
    expect(downButton).toHaveAttribute("aria-pressed", "false");
  });

  it("a failed submission does not throw or block the UI", async () => {
    submitFeedback.mockRejectedValueOnce(new Error("network down"));
    render(<FeedbackButtons {...baseProps} />);

    expect(() => fireEvent.click(screen.getByLabelText("Ашигтай хариулт"))).not.toThrow();
  });
});
