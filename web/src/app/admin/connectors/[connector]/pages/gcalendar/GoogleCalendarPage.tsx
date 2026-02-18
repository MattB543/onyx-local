"use client";

import React from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { ValidSources } from "@/lib/types";
import { usePublicCredentials } from "@/lib/hooks";
import Title from "@/components/ui/title";
import {
  Credential,
  GoogleCalendarCredentialJson,
  GoogleCalendarServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import {
  useGoogleAppCredential,
  useGoogleServiceAccountKey,
  useGoogleCredentials,
  useConnectorsByCredentialId,
  checkCredentialsFetched,
  filterUploadedCredentials,
  checkConnectorsExist,
  refreshAllGoogleData,
} from "@/lib/googleConnector";
import { useUser } from "@/providers/UserProvider";
import {
  GoogleCalendarAuthSection,
  GoogleCalendarJsonUploadSection,
} from "./Credential";

const GoogleCalendarMain = () => {
  const { isAdmin, user } = useUser();

  const {
    data: appCredentialData,
    isLoading: isAppCredentialLoading,
    error: isAppCredentialError,
  } = useGoogleAppCredential("google_calendar");

  const {
    data: serviceAccountKeyData,
    isLoading: isServiceAccountKeyLoading,
    error: isServiceAccountKeyError,
  } = useGoogleServiceAccountKey("google_calendar");

  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  const {
    data: googleCalendarCredentials,
    isLoading: isGoogleCalendarCredentialsLoading,
    error: googleCalendarCredentialsError,
  } = useGoogleCredentials(ValidSources.GoogleCalendar);

  const { credential_id } = filterUploadedCredentials(googleCalendarCredentials);

  const {
    data: googleCalendarConnectors,
    isLoading: isGoogleCalendarConnectorsLoading,
    error: googleCalendarConnectorsError,
    refreshConnectorsByCredentialId,
  } = useConnectorsByCredentialId(credential_id);

  const {
    appCredentialSuccessfullyFetched,
    serviceAccountKeySuccessfullyFetched,
  } = checkCredentialsFetched(
    appCredentialData,
    isAppCredentialError,
    serviceAccountKeyData,
    isServiceAccountKeyError
  );

  const handleRefresh = () => {
    refreshCredentials();
    refreshConnectorsByCredentialId();
    refreshAllGoogleData(ValidSources.GoogleCalendar);
  };

  if (
    (!appCredentialSuccessfullyFetched && isAppCredentialLoading) ||
    (!serviceAccountKeySuccessfullyFetched && isServiceAccountKeyLoading) ||
    (!credentialsData && isCredentialsLoading) ||
    (!googleCalendarCredentials && isGoogleCalendarCredentialsLoading) ||
    (!googleCalendarConnectors && isGoogleCalendarConnectorsLoading)
  ) {
    return (
      <div className="mx-auto">
        <LoadingAnimation text="" />
      </div>
    );
  }

  if (credentialsError || !credentialsData) {
    return <ErrorCallout errorTitle="Failed to load credentials." />;
  }

  if (googleCalendarCredentialsError || !googleCalendarCredentials) {
    return (
      <ErrorCallout errorTitle="Failed to load Google Calendar credentials." />
    );
  }

  if (
    !appCredentialSuccessfullyFetched ||
    !serviceAccountKeySuccessfullyFetched
  ) {
    return (
      <ErrorCallout errorTitle="Error loading Google Calendar app credentials. Contact an administrator." />
    );
  }

  if (googleCalendarConnectorsError) {
    return (
      <ErrorCallout errorTitle="Failed to load Google Calendar associated connectors." />
    );
  }

  const connectorAssociated = checkConnectorsExist(googleCalendarConnectors);

  const googleCalendarPublicUploadedCredential:
    | Credential<GoogleCalendarCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_tokens &&
      credential.admin_public &&
      credential.source === "google_calendar" &&
      credential.credential_json.authentication_method !== "oauth_interactive"
  );

  const googleCalendarServiceAccountCredential:
    | Credential<GoogleCalendarServiceAccountCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.source === "google_calendar"
  );

  return (
    <>
      <Title className="mb-2 mt-6">Step 1: Provide your Credentials</Title>
      <GoogleCalendarJsonUploadSection
        appCredentialData={appCredentialData}
        serviceAccountCredentialData={serviceAccountKeyData}
        isAdmin={isAdmin}
        onSuccess={handleRefresh}
        existingAuthCredential={Boolean(
          googleCalendarPublicUploadedCredential ||
            googleCalendarServiceAccountCredential
        )}
      />

      {isAdmin &&
        (appCredentialData?.client_id ||
          serviceAccountKeyData?.service_account_email) && (
          <>
            <Title className="mb-2 mt-6">Step 2: Authenticate with Onyx</Title>
            <GoogleCalendarAuthSection
              refreshCredentials={handleRefresh}
              googleCalendarPublicUploadedCredential={
                googleCalendarPublicUploadedCredential
              }
              googleCalendarServiceAccountCredential={
                googleCalendarServiceAccountCredential
              }
              appCredentialData={appCredentialData}
              serviceAccountKeyData={serviceAccountKeyData}
              connectorAssociated={connectorAssociated}
              user={user}
            />
          </>
        )}
    </>
  );
};

export default GoogleCalendarMain;
