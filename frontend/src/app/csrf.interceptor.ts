import { Injectable } from "@angular/core";
import {
  HttpRequest,
  HttpHandler,
  HttpEvent,
  HttpInterceptor,
  HttpResponse,
} from "@angular/common/http";
import { Observable, of } from "rxjs";
import { tap, switchMap } from "rxjs/operators";
import { CsrfService } from "./csrf.service";

@Injectable()
export class CsrfInterceptor implements HttpInterceptor {
  constructor(private csrfService: CsrfService) {}

  intercept(
    request: HttpRequest<any>,
    next: HttpHandler,
  ): Observable<HttpEvent<any>> {
    // Only add CSRF token for non-safe requests
    if (this.isSafeMethod(request.method)) {
      return next.handle(request);
    }

    // For non-safe requests, ensure we have a CSRF token
    return this.csrfService.getToken().pipe(
      switchMap((csrfToken) => {
        // Clone request and add CSRF token
        if (csrfToken) {
          request = request.clone({
            setHeaders: {
              "X-CSRFToken": csrfToken,
            },
          });
          console.log(`✓ Added CSRF token to ${request.method} request`);
        } else {
          console.warn(
            `⚠ No CSRF token available for ${request.method} request`,
          );
        }

        // Handle response
        return next.handle(request).pipe(
          tap((event: HttpEvent<any>) => {
            if (event instanceof HttpResponse) {
              const token = event.headers.get("X-CSRFToken");
              if (token) {
                this.csrfService.setToken(token);
              }
            }
          }),
        );
      }),
    );
  }

  private isSafeMethod(method: string): boolean {
    return ["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
  }
}
