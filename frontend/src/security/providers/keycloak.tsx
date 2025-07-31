export class KeycloakAuthService {
  private config: any;

  constructor(config: any) {
    this.config = config;
    console.log("KeycloakAuthService initialized with config:", config);
  }

  async CallLogin(callback: Function) {
    // Implement your login logic here
    console.log("CallLogin not implemented for KeycloakAuthService");
    callback();
  }

  async CallLogout() {
    console.log("CallLogout not implemented for KeycloakAuthService");
  }

  GetToken() {
    return null;
  }

  GetUserId() {
    return "mock-keycloak-user";
  }

  GetUserName() {
    return "mock-user";
  }

  GetUserFullName() {
    return "Mock Keycloak User";
  }

  GetUserMail() {
    return "mock@user.com";
  }

  GetRealmRoles() {
    return ["admin"];
  }

  GetUserRoles() {
    return ["admin"];
  }

  GetTokenParsed() {
    return null;
  }
}