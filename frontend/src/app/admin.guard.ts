import { Injectable } from "@angular/core";
import { CanActivate, Router } from "@angular/router";
import { Store } from "@ngrx/store";
import { selectIsAdmin } from "../store/auth/auth.selectors";
import { Observable } from "rxjs";
import { map, take } from "rxjs/operators";

@Injectable({
  providedIn: "root",
})
export class AdminGuard implements CanActivate {
  constructor(
    private store: Store,
    private router: Router,
  ) {}

  canActivate(): Observable<boolean> {
    return this.store.select(selectIsAdmin).pipe(
      take(1),
      map((isAdmin) => {
        if (!isAdmin) {
          this.router.navigate(["/tasks"]);
          return false;
        }
        return true;
      }),
    );
  }
}
