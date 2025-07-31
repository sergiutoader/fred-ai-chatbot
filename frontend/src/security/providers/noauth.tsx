export class NoAuthService {
  CallLogin(callback: Function) {
    console.log("NoAuth: Logging in as admin");
    callback();
  }

  CallLogout() {
    console.log("NoAuth: Clearing session");
  }

  GetToken() {
    return null;
  }

  GetUserId() {
    return "admin";
  }

  GetUserName() {
    return "admin";
  }

  GetUserFullName() {
    return "Administrator";
  }

  GetUserMail() {
    return "admin@example.com";
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