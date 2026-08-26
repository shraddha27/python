import {
  Component,
  OnInit,
  AfterViewInit,
  ViewChild,
  ElementRef,
  inject,
  signal,
} from "@angular/core";
import { Router } from "@angular/router";
import { AuthStore } from "../store/auth.signal-store";
import { AppService } from "../app.service";
import { environment } from "../../environments/environment";

declare var google: any;

@Component({
  selector: "app-login",
  templateUrl: "./login.component.html",
  styleUrls: ["./login.component.css"],
})
export class LoginComponent implements OnInit, AfterViewInit {
  @ViewChild("googleButtonContainer") googleButtonContainer!: ElementRef;

  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  private readonly authStore = inject(AuthStore);
  private readonly router = inject(Router);
  private readonly appService = inject(AppService);

  ngOnInit(): void {
    // Check if already logged in
    if (localStorage.getItem("auth_user")) {
      this.router.navigate(["/tasks"]);
      return;
    }

    // Initialize Google Sign-In
    this.initializeGoogleSignIn();
  }

  ngAfterViewInit(): void {
    this.renderGoogleButtonWhenReady();
  }

  private initializeGoogleSignIn(): void {
    this.renderGoogleButtonWhenReady();
  }

  private renderGoogleButtonWhenReady(attempt = 0): void {
    const googleAccounts = (globalThis as any).google?.accounts;

    if (googleAccounts && this.googleButtonContainer) {
      this.renderGoogleButton();
      return;
    }

    if (attempt < 20) {
      globalThis.setTimeout(
        () => this.renderGoogleButtonWhenReady(attempt + 1),
        100,
      );
    }
  }

  private renderGoogleButton(): void {
    const googleAccounts = (globalThis as any).google?.accounts;

    if (!googleAccounts || !this.googleButtonContainer) {
      return;
    }

    // Initialize Google Sign-In button
    googleAccounts.id.initialize({
      client_id: environment.googleClientId,
      callback: (response: any) => this.handleGoogleLogin(response),
    });

    googleAccounts.id.renderButton(this.googleButtonContainer.nativeElement, {
      theme: "outline",
      size: "large",
      text: "signin_with",
    });
  }

  private handleGoogleLogin(response: any): void {
    const idToken = response.credential;
    this.loading.set(true);
    this.error.set(null);
    this.appService.googleLogin(idToken).subscribe({
      next: (loginResponse: any) => {
        this.authStore.user.set(loginResponse.user);
        if (loginResponse.access_token) {
          this.appService.setAuthToken(loginResponse.access_token);
        }
        localStorage.setItem("auth_user", JSON.stringify(loginResponse.user));
        localStorage.setItem("user_loaded", "true");
        this.loading.set(false);
        this.router.navigate(["/tasks"]);
      },
      error: (error: any) => {
        console.error("✗ Google Login Error:", error);
        this.loading.set(false);
        this.error.set(error.detail || error.message || "Login failed");
      },
    });
  }
}
