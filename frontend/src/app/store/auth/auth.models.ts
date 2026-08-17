export interface AuthUser {
  id: number;
  email: string;
  name: string;
  roles: { id: number; name: string }[];
}

export interface AuthState {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  error: string | null;
  isAuthenticated: boolean;
}
