import React, { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { SWRConfig } from "swr";
import englishMessages from "@/i18n/messages/en.json";
import { ChatFileType } from "@/app/app/interfaces";
import { ProjectsProvider, useProjectsContext } from "@/lib/projects/providers";
import { UserFileStatus, type ProjectFile } from "@/lib/projects/types";

const mockUploadFiles = jest.fn();
const mockGetRecentFiles = jest.fn();
const mockToastWarning = jest.fn();
const mockRecentFilesFetcher = jest.fn();

jest.mock("@/lib/fetcher", () => ({
  ...jest.requireActual("@/lib/fetcher"),
  errorHandlingFetcher: (...args: unknown[]) => mockRecentFilesFetcher(...args),
}));

jest.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: () => null,
  }),
}));

jest.mock("@/lib/position/hooks", () => ({
  useAppPosition: () => ({ openNewSession: jest.fn() }),
}));

jest.mock("@/lib/projects/hooks", () => ({
  useProjects: () => ({
    projects: [],
    refreshProjects: jest.fn().mockResolvedValue([]),
  }),
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    user_file_max_upload_size_mb: 1,
    enterprise: null,
    appName: "Onyx",
    vectorDbEnabled: true,
    isLoading: false,
    error: undefined,
  }),
}));

jest.mock("@opal/layouts/toast/store", () => ({
  toast: {
    warning: (...args: unknown[]) => mockToastWarning(...args),
    error: jest.fn(),
    success: jest.fn(),
  },
}));

jest.mock("@/lib/projects/svc", () => {
  const actual = jest.requireActual("@/lib/projects/svc");
  return {
    ...actual,
    fetchProjects: jest.fn().mockResolvedValue([]),
    createProject: jest.fn(),
    uploadFiles: (...args: unknown[]) => mockUploadFiles(...args),
    getRecentFiles: (...args: unknown[]) => mockGetRecentFiles(...args),
    getFilesInProject: jest.fn().mockResolvedValue([]),
    getProject: jest.fn(),
    getProjectInstructions: jest.fn(),
    upsertProjectInstructions: jest.fn(),
    getProjectDetails: jest.fn(),
    renameProject: jest.fn(),
    deleteProject: jest.fn(),
    deleteUserFile: jest.fn(),
    getUserFileStatuses: jest.fn().mockResolvedValue([]),
    unlinkFileFromProject: jest.fn(),
    linkFileToProject: jest.fn(),
  };
});

const wrapper = ({ children }: PropsWithChildren) => (
  <NextIntlClientProvider locale="en" messages={englishMessages}>
    <ProjectsProvider>{children}</ProjectsProvider>
  </NextIntlClientProvider>
);

