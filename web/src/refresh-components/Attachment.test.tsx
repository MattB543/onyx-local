import { render, screen, setupUser } from "@tests/setup/test-utils";
import Attachment from "@/refresh-components/Attachment";

describe("Attachment", () => {
  it("opens the file from the name by click and keyboard", async () => {
    const user = setupUser();
    const open = jest.fn();
    render(<Attachment fileName="notes.docx" open={open} />);

    const name = screen.getByRole("button", { name: /notes\.docx/ });
    await user.click(name);
    expect(open).toHaveBeenCalledTimes(1);

    name.focus();
    await user.keyboard("{Enter}");
    expect(open).toHaveBeenCalledTimes(2);
  });

  it("renders the name as plain text without an open action", () => {
    render(<Attachment fileName="notes.docx" />);
    expect(screen.getByText("notes.docx")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
