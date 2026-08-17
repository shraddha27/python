import { Injectable } from "@angular/core";
import { HttpClient } from "@angular/common/http";
import { Observable, of } from "rxjs";
import { catchError, tap, map } from "rxjs/operators";

@Injectable({
  providedIn: "root",
})
export class CsrfService {
  private csrfToken: string | null = null;

  constructor(private http: HttpClient) {
    this.initializeToken();
  }

  /**
   * Initialize CSRF token from cookie or fetch from server
   */
  private initializeToken(): void {
    const token = this.getCookie("csrftoken");
    if (token) {
      this.csrfToken = token;
    }
  }

  /**
   * Get CSRF token - from cache, cookie, or fetch from server
   */
  getToken(): Observable<string | null> {
    // Try to get from cache first
    if (this.csrfToken) {
      return of(this.csrfToken);
    }

    // Try to get from cookie
    const cookieToken = this.getCookie("csrftoken");
    if (cookieToken) {
      this.csrfToken = cookieToken;
      return of(cookieToken);
    }

    // Fetch from server - this will trigger Django to set the CSRF cookie
    return this.http.get<{ csrfToken: string }>("/api/csrf-token/").pipe(
      map((response) => response.csrfToken || null),
      tap((token) => {
        // Store from response or from cookie after request
        this.csrfToken = token || this.getCookie("csrftoken");
        console.log(
          `✓ CSRF token loaded: ${this.csrfToken ? "present" : "missing"}`,
        );
      }),
      catchError((error) => {
        console.warn("Failed to fetch CSRF token:", error);
        // Fallback: try to get from cookie even if request fails
        const token = this.getCookie("csrftoken");
        this.csrfToken = token;
        return of(token);
      }),
    );
  }

  /**
   * Get cached CSRF token synchronously (for init only)
   */
  getTokenSync(): string | null {
    if (this.csrfToken) {
      return this.csrfToken;
    }
    return this.getCookie("csrftoken");
  }

  /**
   * Set CSRF token (used by interceptor when received from server)
   */
  setToken(token: string): void {
    this.csrfToken = token;
  }

  /**
   * Extract CSRF token from cookie
   */
  private getCookie(name: string): string | null {
    if (typeof document === "undefined") {
      return null;
    }

    const cookieString = document.cookie || "";
    if (!cookieString) {
      return null;
    }

    const cookies = cookieString.split(";");
    for (let cookie of cookies) {
      cookie = cookie.trim();
      if (cookie.startsWith(name + "=")) {
        const value = cookie.substring(name.length + 1);
        try {
          return decodeURIComponent(value);
        } catch (e) {
          console.warn("Failed to decode CSRF cookie:", e);
          return value;
        }
      }
    }
    return null;
  }
}