describe("ProjectsContext beginUpload size precheck", () => {
  beforeEach(() => {
    mockUploadFiles.mockReset();
    mockGetRecentFiles.mockReset();
    mockToastWarning.mockReset();

    mockUploadFiles.mockResolvedValue({
      user_files: [],
      rejected_files: [],
    });
    mockGetRecentFiles.mockResolvedValue([]);
  });

  it("only sends valid files to the upload API when oversized files are present", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const valid = new File(["small"], "small.txt", { type: "text/plain" });
    const oversized = new File([new Uint8Array(2 * 1024 * 1024)], "big.txt", {
      type: "text/plain",
    });

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [valid, oversized],
        null
      );
    });

    expect(mockUploadFiles).toHaveBeenCalledTimes(1);
    const [uploadedFiles] = mockUploadFiles.mock.calls[0];
    expect((uploadedFiles as File[]).map((f) => f.name)).toEqual(["small.txt"]);
    expect(optimisticFiles.map((f) => f.name)).toEqual(["small.txt"]);
    expect(mockToastWarning).toHaveBeenCalledTimes(1);
  });

  it("uploads all files when none are oversized", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const first = new File(["small"], "first.txt", { type: "text/plain" });
    const second = new File(["small"], "second.txt", { type: "text/plain" });

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload([first, second], null);
    });

    expect(mockUploadFiles).toHaveBeenCalledTimes(1);
    const [uploadedFiles] = mockUploadFiles.mock.calls[0];
    expect((uploadedFiles as File[]).map((f) => f.name)).toEqual([
      "first.txt",
      "second.txt",
    ]);
    expect(mockToastWarning).not.toHaveBeenCalled();
    expect(optimisticFiles.map((f) => f.name)).toEqual([
      "first.txt",
      "second.txt",
    ]);
  });

  it("does not call upload API when all files are oversized", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const oversized = new File(
      [new Uint8Array(2 * 1024 * 1024)],
      "too-big.txt",
      { type: "text/plain" }
    );
    const onSuccess = jest.fn();
    const onFailure = jest.fn();

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [oversized],
        null,
        onSuccess,
        onFailure
      );
    });

    expect(mockUploadFiles).not.toHaveBeenCalled();
    expect(optimisticFiles).toEqual([]);
    expect(mockToastWarning).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onFailure).toHaveBeenCalledWith([]);
  });

  it("reports the optimistic temp id via onFailure when the server rejects a file", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const rejected = new File(["small"], "too-many-tokens.txt", {
      type: "text/plain",
    });
    const onSuccess = jest.fn();
    const onFailure = jest.fn();

    mockUploadFiles.mockResolvedValue({
      user_files: [],
      rejected_files: [
        { file_name: "too-many-tokens.txt", reason: "Exceeds token limit" },
      ],
    });

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [rejected],
        null,
        onSuccess,
        onFailure
      );
    });

    const tempId = optimisticFiles[0]?.temp_id;
    expect(tempId).toBeTruthy();
    expect(mockUploadFiles).toHaveBeenCalledTimes(1);
    expect(mockToastWarning).toHaveBeenCalledTimes(1);
    // AgentEditorPage relies on this callback firing with the failed temp id
    // to strip the file from user_file_ids; otherwise the submit button stays
    // disabled forever waiting on a phantom "uploading" file.
    expect(onFailure).toHaveBeenCalledWith([tempId]);
  });
});

function makeRecentFile(id: string, name: string): ProjectFile {
  return {
    id,
    name,
    project_id: null,
    user_id: "user-1",
    file_id: `file-${id}`,
    created_at: "2026-09-23T00:00:00Z",
    status: UserFileStatus.COMPLETED,
    file_type: "application/pdf",
    last_accessed_at: "2026-09-23T00:00:00Z",
    chat_file_type: ChatFileType.DOCUMENT,
    token_count: null,
    chunk_count: null,
  };
}

describe("ProjectsContext recent files sync", () => {
  // A fresh SWR cache per test, so no fetch result leaks between tests.
  const isolatedWrapper = ({ children }: PropsWithChildren) => (
    <SWRConfig value={{ provider: () => new Map() }}>
      {wrapper({ children })}
    </SWRConfig>
  );

  beforeEach(() => {
    mockRecentFilesFetcher.mockReset();
  });

  it("prepends files that a refresh returns for the first time", async () => {
    const known = makeRecentFile("known", "Known.pdf");
    const promoted = makeRecentFile("promoted", "Promoted.pdf");
    mockRecentFilesFetcher.mockResolvedValueOnce([known]);

    const { result } = renderHook(() => useProjectsContext(), {
      wrapper: isolatedWrapper,
    });
    await waitFor(() =>
      expect(result.current.allRecentFiles.map((f) => f.id)).toEqual(["known"])
    );

    // A chat send promoted an "Index for later" upload; the known file was
    // also renamed on the server.
    mockRecentFilesFetcher.mockResolvedValueOnce([
      promoted,
      { ...known, name: "Renamed.pdf" },
    ]);
    await act(async () => {
      await result.current.refreshRecentFiles();
    });

    await waitFor(() =>
      expect(result.current.allRecentFiles.map((f) => [f.id, f.name])).toEqual([
        ["promoted", "Promoted.pdf"],
        ["known", "Renamed.pdf"],
      ])
    );
  });
});
