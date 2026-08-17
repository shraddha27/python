import { Component, OnInit, inject } from "@angular/core";
import { AppService } from "../app.service";
import { Task } from "../task.model";
import { ApiError, TaskStats } from "../error.model";
import { AuthStore } from "../store/auth.signal-store";

@Component({
  selector: "app-task-list",
  templateUrl: "./task-list.component.html",
  styleUrls: ["./task-list.component.css"],
})
export class TaskListComponent implements OnInit {
  tasks: Task[] = [];
  newTitle = "";
  newDescription = "";
  loading = false;
  generalError = "";
  fieldErrors: { [key: string]: string } = {};
  stats: TaskStats | null = null;
  showStats = false;

  // Pagination
  currentPage = 0;
  pageSize = 10;
  totalTasks = 0;
  hasMore = false;

  private service = inject(AppService);
  authStore = inject(AuthStore);

  ngOnInit(): void {
    this.loadTasks();
    this.loadStats();
  }

  loadTasks(): void {
    this.loading = true;
    this.generalError = "";
    const skip = this.currentPage * this.pageSize;
    this.service.getTasks(undefined, undefined, skip, this.pageSize).subscribe({
      next: (response) => {
        this.tasks = response.data || [];
        if (response.pagination) {
          this.totalTasks = response.pagination.total;
          this.hasMore = response.pagination.has_more;
        }
        this.loading = false;
      },
      error: (error: ApiError) => {
        this.generalError = this.getErrorMessage(error);
        this.loading = false;
      },
    });
  }

  loadStats(): void {
    this.service.getTaskStats().subscribe({
      next: (stats: TaskStats) => {
        this.stats = stats;
      },
      error: (error: ApiError) => {
        console.error("Failed to load stats:", error);
      },
    });
  }

  createTask(): void {
    this.generalError = "";
    this.fieldErrors = {};

    // Client-side validation
    if (!this.newTitle.trim()) {
      this.fieldErrors["title"] = "Title is required";
      return;
    }

    if (this.newTitle.trim().length < 3) {
      this.fieldErrors["title"] = "Title must be at least 3 characters long";
      return;
    }

    this.service
      .addTask({
        title: this.newTitle.trim(),
        description: this.newDescription.trim(),
      })
      .subscribe({
        next: () => {
          this.newTitle = "";
          this.newDescription = "";
          this.fieldErrors = {};
          this.loadTasks();
          this.loadStats();
        },
        error: (error: ApiError) => {
          this.handleFormError(error);
        },
      });
  }

  toggleCompletion(task: Task): void {
    // Only send id and completed fields (employees can only update status)
    const updated = { id: task.id, completed: !task.completed } as any;
    this.service.updateTask(updated).subscribe({
      next: () => {
        this.loadTasks();
        this.loadStats();
      },
      error: (error: ApiError) => {
        this.generalError = this.getErrorMessage(error);
      },
    });
  }

  deleteTask(taskId: number): void {
    if (confirm("Are you sure you want to delete this task?")) {
      this.service.deleteTask(taskId).subscribe({
        next: () => {
          this.loadTasks();
          this.loadStats();
        },
        error: (error: ApiError) => {
          this.generalError = this.getErrorMessage(error);
        },
      });
    }
  }

  private handleFormError(error: ApiError): void {
    if (error.errors && typeof error.errors === "object") {
      this.fieldErrors = this.flattenErrors(
        error.errors as { [key: string]: string[] | string },
      );
    } else {
      this.generalError = this.getErrorMessage(error);
    }
  }

  private flattenErrors(errors: { [key: string]: string[] | string }): {
    [key: string]: string;
  } {
    const flattened: { [key: string]: string } = {};
    for (const key in errors) {
      const value = errors[key];
      if (Array.isArray(value)) {
        flattened[key] = value[0] || "Invalid field";
      } else {
        flattened[key] = value;
      }
    }
    return flattened;
  }

  nextPage(): void {
    if (this.hasMore) {
      this.currentPage++;
      this.loadTasks();
    }
  }

  previousPage(): void {
    if (this.currentPage > 0) {
      this.currentPage--;
      this.loadTasks();
    }
  }

  get pageCount(): number {
    return Math.ceil(this.totalTasks / this.pageSize);
  }

  get startIndex(): number {
    return this.currentPage * this.pageSize + 1;
  }

  get endIndex(): number {
    return Math.min((this.currentPage + 1) * this.pageSize, this.totalTasks);
  }

  clearError(): void {
    this.generalError = "";
  }

  toggleStats(): void {
    this.showStats = !this.showStats;
  }

  private getErrorMessage(error: ApiError): string {
    if (error.detail) {
      return error.detail;
    }
    if (error.message) {
      return error.message;
    }
    return "An error occurred. Please try again.";
  }
}
