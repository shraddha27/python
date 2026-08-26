import { HttpClient, HttpErrorResponse } from "@angular/common/http";
import { Injectable } from "@angular/core";
import { Observable, throwError } from "rxjs";
import { catchError, map, timeout } from "rxjs/operators";
import { environment } from "../environments/environment";
import { Task } from "./task.model";
import { ApiError, ApiResponse, TaskStats } from "./error.model";

@Injectable({
  providedIn: "root",
})
export class AppService {
  private apiUrl = `${environment.apiUrl}/tasks/`;
  private authUrl = `${environment.apiUrl}/auth/`;

  constructor(private http: HttpClient) {}

  // ============================================================================
  // AUTH METHODS
  // ============================================================================

  googleLogin(idToken: string): Observable<any> {
    return this.http
      .post<any>(`${this.authUrl}google/`, { id_token: idToken })
      .pipe(timeout(30000))
      .pipe(catchError(this.handleError));
  }

  logout(): Observable<any> {
    return this.http
      .post<any>(`${this.authUrl}logout/`, {})
      .pipe(catchError(this.handleError));
  }

  getCurrentUser(): Observable<any> {
    return this.http
      .get<any>(`${this.authUrl}me/`)
      .pipe(catchError(this.handleError));
  }

  getAuthToken(): string | null {
    return localStorage.getItem("auth_token");
  }

  setAuthToken(token: string): void {
    localStorage.setItem("auth_token", token);
  }

  clearAuthToken(): void {
    localStorage.removeItem("auth_token");
  }

  // ============================================================================
  // TASK METHODS
  // ============================================================================

  getTasks(
    search?: string,
    completed?: boolean,
    skip: number = 0,
    limit: number = 10,
  ): Observable<ApiResponse<Task[]>> {
    let url = this.apiUrl;
    const params: string[] = [`skip=${skip}`, `limit=${limit}`];

    if (search) {
      params.push(`search=${encodeURIComponent(search)}`);
    }

    if (completed !== undefined) {
      params.push(`completed=${completed}`);
    }

    url += `?${params.join("&")}`;

    return this.http
      .get<ApiResponse<Task[]>>(url)
      .pipe(catchError(this.handleError));
  }

  addTask(task: Partial<Task>): Observable<Task> {
    return this.http.post<ApiResponse<Task>>(this.apiUrl, task).pipe(
      map((response) => response.data as Task),
      catchError(this.handleError),
    );
  }

  updateTask(task: Task): Observable<Task> {
    return this.http
      .put<ApiResponse<Task>>(`${this.apiUrl}${task.id}/`, task)
      .pipe(
        map((response) => response.data as Task),
        catchError(this.handleError),
      );
  }

  deleteTask(taskId: number): Observable<void> {
    return this.http
      .delete<void>(`${this.apiUrl}${taskId}/`)
      .pipe(catchError(this.handleError));
  }

  getTaskStats(): Observable<TaskStats> {
    return this.http.get<ApiResponse<TaskStats>>(`${this.apiUrl}stats/`).pipe(
      map((response) => response.data as TaskStats),
      catchError(this.handleError),
    );
  }

  bulkUpdateTasks(
    taskIds: number[],
    completed: boolean,
  ): Observable<ApiResponse<Task[]>> {
    return this.http
      .post<ApiResponse<Task[]>>(`${this.apiUrl}bulk_update/`, {
        task_ids: taskIds,
        completed: completed,
      })
      .pipe(catchError(this.handleError));
  }

  private handleError(error: HttpErrorResponse): Observable<never> {
    let apiError: ApiError = { message: "An error occurred" };

    if (error.error instanceof ErrorEvent) {
      // Client-side error
      apiError = {
        message: error.error.message || "Client error occurred",
        detail: error.error.message,
      };
    } else {
      // Server-side error
      if (error.error && typeof error.error === "object") {
        if (error.error.errors) {
          apiError.errors = error.error.errors;
        }
        if (error.error.detail) {
          apiError.detail = error.error.detail;
        }
        if (error.error.message) {
          apiError.message = error.error.message;
        }
      } else {
        apiError = {
          message: error.message || `Server error: ${error.status}`,
          detail: error.statusText,
        };
      }
    }

    return throwError(() => apiError);
  }
}
