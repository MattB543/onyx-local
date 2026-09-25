/**
 * A file still indexing (e.g. one just promoted by "Index for later") shows a
 * spinner in Recent Files. The row sizes its icon through props, so the
 * spinner must take them, or it is left unsized and the row shows no icon.
 */
import React from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import { ChatFileType } from "@/app/app/interfaces";
import { ProjectFile, UserFileStatus } from "@/lib/projects/types";

function projectFile(
  id: string,
  name: string,
  status: UserFileStatus
): ProjectFile {
  return {
    id,
    name,
    project_id: null,
    user_id: "user-1",
    file_id: `file-${id}`,
    created_at: "2026-09-24T14:00:00Z",
    status,
    file_type: "text/plain",
    last_accessed_at: "2026-09-24T14:00:00Z",
    chat_file_type: ChatFileType.PLAIN_TEXT,
    token_count: null,
    chunk_count: null,
  };
}

const recentFiles = [
  projectFile("new", "qa-raw-c.txt", UserFileStatus.PROCESSING),
  projectFile("old", "notes.txt", UserFileStatus.COMPLETED),
];

jest.mock("@/lib/projects/providers", () => ({
  ...jest.requireActual("@/lib/projects/providers"),
  useProjectsContext: () => ({
    allRecentFiles: recentFiles,
    deleteUserFile: jest.fn(),
    setCurrentMessageFiles: jest.fn(),
  }),
}));

function rowIcon(fileName: string): SVGElement {
  const row = screen.getByText(fileName).closest("[data-opal-content]");
  const icon = row?.querySelector("svg");
  if (!icon) throw new Error(`no icon for ${fileName}`);
  return icon;
}

describe("FilePickerPopover recent files", () => {
  it("sizes the spinner of a file that is still processing", async () => {
    const user = setupUser();
    render(
      <FilePickerPopover
        handleUploadChange={jest.fn()}
        trigger={<button type="button">attach</button>}
      />
    );

    await user.click(screen.getByRole("button", { name: "attach" }));

    const spinner = rowIcon("qa-raw-c.txt");
    const fileIcon = rowIcon("notes.txt");
    expect(spinner.getAttribute("class")).toContain("animate-spin");
    expect(fileIcon.style.width).not.toBe("");
    expect(spinner.style.width).toBe(fileIcon.style.width);
    expect(spinner.style.height).toBe(fileIcon.style.height);
  }, 30_000);
});
