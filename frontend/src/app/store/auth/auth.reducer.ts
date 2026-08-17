import { createReducer, on, Action } from "@ngrx/store";
import * as AuthActions from "./auth.actions";
import { AuthState } from "./auth.models";

export const initialAuthState: AuthState = {
  user: null,
  token: null,
  loading: false,
  error: null,
  isAuthenticated: false,
};

const authReducer = createReducer(
  initialAuthState,
  // Initialize from Storage
  on(AuthActions.initializeAuthFromStorage, (state, { token }) => ({
    ...state,
    token: token,
    isAuthenticated: token !== null,
  })),
  // Google Login
  on(AuthActions.googleLogin, (state) => ({
    ...state,
    loading: true,
    error: null,
  })),
  on(AuthActions.googleLoginSuccess, (state, { user, token }) => ({
    ...state,
    user,
    token,
    loading: false,
    isAuthenticated: true,
    error: null,
  })),
  on(AuthActions.googleLoginFailure, (state, { error }) => ({
    ...state,
    loading: false,
    error,
    isAuthenticated: false,
  })),
  // Logout
  on(AuthActions.logout, (state) => ({
    ...state,
    loading: true,
  })),
  on(AuthActions.logoutSuccess, (state) => ({
    ...state,
    user: null,
    token: null,
    loading: false,
    isAuthenticated: false,
  })),
  // Get Current User
  on(AuthActions.getCurrentUser, (state) => ({
    ...state,
    loading: true,
  })),
  on(AuthActions.getCurrentUserSuccess, (state, { user }) => ({
    ...state,
    user,
    loading: false,
    isAuthenticated: true,
  })),
  on(AuthActions.getCurrentUserFailure, (state, { error }) => ({
    ...state,
    loading: false,
    error,
    // Keep isAuthenticated as is - don't logout on failure
  })),
);

export function reducer(state: AuthState | undefined, action: Action) {
  return authReducer(state, action);
}
