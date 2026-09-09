"use client";

import React from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { ValidSources } from "@/lib/types";
import { usePublicCredentials } from "@/lib/hooks";
import { CalendarAuthSection } from "./Credential";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import {
  useGoogleCredentials,
  refreshAllGoogleData,
} from "@/lib/googleConnector";

const GoogleCalendarMain = () => {
  const { user } = useUser();
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );

  // Get all public credentials
  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  // Get Google Calendar-specific credentials
  const {
    data: googleCalendarCredentials,
    isLoading: isGoogleCalendarCredentialsLoading,
    error: googleCalendarCredentialsError,
  } = useGoogleCredentials(ValidSources.GoogleCalendar);

  // Handle refresh of all data
  const handleRefresh = () => {
    refreshCredentials();
    refreshAllGoogleData(ValidSources.GoogleCalendar);
  };

  // Loading state
  if (
    (!credentialsData && isCredentialsLoading) ||
    (!googleCalendarCredentials && isGoogleCalendarCredentialsLoading)
  ) {
    return (
      <div className="mx-auto">
        <LoadingAnimation text="" />
      </div>
    );
  }

  // Error states
  if (credentialsError || !credentialsData) {
    return <ErrorCallout errorTitle="Failed to load credentials." />;
  }

  if (googleCalendarCredentialsError || !googleCalendarCredentials) {
    return (
      <ErrorCallout errorTitle="Failed to load Google Calendar credentials." />
    );
  }

  return (
    <>
      {isGlobalHolder && (
        <>
          <CalendarAuthSection refreshCredentials={handleRefresh} user={user} />
        </>
      )}
    </>
  );
};

export default GoogleCalendarMain;
