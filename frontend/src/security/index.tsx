import { store } from "../common/store";
import { securityApiSlice } from "../slices/securityApiSlice";
import { KeycloakAuthService } from "./providers/keycloak";
import { NoAuthService } from "./providers/noauth";
import type { SecurityConfig } from "../slices/securityApiSlice";

export async function getAuthService() {
  const result = await store.dispatch(
    securityApiSlice.endpoints.getSecurityConfig.initiate()
  );

  const config = result.data as SecurityConfig | undefined;

  if (!config || !config.enabled) {
    return new NoAuthService();
  }

  switch (config.idp) {
    case "keycloak":
      return new KeycloakAuthService(config);
    default:
      console.warn(`Unknown IDP: ${config.idp}`);
      return new NoAuthService();
  }
}
