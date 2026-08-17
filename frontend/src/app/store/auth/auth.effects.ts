import { Injectable } from "@angular/core";
import { Actions, createEffect, ofType } from "@ngrx/effects";
import { catchError, map, switchMap, tap, mergeMap } from "rxjs/operators";
import { of } from "rxjs";
import * as AuthActions from "./auth.actions";
import { AppService } from "../../app.service";
import { Router } from "@angular/router";

@Injectable()
export class AuthEffects {
  constructor(
    private actions$: Actions,
    private appService: AppService,
    private router: Router,
  ) {}

  googleLogin$ = createEffect(() =>
    this.actions$.pipe(
      ofType(AuthActions.googleLogin),
      switchMap(({ idToken }) =>
        this.appService.googleLogin(idToken).pipe(
          map((response: any) =>
            AuthActions.googleLoginSuccess({
              user: response.user,
              token: response.access_token,
            }),
          ),
          catchError((error) =>
            of(
              AuthActions.googleLoginFailure({
                error: error.message || "Login failed",
              }),
            ),
          ),
        ),
      ),
    ),
  );

  googleLoginSuccess$ = createEffect(
    () =>
      this.actions$.pipe(
        ofType(AuthActions.googleLoginSuccess),
        tap(({ token }) => {
          localStorage.setItem("auth_token", token);
        }),
      ),
    { dispatch: false },
  );

  logout$ = createEffect(() =>
    this.actions$.pipe(
      ofType(AuthActions.logout),
      switchMap(() =>
        this.appService.logout().pipe(
          map(() => AuthActions.logoutSuccess()),
          catchError(() => of(AuthActions.logoutSuccess())),
        ),
      ),
    ),
  );

  logoutSuccess$ = createEffect(
    () =>
      this.actions$.pipe(
        ofType(AuthActions.logoutSuccess),
        tap(() => {
          localStorage.removeItem("auth_token");
          this.router.navigate(["/login"]);
        }),
      ),
    { dispatch: false },
  );

  getCurrentUser$ = createEffect(() =>
    this.actions$.pipe(
      ofType(AuthActions.getCurrentUser),
      switchMap(() =>
        this.appService.getCurrentUser().pipe(
          map((user) => AuthActions.getCurrentUserSuccess({ user })),
          catchError((error) =>
            of(
              AuthActions.getCurrentUserFailure({
                error: error.message || "Failed to get user",
              }),
            ),
          ),
        ),
      ),
    ),
  );
}
