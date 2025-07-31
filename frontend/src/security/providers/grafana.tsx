// Copyright Thales 2025
//
// Licensed under the Apache License, Version 2.0

let config: any = null;

const CallLogin = (onAuthenticatedCallback: Function) => {
  console.log("Grafana login called");
  const token = localStorage.getItem("grafana_token");
  if (token) {
    onAuthenticatedCallback();
  } else {
    // In a real setup, this should redirect or trigger an auth flow via Grafana proxy
    console.warn("No token found. Auth proxy should inject it.");
    onAuthenticatedCallback();
  }
};

const CallLogout = () => {
  console.log("Logging out from Grafana (noop, handled by proxy)");
  localStorage.removeItem("grafana_token");
  window.location.href = "/";
};

const GetUserName = (): string => {
  return localStorage.getItem("grafana_username") || "admin";
};

const GetUserId = (): string => {
  return localStorage.getItem("grafana_uid") || "admin";
};

const GetUserFullName = (): string => {
  return localStorage.getItem("grafana_name") || "Administrator";
};

const GetUserMail = (): string => {
  return localStorage.getItem("grafana_email") || "admin@example.com";
};

const GetRealmRoles = (): string[] => {
  const raw = localStorage.getItem("grafana_roles");
  return raw ? JSON.parse(raw) : ["admin"];
};

const GetUserRoles = (): string[] => {
  return GetRealmRoles();
};

const GetToken = (): string | null => {
  return localStorage.getItem("grafana_token");
};

const GetTokenParsed = (): any => {
  const raw = localStorage.getItem("grafana_token_parsed");
  return raw ? JSON.parse(raw) : null;
};

export const AuthService = {
  CallLogin,
  CallLogout,
  GetUserName,
  GetUserId,
  GetUserFullName,
  GetUserMail,
  GetToken,
  GetRealmRoles,
  GetUserRoles,
  GetTokenParsed,
};
