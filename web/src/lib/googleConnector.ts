import useSWR, { mutate } from "swr";
import { FetchError, errorHandlingFetcher } from "@/lib/fetcher";
import { Credential } from "@/lib/connectors/credentials";
import { ConnectorSnapshot } from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/types";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";

// Constants for service names to avoid typos
export const GOOGLE_SERVICES = {
  GMAIL: "gmail",
  GOOGLE_DRIVE: "google-drive",
  GOOGLE_CALENDAR: "google-calendar",
} as const;

type GoogleConnectorService = "gmail" | "google_drive" | "google_calendar";

const mapServiceToEndpoint = (service: GoogleConnectorService) => {
  if (service === "gmail") {
    return GOOGLE_SERVICES.GMAIL;
  }
  if (service === "google_drive") {
    return GOOGLE_SERVICES.GOOGLE_DRIVE;
  }
  return GOOGLE_SERVICES.GOOGLE_CALENDAR;
};

export const useGoogleAppCredential = (service: GoogleConnectorService) => {
  const endpoint = `/api/manage/admin/connector/${mapServiceToEndpoint(
    service
  )}/app-credential`;

  return useSWR<{ client_id: string }, FetchError>(
    endpoint,
    errorHandlingFetcher
  );
};

export const useGoogleServiceAccountKey = (service: GoogleConnectorService) => {
  const endpoint = `/api/manage/admin/connector/${mapServiceToEndpoint(
    service
  )}/service-account-key`;

  return useSWR<{ service_account_email: string }, FetchError>(
    endpoint,
    errorHandlingFetcher
  );
};

export const useGoogleCredentials = (
  source:
    | ValidSources.Gmail
    | ValidSources.GoogleDrive
    | ValidSources.GoogleCalendar
) => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(source),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );
};

export const useConnectorsByCredentialId = (credential_id: number | null) => {
  let url: string | null = null;
  if (credential_id !== null) {
    url = `/api/manage/admin/connector?credential=${credential_id}`;
  }
  const swrResponse = useSWR<ConnectorSnapshot[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshConnectorsByCredentialId: () => mutate(url),
  };
};

export const checkCredentialsFetched = (
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  appCredentialData: any,
  appCredentialError: FetchError | undefined,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  serviceAccountKeyData: any,
  serviceAccountKeyError: FetchError | undefined
) => {
  const appCredentialSuccessfullyFetched =
    appCredentialData ||
    (appCredentialError && appCredentialError.status === 404);

  const serviceAccountKeySuccessfullyFetched =
    serviceAccountKeyData ||
    (serviceAccountKeyError && serviceAccountKeyError.status === 404);

  return {
    appCredentialSuccessfullyFetched,
    serviceAccountKeySuccessfullyFetched,
  };
};

export const filterUploadedCredentials = <
  T extends { authentication_method?: string },
>(
  credentials: Credential<T>[] | undefined
): { credential_id: number | null; uploadedCredentials: Credential<T>[] } => {
  let credential_id = null;
  let uploadedCredentials: Credential<T>[] = [];

  if (credentials) {
    uploadedCredentials = credentials.filter(
      (credential) =>
        credential.credential_json.authentication_method !== "oauth_interactive"
    );

    if (uploadedCredentials.length > 0 && uploadedCredentials[0]) {
      credential_id = uploadedCredentials[0].id;
    }
  }

  return { credential_id, uploadedCredentials };
};

export const checkConnectorsExist = (
  connectors: ConnectorSnapshot[] | undefined
): boolean => {
  return !!connectors && connectors.length > 0;
};

export const refreshAllGoogleData = (
  source:
    | ValidSources.Gmail
    | ValidSources.GoogleDrive
    | ValidSources.GoogleCalendar
) => {
  mutate(buildSimilarCredentialInfoURL(source));

  const service =
    source === ValidSources.Gmail
      ? GOOGLE_SERVICES.GMAIL
      : source === ValidSources.GoogleDrive
        ? GOOGLE_SERVICES.GOOGLE_DRIVE
        : GOOGLE_SERVICES.GOOGLE_CALENDAR;
  mutate(`/api/manage/admin/connector/${service}/app-credential`);
  mutate(`/api/manage/admin/connector/${service}/service-account-key`);
};
