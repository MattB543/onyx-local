import {
  GmailConfig,
  GoogleCalendarConfig,
} from "@/lib/connectors/connectors";
import {
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
  GoogleCalendarCredentialJson,
  GoogleCalendarServiceAccountCredentialJson,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { usePublicCredentials } from "@/lib/hooks";

export const gmailConnectorNameBuilder = (_values: GmailConfig) =>
  "GmailConnector";

export const googleCalendarConnectorNameBuilder = (
  _values: GoogleCalendarConfig
) => "GoogleCalendarConnector";

export const useGmailCredentials = (connector: string) => {
  const { data: credentialsData } = usePublicCredentials();

  const gmailPublicCredential: Credential<GmailCredentialJson> | undefined =
    credentialsData?.find(
      (credential) =>
        credential.credential_json?.google_tokens &&
        credential.admin_public &&
        credential.source === connector
    );

  const gmailServiceAccountCredential:
    | Credential<GmailServiceAccountCredentialJson>
    | undefined = credentialsData?.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.admin_public &&
      credential.source === connector
  );

  const liveGmailCredential =
    gmailPublicCredential || gmailServiceAccountCredential;

  return {
    liveGmailCredential,
  };
};

export const useGoogleDriveCredentials = (connector: string) => {
  const { data: credentialsData } = usePublicCredentials();

  const googleDrivePublicCredential:
    | Credential<GoogleDriveCredentialJson>
    | undefined = credentialsData?.find(
    (credential) =>
      credential.credential_json?.google_tokens &&
      credential.admin_public &&
      credential.source === connector
  );

  const googleDriveServiceAccountCredential:
    | Credential<GoogleDriveServiceAccountCredentialJson>
    | undefined = credentialsData?.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.admin_public &&
      credential.source === connector
  );

  const liveGDriveCredential =
    googleDrivePublicCredential || googleDriveServiceAccountCredential;

  return {
    liveGDriveCredential,
  };
};

export const useGoogleCalendarCredentials = (connector: string) => {
  const { data: credentialsData } = usePublicCredentials();

  const googleCalendarPublicCredential:
    | Credential<GoogleCalendarCredentialJson>
    | undefined = credentialsData?.find(
    (credential) =>
      credential.credential_json?.google_tokens &&
      credential.admin_public &&
      credential.source === connector
  );

  const googleCalendarServiceAccountCredential:
    | Credential<GoogleCalendarServiceAccountCredentialJson>
    | undefined = credentialsData?.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.admin_public &&
      credential.source === connector
  );

  const liveGoogleCalendarCredential =
    googleCalendarPublicCredential || googleCalendarServiceAccountCredential;

  return {
    liveGoogleCalendarCredential,
  };
};
