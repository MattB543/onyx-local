import { buildUrl, UrlBuilder } from "@/lib/utilsSS";
import {
  AuthType,
  NEXT_PUBLIC_CLOUD_ENABLED,
  SERVER_SIDE_ONLY__AUTH_TYPE,
} from "@/lib/constants";
import { User, UserRole } from "@/lib/types";
import { getCurrentUserSS } from "@/lib/users/svcSS";
import { AuthTypeMetadata } from "@/lib/auth/types";

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

export async function getAuthTypeMetadataSS(): Promise<AuthTypeMetadata> {
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
}

async function getOIDCAuthUrlSS(nextUrl: string | null): Promise<string> {
  const url = UrlBuilder.fromClientUrl("/api/auth/oidc/authorize");
  if (nextUrl) url.addParam("next", nextUrl);
  url.addParam("redirect", true);
  return url.toString();
}

async function getGoogleOAuthUrlSS(nextUrl: string | null): Promise<string> {
  const url = UrlBuilder.fromClientUrl("/api/auth/oauth/authorize");
  if (nextUrl) url.addParam("next", nextUrl);
  url.addParam("redirect", true);
  return url.toString();
}

async function getSAMLAuthUrlSS(nextUrl: string | null): Promise<string> {
  const url = UrlBuilder.fromInternalUrl("/auth/saml/authorize");
  if (nextUrl) url.addParam("next", nextUrl);

  const res = await fetch(url.toString());
  if (!res.ok) throw new Error("Failed to fetch data");

  const data: { authorization_url: string } = await res.json();
  return data.authorization_url;
}

export async function getAuthUrlSS(
  authType: AuthType,
  nextUrl: string | null
): Promise<string> {
  switch (authType) {
    case AuthType.BASIC:
      return "";
    case AuthType.GOOGLE_OAUTH:
    case AuthType.CLOUD:
      return getGoogleOAuthUrlSS(nextUrl);
    case AuthType.SAML:
      return getSAMLAuthUrlSS(nextUrl);
    case AuthType.OIDC:
      return getOIDCAuthUrlSS(nextUrl);
  }
}

async function logoutStandardSS(headers: Headers): Promise<Response> {
  return fetch(buildUrl("/auth/logout"), { method: "POST", headers });
}

async function logoutSAMLSS(headers: Headers): Promise<Response> {
  return fetch(buildUrl("/auth/saml/logout"), { method: "POST", headers });
}

export async function logoutSS(
  authType: AuthType,
  headers: Headers
): Promise<Response | null> {
  switch (authType) {
    case AuthType.SAML:
      return logoutSAMLSS(headers);
    default:
      return logoutStandardSS(headers);
  }
}

// ---------------------------------------------------------------------------
// Auth guards
// ---------------------------------------------------------------------------

interface AuthCheckResult {
  user: User | null;
  authTypeMetadata: AuthTypeMetadata | null;
  redirect?: string;
}

const ADMIN_ALLOWED_ROLES = [
  UserRole.ADMIN,
  UserRole.CURATOR,
  UserRole.GLOBAL_CURATOR,
];

export async function requireAuth(): Promise<AuthCheckResult> {
  let user: User | null = null;
  let authTypeMetadata: AuthTypeMetadata | null = null;

  try {
    [authTypeMetadata, user] = await Promise.all([
      getAuthTypeMetadataSS(),
      getCurrentUserSS(),
    ]);
  } catch (e) {
    console.log(`Failed to fetch auth information - ${e}`);
  }

  if (!user) {
    return { user, authTypeMetadata, redirect: "/auth/login" };
  }

  if (user && !user.is_verified && authTypeMetadata?.requiresVerification) {
    return {
      user,
      authTypeMetadata,
      redirect: "/auth/waiting-on-verification",
    };
  }

  return { user, authTypeMetadata };
}

export async function requireAdminAuth(): Promise<AuthCheckResult> {
  const authResult = await requireAuth();

  if (authResult.redirect) {
    return authResult;
  }

  const { user, authTypeMetadata } = authResult;

  if (user && !ADMIN_ALLOWED_ROLES.includes(user.role)) {
    return { user, authTypeMetadata, redirect: "/app" };
  }

  return authResult;
}
