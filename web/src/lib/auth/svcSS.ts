import "server-only";

import { buildUrl, UrlBuilder } from "@/lib/utilsSS";
import { getDomain } from "@/lib/redirectSS";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { NextRequest, NextResponse } from "next/server";
import { AuthTypeMetadata, type SSOProviderType } from "@/lib/auth/types";
import { User, UserRole } from "@/lib/types";
import { getCurrentUserSS } from "@/lib/users/svcSS";

// Fork: a failing/slow /auth/type must never hard-fail a server render, so
// fall back to conservative single-tenant metadata instead of throwing.
function buildFallbackAuthTypeMetadata(): AuthTypeMetadata {
  return {
    multiTenant: NEXT_PUBLIC_CLOUD_ENABLED,
    requiresVerification: false,
    anonymousUserEnabled: null,
    passwordMinLength: 8,
    passwordMaxLength: 128,
    passwordRequireUppercase: false,
    passwordRequireLowercase: false,
    passwordRequireDigit: false,
    passwordRequireSpecialChar: false,
    hasUsers: true,
    oauthEnabled: false,
    passwordAuthEnabled: true,
    ssoProviders: [],
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
      multi_tenant?: boolean;
      requires_verification?: boolean;
      anonymous_user_enabled?: boolean | null;
      password_min_length?: number;
      password_max_length?: number;
      password_require_uppercase?: boolean;
      password_require_lowercase?: boolean;
      password_require_digit?: boolean;
      password_require_special_char?: boolean;
      has_users?: boolean;
      oauth_enabled?: boolean;
      password_auth_enabled?: boolean;
      sso_providers?: {
        name: string;
        display_name: string;
        provider_type: SSOProviderType;
        authorize_url: string;
      }[];
    };

    const fallback = buildFallbackAuthTypeMetadata();
    return {
      multiTenant: NEXT_PUBLIC_CLOUD_ENABLED
        ? true
        : typeof data.multi_tenant === "boolean"
          ? data.multi_tenant
          : fallback.multiTenant,
      requiresVerification:
        typeof data.requires_verification === "boolean"
          ? data.requires_verification
          : fallback.requiresVerification,
      anonymousUserEnabled:
        typeof data.anonymous_user_enabled === "boolean"
          ? data.anonymous_user_enabled
          : null,
      passwordMinLength:
        typeof data.password_min_length === "number"
          ? data.password_min_length
          : fallback.passwordMinLength,
      passwordMaxLength:
        typeof data.password_max_length === "number"
          ? data.password_max_length
          : fallback.passwordMaxLength,
      passwordRequireUppercase:
        typeof data.password_require_uppercase === "boolean"
          ? data.password_require_uppercase
          : false,
      passwordRequireLowercase:
        typeof data.password_require_lowercase === "boolean"
          ? data.password_require_lowercase
          : false,
      passwordRequireDigit:
        typeof data.password_require_digit === "boolean"
          ? data.password_require_digit
          : false,
      passwordRequireSpecialChar:
        typeof data.password_require_special_char === "boolean"
          ? data.password_require_special_char
          : false,
      hasUsers: typeof data.has_users === "boolean" ? data.has_users : true,
      oauthEnabled:
        typeof data.oauth_enabled === "boolean" ? data.oauth_enabled : false,
      passwordAuthEnabled:
        typeof data.password_auth_enabled === "boolean"
          ? data.password_auth_enabled
          : true,
      ssoProviders: (data.sso_providers ?? []).map((provider) => ({
        name: provider.name,
        displayName: provider.display_name,
        providerType: provider.provider_type,
        authorizeUrl: provider.authorize_url,
      })),
    };
  } catch (error) {
    console.warn("getAuthTypeMetadataSS exception; using fallback.", error);
    return buildFallbackAuthTypeMetadata();
  }
}

async function getGoogleOAuthUrlSS(nextUrl: string | null): Promise<string> {
  const url = UrlBuilder.fromClientUrl("/api/auth/oauth/authorize");
  if (nextUrl) url.addParam("next", nextUrl);
  url.addParam("redirect", true);
  return url.toString();
}

export async function getAuthUrlSS(
  multiTenant: boolean,
  nextUrl: string | null
): Promise<string> {
  return multiTenant ? getGoogleOAuthUrlSS(nextUrl) : "";
}

async function logoutStandardSS(headers: Headers): Promise<Response> {
  return fetch(buildUrl("/auth/logout"), { method: "POST", headers });
}

export async function logoutSS(headers: Headers): Promise<Response | null> {
  return logoutStandardSS(headers);
}

export async function authErrorRedirect(
  request: NextRequest,
  response: Response,
  redirectStatus?: number
): Promise<NextResponse> {
  const errorUrl = new URL("/auth/error", getDomain(request));
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string" && detail) {
      errorUrl.searchParams.set("error", detail);
    }
  } catch {
    // response may not be JSON
  }
  return NextResponse.redirect(errorUrl, redirectStatus);
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
