export interface ApiError {
  errors?: { [key: string]: string[] | string };
  detail?: string;
  message?: string;
  success?: boolean;
}

export interface PaginationMeta {
  skip: number;
  limit: number;
  total: number;
  has_more: boolean;
}

export interface ApiResponse<T> {
  data?: T;
  success: boolean;
  errors?: ApiError;
  updated_count?: number;
  message?: string;
  pagination?: PaginationMeta;
}

export interface TaskStats {
  total: number;
  completed: number;
  pending: number;
  completion_percentage: number;
}
