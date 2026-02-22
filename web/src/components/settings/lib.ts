import {
  CombinedSettings,
  EnterpriseSettings,
  ApplicationStatus,
  Settings,
  QueryHistoryType,
} from "@/app/admin/settings/interfaces";
import {
  CUSTOM_ANALYTICS_ENABLED,
  HOST_URL,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
} from "@/lib/constants";
import { fetchSS } from "@/lib/utilsSS";
import { getWebVersion } from "@/lib/version";

export enum SettingsError {
  OTHER = "OTHER",
}

function buildFallbackSettings(): Settings {
  return {
    auto_scroll: true,
    application_status: ApplicationStatus.ACTIVE,
    gpu_enabled: false,
    maximum_chat_retention_days: null,
    notifications: [],
    needs_reindexing: false,
    anonymous_user_enabled: false,
    deep_research_enabled: true,
    temperature_override_enabled: true,
    query_history_type: QueryHistoryType.NORMAL,
  };
}

export async function fetchStandardSettingsSS() {
  return fetchSS("/settings");
}

export async function fetchEnterpriseSettingsSS() {
  return fetchSS("/enterprise-settings");
}

export async function fetchCustomAnalyticsScriptSS() {
  return fetchSS("/enterprise-settings/custom-analytics-script");
}

export async function fetchSettingsSS(): Promise<CombinedSettings | null> {
  const tasks = [fetchStandardSettingsSS()];
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    tasks.push(fetchEnterpriseSettingsSS());
    if (CUSTOM_ANALYTICS_ENABLED) {
      tasks.push(fetchCustomAnalyticsScriptSS());
    }
  }

  try {
    const results = await Promise.allSettled(tasks);

    let settings: Settings = buildFallbackSettings();

    const standardResult = results[0];
    if (!standardResult) {
      console.warn(
        "fetchStandardSettingsSS missing result; using fallback settings."
      );
    } else if (standardResult.status === "rejected") {
      console.warn(
        "fetchStandardSettingsSS rejected; using fallback settings.",
        standardResult.reason
      );
    } else if (!standardResult.value.ok) {
      if (
        standardResult.value.status !== 403 &&
        standardResult.value.status !== 401
      ) {
        console.warn(
          `fetchStandardSettingsSS failed: status=${standardResult.value.status}`
        );
      }
    } else {
      settings = await standardResult.value.json();
    }

    let enterpriseSettings: EnterpriseSettings | null = null;
    if (tasks.length > 1) {
      const enterpriseResult = results[1];
      if (!enterpriseResult) {
        console.warn("fetchEnterpriseSettingsSS missing result; using null.");
      } else if (enterpriseResult.status === "rejected") {
        console.warn(
          "fetchEnterpriseSettingsSS rejected; using null.",
          enterpriseResult.reason
        );
      } else if (!enterpriseResult.value.ok) {
        if (
          enterpriseResult.value.status !== 403 &&
          enterpriseResult.value.status !== 401
        ) {
          console.warn(
            `fetchEnterpriseSettingsSS failed: status=${enterpriseResult.value.status}`
          );
        }
      } else {
        enterpriseSettings = await enterpriseResult.value.json();
      }
    }

    let customAnalyticsScript: string | null = null;
    if (tasks.length > 2) {
      const analyticsResult = results[2];
      if (!analyticsResult) {
        console.warn(
          "fetchCustomAnalyticsScriptSS missing result; using null."
        );
      } else if (analyticsResult.status === "rejected") {
        console.warn(
          "fetchCustomAnalyticsScriptSS rejected; using null.",
          analyticsResult.reason
        );
      } else if (!analyticsResult.value.ok) {
        if (analyticsResult.value.status !== 403) {
          console.warn(
            `fetchCustomAnalyticsScriptSS failed: status=${analyticsResult.value.status}`
          );
        }
      } else {
        customAnalyticsScript = await analyticsResult.value.json();
      }
    }

    if (settings.deep_research_enabled == null) {
      settings.deep_research_enabled = true;
    }

    const webVersion = getWebVersion();

    const combinedSettings: CombinedSettings = {
      settings,
      enterpriseSettings,
      customAnalyticsScript,
      webVersion,
      webDomain: HOST_URL,
    };

    return combinedSettings;
  } catch (error) {
    console.warn(
      "fetchSettingsSS unexpected exception; using fallback settings.",
      error
    );
    const webVersion = getWebVersion();

    return {
      settings: buildFallbackSettings(),
      enterpriseSettings: null,
      customAnalyticsScript: null,
      webVersion,
      webDomain: HOST_URL,
    };
  }
}
