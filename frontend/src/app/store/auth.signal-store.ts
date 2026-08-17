import { Injectable, computed, signal } from "@angular/core";
import { Router } from "@angular/router";
import { AppService } from "../app.service";

export interface AuthUser {
  id: number;
  email: string;
  name: string;
  roles: { id: number; name: string }[];
}

@Injectable({
  providedIn: "root",
})
export class AuthStore {
  readonly user = signal<AuthUser | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  readonly isAdmin = computed(
    () =>
      this.user()?.roles?.some(
        (role) => role.name?.toLowerCase() === "admin",
      ) ?? false,
  );

  readonly isEmployee = computed(
    () =>
      this.user()?.roles?.some(
        (role) => role.name?.toLowerCase() === "employee",
      ) ?? false,
  );

  readonly isAuthenticated = computed(() => !!this.user());

  initializeFromStorage(): void {
    const userJson = localStorage.getItem("auth_user");
    const user = userJson ? JSON.parse(userJson) : null;

    if (user) {
      this.user.set(user);
    }
  }

  getCurrentUser(appService: AppService): void {
    this.loading.set(true);
    this.error.set(null);

    appService.getCurrentUser().subscribe({
      next: (user: AuthUser) => {
        this.user.set(user);
        this.loading.set(false);
        this.error.set(null);
        localStorage.setItem("auth_user", JSON.stringify(user));
      },
      error: (error: any) => {
        this.loading.set(false);
        this.error.set(error.message || "Failed to get user");
      },
    });
  }

  logout(appService: AppService, router: Router): void {
    this.loading.set(true);

    const finalizeLogout = (): void => {
      this.user.set(null);
      this.loading.set(false);
      this.error.set(null);
      appService.clearAuthToken();
      localStorage.removeItem("user_loaded");
      localStorage.removeItem("auth_user");
      localStorage.removeItem("auth_token");
      router.navigate(["/login"]);
    };

    appService.logout().subscribe({
      next: () => finalizeLogout(),
      error: () => finalizeLogout(),
    });
  }

  setError(error: string | null): void {
    this.error.set(error);
  }

  clearError(): void {
    this.error.set(null);
  }
}
