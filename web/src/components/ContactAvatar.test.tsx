import { fireEvent, render, screen } from "@testing-library/react";

import ContactAvatar from "@/refresh-pages/crm/components/ContactAvatar";

describe("ContactAvatar", () => {
  test("renders initials when no profile picture is available", () => {
    render(<ContactAvatar firstName="Alice" lastName="Smith" />);

    expect(screen.getByText("AS")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  test("falls back to initials when the profile picture fails to load and resets for a new url", () => {
    const { rerender } = render(
      <ContactAvatar
        firstName="Alice"
        lastName="Smith"
        profilePictureUrl="/api/chat/file/file-1"
      />
    );

    const image = screen.getByRole("img", { name: "Alice Smith" });
    expect(image).toHaveAttribute("src", "/api/chat/file/file-1");

    fireEvent.error(image);

    expect(screen.getByText("AS")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    rerender(
      <ContactAvatar
        firstName="Alice"
        lastName="Smith"
        profilePictureUrl="/api/chat/file/file-2"
      />
    );

    expect(screen.getByRole("img", { name: "Alice Smith" })).toHaveAttribute(
      "src",
      "/api/chat/file/file-2"
    );
  });
});
