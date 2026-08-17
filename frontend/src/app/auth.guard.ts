import { Injectable } from "@angular/core";
import { ActivatedRouteSnapshot, CanActivate, Router, RouterStateSnapshot, UrlTree } from "@angular/router";
import { AuthStore } from "./store/auth.signal-store";

@Injectable({
  providedIn: "root",
})
export class AuthGuard implements CanActivate {
  constructor(
    private readonly authStore: AuthStore,
    private readonly router: Router,
  ) {}

  canActivate(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): boolean | UrlTree {
    if (!this.authStore.user()) {
      this.authStore.initializeFromStorage();
    }

    const isAuthenticated = this.authStore.isAuthenticated();
    if (!isAuthenticated) {
      return this.router.createUrlTree(["/login"]);
    }

    if (this.authStore.isEmployee() && !this.authStore.isAdmin()) {
      if (!state.url.startsWith("/tasks") && state.url !== "" && state.url !== "/") {
        return this.router.createUrlTree(["/tasks"]);
      }
    }

    return true;
  }
}
