import { createFeatureSelector, createSelector } from "@ngrx/store";
import { AuthState } from "./auth.models";

export const selectAuthState = createFeatureSelector<AuthState>("auth");

export const selectUser = createSelector(
  selectAuthState,
  (state: AuthState) => state.user,
);

export const selectToken = createSelector(
  selectAuthState,
  (state: AuthState) => state.token,
);

export const selectIsAuthenticated = createSelector(
  selectAuthState,
  (state: AuthState) => state.isAuthenticated,
);

export const selectAuthLoading = createSelector(
  selectAuthState,
  (state: AuthState) => state.loading,
);

export const selectAuthError = createSelector(
  selectAuthState,
  (state: AuthState) => state.error,
);

export const selectIsAdmin = createSelector(selectUser, (user) =>
  user ? user.roles.some((role) => role.name === "admin") : false,
);

export const selectIsEmployee = createSelector(selectUser, (user) =>
  user ? user.roles.some((role) => role.name === "employee") : false,
);
