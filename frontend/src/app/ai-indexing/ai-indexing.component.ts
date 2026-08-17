import { Component, signal, OnInit } from "@angular/core";
import { AiService } from "../ai.service";
import { AppService } from "../app.service";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";

@Component({
  selector: "app-ai-indexing",
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: "./ai-indexing.component.html",
  styleUrls: ["./ai-indexing.component.css"],
})
export class AiIndexingComponent implements OnInit {
  loading = signal(false);
  error = signal<string | null>(null);
  success = signal<string | null>(null);
  selectedTaskIds = signal<number[]>([]);
  allTasks = signal<any[]>([]);
  tasksLoading = signal(true);
  indexMode = signal<"all" | "selected">("all");

  constructor(
    private aiService: AiService,
    private appService: AppService,
  ) {}

  ngOnInit(): void {
    this.loadTasks();
  }

  loadTasks(): void {
    this.appService.getTasks().subscribe({
      next: (response) => {
        this.tasksLoading.set(false);
        if (response.success) {
          this.allTasks.set(response.data);
        }
      },
      error: () => {
        this.tasksLoading.set(false);
      },
    });
  }

  toggleTask(taskId: number): void {
    this.selectedTaskIds.update((ids) => {
      if (ids.includes(taskId)) {
        return ids.filter((id) => id !== taskId);
      } else {
        return [...ids, taskId];
      }
    });
  }

  selectAll(): void {
    this.selectedTaskIds.set(this.allTasks().map((t) => t.id));
  }

  clearAll(): void {
    this.selectedTaskIds.set([]);
  }

  indexDocuments(): void {
    if (this.loading()) return;

    this.loading.set(true);
    this.error.set(null);
    this.success.set(null);

    const taskIds =
      this.indexMode() === "selected" ? this.selectedTaskIds() : undefined;

    this.aiService.indexDocuments(taskIds).subscribe({
      next: (response) => {
        this.loading.set(false);
        if (response.success) {
          const count = response.data?.indexed_count || 0;
          this.success.set(`Successfully indexed ${count} documents!`);
          this.selectedTaskIds.set([]);
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(this.getErrorMessage(err));
      },
    });
  }

  private getErrorMessage(err: any): string {
    const backendError =
      err?.error?.detail ||
      err?.error?.message ||
      err?.error?.errors?.detail ||
      err?.message;

    if (backendError) {
      return backendError;
    }

    if (err?.status === 401) {
      return "Please sign in again to index documents.";
    }

    if (err?.status === 403) {
      return "Only admins can index documents.";
    }

    return "Indexing failed";
  }

  get displayedTasks() {
    return this.allTasks().slice(0, 10);
  }
}
