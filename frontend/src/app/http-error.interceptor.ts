import { Injectable } from "@angular/core";
import {
  HttpRequest,
  HttpHandler,
  HttpEvent,
  HttpInterceptor,
  HttpErrorResponse,
} from "@angular/common/http";
import { Observable, throwError } from "rxjs";
import { catchError } from "rxjs/operators";
import { Router } from "@angular/router";
import { AppService } from "./app.service";

@Injectable()
export class HttpErrorInterceptor implements HttpInterceptor {
  constructor(
    private router: Router,
    private appService: AppService,
  ) {}

  intercept(
    request: HttpRequest<any>,
    next: HttpHandler,
  ): Observable<HttpEvent<any>> {
    return next.handle(request).pipe(
      catchError((error: HttpErrorResponse) => {
        console.error("HTTP Error:", {
          status: error.status,
          statusText: error.statusText,
          message: error.message,
          url: error.url,
        });

        // Handle 401 Unauthorized - but NOT for auth endpoints
        if (
          error.status === 401 &&
          !error.url?.includes("/auth/me/") &&
          !error.url?.includes("/auth/google/") &&
          !error.url?.includes("/auth/logout/")
        ) {
          this.appService.clearAuthToken();
          localStorage.removeItem("auth_user");
          localStorage.removeItem("user_loaded");
          this.router.navigate(["/login"]);
        }

        return throwError(() => error);
      }),
    );
  }
}
