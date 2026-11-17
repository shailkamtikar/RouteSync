import { fireEvent, render, screen, within } from "@testing-library/react";
import { Bus } from "lucide-react";
import { useState } from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { findPlace, type Place } from "@/lib/places";

import { Chips, EmptyState, RouteLabel, Stat, Tabs } from "./bits";
import { ConfirmDialog, Modal } from "./Modal";
import { PlaceInput, ViaPicker } from "./PlaceInput";
import { Pill, StatusBadge, statusLabel } from "./StatusBadge";

beforeAll(() => {
  // jsdom has no modal dialog support; this stands in for the browser's.
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

describe("StatusBadge", () => {
  it("labels every journey status in plain words", () => {
    expect(statusLabel("awaiting_confirmation")).toBe("Awaiting confirmation");
    expect(statusLabel("in_progress")).toBe("In progress");
    expect(statusLabel("boarding")).toBe("Boarding");
    expect(statusLabel("something_new")).toBe("something new");
  });

  it("renders the label and exposes the status", () => {
    render(<StatusBadge status="in_progress" />);
    const badge = screen.getByText("In progress");
    expect(badge.closest("[data-status]")).toHaveAttribute("data-status", "in_progress");
  });

  it("accepts a custom label", () => {
    render(<StatusBadge status="completed" label="Done" />);
    expect(screen.getByText("Done")).toBeInTheDocument();
    render(<Pill tone="ok">Link active</Pill>);
    expect(screen.getByText("Link active")).toBeInTheDocument();
  });
});

describe("small building blocks", () => {
  it("RouteLabel reads as 'from to to' for screen readers", () => {
    render(<RouteLabel from="Pune" to="Nanded" />);
    expect(screen.getByText("Pune", { exact: false }).textContent).toBe("Pune to Nanded");
  });

  it("EmptyState shows its title, text and action", () => {
    render(
      <EmptyState icon={Bus} title="No buses yet" action={<button>Add bus</button>}>
        Add the buses you run.
      </EmptyState>,
    );
    expect(screen.getByRole("heading", { name: "No buses yet" })).toBeInTheDocument();
    expect(screen.getByText("Add the buses you run.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add bus" })).toBeInTheDocument();
  });

  it("Stat shows a value and label", () => {
    render(<Stat icon={Bus} label="On the road" value={4} />);
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("On the road")).toBeInTheDocument();
  });

  it("Tabs mark the selected tab and report changes", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        label="Sections"
        value="plan"
        onChange={onChange}
        tabs={[
          { id: "plan", label: "Plan" },
          { id: "bookings", label: "Bookings", count: 3 },
        ]}
      />,
    );
    expect(screen.getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: /Bookings/ }));
    expect(onChange).toHaveBeenCalledWith("bookings");
    expect(screen.getByRole("tab", { name: /Bookings/ })).toHaveTextContent("3");
  });

  it("Chips are toggle buttons", () => {
    const onChange = vi.fn();
    render(
      <Chips
        label="Filter"
        value="all"
        onChange={onChange}
        options={[
          { id: "all", label: "All", count: 20 },
          { id: "live", label: "Live", count: 2 },
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: /^All/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /^Live/ }));
    expect(onChange).toHaveBeenCalledWith("live");
  });
});

function Controlled({ onPick }: { onPick?: (place: Place | null) => void }) {
  const [value, setValue] = useState<Place | null>(null);
  return (
    <PlaceInput
      label="Origin"
      value={value}
      onChange={(place) => {
        setValue(place);
        onPick?.(place);
      }}
    />
  );
}

describe("PlaceInput", () => {
  it("suggests places while typing and picks one with the mouse", () => {
    const onPick = vi.fn();
    render(<Controlled onPick={onPick} />);
    const box = screen.getByRole("combobox", { name: "Origin" });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "kolh" } });
    const list = screen.getByRole("listbox", { name: "Origin" });
    expect(within(list).getByRole("option", { name: /^Kolhapur/ })).toBeInTheDocument();
    fireEvent.mouseDown(within(list).getByRole("option", { name: /^Kolhapur/ }));
    expect(onPick).toHaveBeenLastCalledWith(expect.objectContaining({ name: "Kolhapur" }));
    expect(box).toHaveValue("Kolhapur");
  });

  it("works with the keyboard", () => {
    const onPick = vi.fn();
    render(<Controlled onPick={onPick} />);
    const box = screen.getByRole("combobox", { name: "Origin" });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "pu" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onPick).toHaveBeenLastCalledWith(expect.objectContaining({ name: "Pune" }));
  });

  it("explains when nothing matches and closes with Escape", () => {
    render(<Controlled />);
    const box = screen.getByRole("combobox", { name: "Origin" });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "zzzzqq" } });
    expect(screen.getByText(/No Maharashtra place matches/)).toBeInTheDocument();
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("leaves out places it is told to exclude", () => {
    render(
      <PlaceInput label="Destination" value={null} onChange={() => {}} exclude={["Pune"]} />,
    );
    const box = screen.getByRole("combobox", { name: "Destination" });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "pune" } });
    expect(screen.queryByRole("option", { name: /^Pune/ })).not.toBeInTheDocument();
  });
});

describe("ViaPicker", () => {
  function Harness({ initial = [] as Place[] }) {
    const [value, setValue] = useState<Place[]>(initial);
    return <ViaPicker value={value} onChange={setValue} exclude={["Pune", "Nanded"]} />;
  }
  const sangamner = findPlace("Sangamner")!;
  const sinnar = findPlace("Sinnar")!;

  it("adds towns in order, moves and removes them", () => {
    render(<Harness />);
    const box = screen.getByRole("combobox", { name: /Add a town/ });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "sangam" } });
    fireEvent.mouseDown(screen.getByRole("option", { name: /Sangamner/ }));
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "sinn" } });
    fireEvent.mouseDown(screen.getByRole("option", { name: /Sinnar/ }));
    const names = () => within(screen.getByRole("list", { name: "Route via" })).getAllByRole("listitem").map((li) => li.textContent);
    expect(names()[0]).toContain("Sangamner");
    expect(names()[1]).toContain("Sinnar");

    fireEvent.click(screen.getByRole("button", { name: "Move Sinnar earlier" }));
    expect(names()[0]).toContain("Sinnar");

    fireEvent.click(screen.getByRole("button", { name: "Remove Sinnar" }));
    expect(names()).toHaveLength(1);
  });

  it("does not move the first town earlier or the last one later", () => {
    render(<Harness initial={[sangamner, sinnar]} />);
    expect(screen.getByRole("button", { name: "Move Sangamner earlier" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move Sinnar later" })).toBeDisabled();
  });
});

describe("Modal and ConfirmDialog", () => {
  it("shows its content only while open and closes from the button", () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <Modal open={false} onClose={onClose} title="New service">
        <p>Body</p>
      </Modal>,
    );
    expect(screen.queryByText("Body")).not.toBeInTheDocument();
    rerender(
      <Modal open onClose={onClose} title="New service" description="Choose cities">
        <p>Body</p>
      </Modal>,
    );
    expect(screen.getByRole("heading", { name: "New service" })).toBeInTheDocument();
    expect(screen.getByText("Choose cities")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("ConfirmDialog asks and reports the answer", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Remove this bus?"
        message="It will be removed."
        confirmLabel="Remove bus"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(onCancel).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Remove bus" }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("ConfirmDialog disables both answers while working", () => {
    render(
      <ConfirmDialog open title="t" message="m" confirmLabel="Do it" busy onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Keep it" })).toBeDisabled();
  });
});
