import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ChatPanel from "@/components/ChatPanel";
import type { ChatResponse } from "@/lib/types";

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

function setup(overrides: Partial<Parameters<typeof ChatPanel>[0]> = {}) {
  const props = {
    sendMessage: vi.fn(),
    loadHistory: vi.fn().mockResolvedValue([]),
    onActions: vi.fn(),
    collapsed: false,
    onToggle: vi.fn(),
    ...overrides,
  };
  render(<ChatPanel {...props} />);
  return props;
}

describe("ChatPanel", () => {
  it("restores conversation history with inline actions", async () => {
    setup({
      loadHistory: vi.fn().mockResolvedValue([
        { id: "1", role: "user", content: "Buy 5 AAPL", actions: null, created_at: "" },
        {
          id: "2",
          role: "assistant",
          content: "Done.",
          actions: { trades: [{ ticker: "AAPL", side: "buy", quantity: 5, status: "executed", price: 190 }], watchlist_changes: [] },
          created_at: "",
        },
      ]),
    });
    const msgs = await screen.findAllByTestId("chat-message");
    expect(msgs).toHaveLength(2);
    expect(msgs[0]).toHaveAttribute("data-role", "user");
    expect(msgs[1]).toHaveAttribute("data-role", "assistant");
    expect(screen.getByTestId("chat-action")).toHaveTextContent("Bought 5 AAPL at $190.00");
  });

  it("shows a loading indicator while awaiting the reply, then renders it", async () => {
    const user = userEvent.setup();
    const d = deferred<ChatResponse>();
    const props = setup({ sendMessage: vi.fn().mockReturnValue(d.promise) });
    await user.type(screen.getByTestId("chat-input"), "How am I doing?");
    await user.click(screen.getByTestId("chat-send-button"));

    expect(props.sendMessage).toHaveBeenCalledWith("How am I doing?");
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    expect(screen.getByTestId("chat-message")).toHaveAttribute("data-role", "user");
    expect(screen.getByTestId("chat-input")).toHaveValue("");

    d.resolve({ message: "You're up 1%.", trades: [], watchlist_changes: [] });
    await waitFor(() => expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument());
    const msgs = screen.getAllByTestId("chat-message");
    expect(msgs[1]).toHaveTextContent("You're up 1%.");
    expect(props.onActions).not.toHaveBeenCalled();
  });

  it("renders executed and failed actions and notifies the parent", async () => {
    const user = userEvent.setup();
    const response: ChatResponse = {
      message: "Here you go.",
      trades: [
        { ticker: "AAPL", side: "buy", quantity: 5, status: "executed", price: 190.12, error: null },
        { ticker: "TSLA", side: "sell", quantity: 3, status: "failed", error: "Insufficient shares" },
      ],
      watchlist_changes: [{ ticker: "PYPL", action: "add", status: "executed", error: null }],
    };
    const props = setup({ sendMessage: vi.fn().mockResolvedValue(response) });
    await user.type(screen.getByTestId("chat-input"), "do it{enter}");
    const actions = await screen.findAllByTestId("chat-action");
    expect(actions).toHaveLength(3);
    expect(actions[0]).toHaveAttribute("data-status", "executed");
    expect(actions[0]).toHaveTextContent("Bought 5 AAPL at $190.12");
    expect(actions[1]).toHaveAttribute("data-status", "failed");
    expect(actions[1]).toHaveTextContent("Insufficient shares");
    expect(actions[2]).toHaveTextContent("Added PYPL to watchlist");
    expect(props.onActions).toHaveBeenCalledWith(response);
  });

  it("shows an error when the request fails", async () => {
    const user = userEvent.setup();
    setup({ sendMessage: vi.fn().mockRejectedValue(new Error("Can't reach the server.")) });
    await user.type(screen.getByTestId("chat-input"), "hello{enter}");
    expect(await screen.findByTestId("chat-error")).toHaveTextContent("Can't reach the server.");
    expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument();
  });

  it("collapses to a rail that still exposes the panel", async () => {
    const user = userEvent.setup();
    const props = setup({ collapsed: true });
    expect(screen.getByTestId("chat-panel")).toHaveAttribute("data-collapsed", "true");
    expect(screen.queryByTestId("chat-input")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("chat-toggle"));
    expect(props.onToggle).toHaveBeenCalled();
  });
});
