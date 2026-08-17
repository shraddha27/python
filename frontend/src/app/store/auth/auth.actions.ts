import { createAction, props } from "@ngrx/store";
import { AuthUser } from "./auth.models";

// Initialize Auth from Storage
export const initializeAuthFromStorage = createAction(
  "[Auth] Initialize From Storage",
  props<{ token: string | null }>(),
);

// Google Login
export const googleLogin = createAction(
  "[Auth] Google Login",
  props<{ idToken: string }>(),
);

export const googleLoginSuccess = createAction(
  "[Auth] Google Login Success",
  props<{ user: AuthUser; token: string }>(),
);

export const googleLoginFailure = createAction(
  "[Auth] Google Login Failure",
  props<{ error: string }>(),
);

// Logout
export const logout = createAction("[Auth] Logout");

export const logoutSuccess = createAction("[Auth] Logout Success");

// Get Current User
export const getCurrentUser = createAction("[Auth] Get Current User");

export const getCurrentUserSuccess = createAction(
  "[Auth] Get Current User Success",
  props<{ user: AuthUser }>(),
);

export const getCurrentUserFailure = createAction(
  "[Auth] Get Current User Failure",
  props<{ error: string }>(),
);
