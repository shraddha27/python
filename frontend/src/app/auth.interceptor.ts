import { Injectable } from "@angular/core";
import {
  HttpRequest,
  HttpHandler,
  HttpEvent,
  HttpInterceptor,
} from "@angular/common/http";
import { Observable } from "rxjs";

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  intercept(
    request: HttpRequest<unknown>,
    next: HttpHandler,
  ): Observable<HttpEvent<unknown>> {
    const token = localStorage.getItem("auth_token");
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    return next.handle(request.clone({ withCredentials: true, setHeaders: headers }));
  }
}
