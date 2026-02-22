import { ReadonlyRequestCookies } from "next/dist/server/web/spec-extension/adapters/request-cookies";
import { cookies } from "next/headers";

import {
  AuthType,
  NEXT_PUBLIC_CLOUD_ENABLED,
  SERVER_SIDE_ONLY__AUTH_TYPE,
} from "./constants";
import { User } from "./types";
import { buildUrl, UrlBuilder } from "./utilsSS";

export interface AuthTypeMetadata {
  authType: AuthType;
  autoRedirect: boolean;
  requiresVerification: boolean;
  anonymousUserEnabled: boolean | null;
  passwordMinLength: number;
  hasUsers: boolean;
  oauthEnabled: boolean;
}

const AUTH_TYPE_VALUES = new Set<string>(Object.values(AuthType));

function resolveAuthType(rawAuthType: string | null | undefined): AuthType {
  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    return AuthType.CLOUD;
  }

  if (rawAuthType && AUTH_TYPE_VALUES.has(rawAuthType)) {
    return rawAuthType as AuthType;
  }

  return SERVER_SIDE_ONLY__AUTH_TYPE;
}

function buildFallbackAuthTypeMetadata(): AuthTypeMetadata {
  const fallbackAuthType = resolveAuthType(null);
  return {
    authType: fallbackAuthType,
    autoRedirect:
      fallbackAuthType === AuthType.OIDC || fallbackAuthType === AuthType.SAML,
    requiresVerification: false,
    anonymousUserEnabled: null,
    passwordMinLength: 8,
    hasUsers: true,
    oauthEnabled: false,
  };
}

export const getAuthTypeMetadataSS = async (): Promise<AuthTypeMetadata> => {
  try {
    const res = await fetch(buildUrl("/auth/type"));
    if (!res.ok) {
      console.warn(
        `getAuthTypeMetadataSS: /auth/type failed with status ${res.status}, using fallback.`
      );
      return buildFallbackAuthTypeMetadata();
    }

    const data = (await res.json()) as {
      auth_type?: string;
      requires_verification?: boolean;
      anonymous_user_enabled?: boolean | null;
      password_min_length?: number;
      has_users?: boolean;
      oauth_enabled?: boolean;
    };

    const authType = resolveAuthType(data.auth_type);
    const requiresVerification =
      typeof data.requires_verification === "boolean"
        ? data.requires_verification
        : false;
    const anonymousUserEnabled =
      typeof data.anonymous_user_enabled === "boolean"
        ? data.anonymous_user_enabled
        : null;
    const passwordMinLength =
      typeof data.password_min_length === "number"
        ? data.password_min_length
        : 8;
    const hasUsers =
      typeof data.has_users === "boolean" ? data.has_users : true;
    const oauthEnabled =
      typeof data.oauth_enabled === "boolean" ? data.oauth_enabled : false;

    // for SAML / OIDC, we auto-redirect the user to the IdP when the user visits
    // Onyx in an un-authenticated state
    return {
      authType,
      autoRedirect: authType === AuthType.OIDC || authType === AuthType.SAML,
      requiresVerification,
      anonymousUserEnabled,
      passwordMinLength,
      hasUsers,
      oauthEnabled,
    };
  } catch (error) {
    console.warn("getAuthTypeMetadataSS exception; using fallback.", error);
    return buildFallbackAuthTypeMetadata();
  }
};

const getOIDCAuthUrlSS = async (nextUrl: string | null): Promise<string> => {
  const url = UrlBuilder.fromClientUrl("/api/auth/oidc/authorize");
  if (nextUrl) {
    url.addParam("next", nextUrl);
  }
  url.addParam("redirect", true);

  return url.toString();
};

const getGoogleOAuthUrlSS = async (nextUrl: string | null): Promise<string> => {
  const url = UrlBuilder.fromClientUrl("/api/auth/oauth/authorize");
  if (nextUrl) {
    url.addParam("next", nextUrl);
  }
  url.addParam("redirect", true);

  return url.toString();
};

const getSAMLAuthUrlSS = async (nextUrl: string | null): Promise<string> => {
  const url = UrlBuilder.fromInternalUrl("/auth/saml/authorize");
  if (nextUrl) {
    url.addParam("next", nextUrl);
  }

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: { authorization_url: string } = await res.json();
  return data.authorization_url;
};

export const getAuthUrlSS = async (
  authType: AuthType,
  nextUrl: string | null
): Promise<string> => {
  // Returns the auth url for the given auth type

  switch (authType) {
    case AuthType.BASIC:
      return "";
    case AuthType.GOOGLE_OAUTH: {
      return await getGoogleOAuthUrlSS(nextUrl);
    }
    case AuthType.CLOUD: {
      return await getGoogleOAuthUrlSS(nextUrl);
    }
    case AuthType.SAML: {
      return await getSAMLAuthUrlSS(nextUrl);
    }
    case AuthType.OIDC: {
      return await getOIDCAuthUrlSS(nextUrl);
    }
  }
};

const logoutStandardSS = async (headers: Headers): Promise<Response> => {
  return await fetch(buildUrl("/auth/logout"), {
    method: "POST",
    headers: headers,
  });
};

const logoutSAMLSS = async (headers: Headers): Promise<Response> => {
  return await fetch(buildUrl("/auth/saml/logout"), {
    method: "POST",
    headers: headers,
  });
};

export const logoutSS = async (
  authType: AuthType,
  headers: Headers
): Promise<Response | null> => {
  switch (authType) {
    case AuthType.SAML: {
      return await logoutSAMLSS(headers);
    }
    default: {
      return await logoutStandardSS(headers);
    }
  }
};

export const getCurrentUserSS = async (): Promise<User | null> => {
  try {
    const cookieString = processCookies(await cookies());

    const response = await fetch(buildUrl("/me"), {
      credentials: "include",
      next: { revalidate: 0 },
      headers: {
        cookie: cookieString,
      },
    });

    if (!response.ok) {
      return null;
    }

    const user = await response.json();
    return user;
  } catch (e) {
    console.log(`Error fetching user: ${e}`);
    return null;
  }
};

export const processCookies = (cookies: ReadonlyRequestCookies): string => {
  let cookieString = cookies
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");

  // Inject debug auth cookie for local development against remote backend (only if not already present)
  if (process.env.DEBUG_AUTH_COOKIE && process.env.NODE_ENV === "development") {
    const hasAuthCookie = cookieString
      .split(/;\s*/)
      .some((c) => c.startsWith("fastapiusersauth="));
    if (!hasAuthCookie) {
      const debugCookie = `fastapiusersauth=${process.env.DEBUG_AUTH_COOKIE}`;
      cookieString = cookieString
        ? `${cookieString}; ${debugCookie}`
        : debugCookie;
    }
  }

  return cookieString;
};
