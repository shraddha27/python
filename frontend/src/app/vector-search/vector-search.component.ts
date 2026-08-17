import { Component, signal } from "@angular/core";
import { AiService, SearchResult } from "../ai.service";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";

@Component({
  selector: "app-vector-search",
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: "./vector-search.component.html",
  styleUrls: ["./vector-search.component.css"],
})
export class VectorSearchComponent {
  searchQuery = signal("");
  results = signal<SearchResult[]>([]);
  loading = signal(false);
  error = signal<string | null>(null);
  limit = signal(5);

  constructor(private aiService: AiService) {}

  search(): void {
    const query = this.searchQuery().trim();
    if (!query || this.loading()) return;

    this.loading.set(true);
    this.error.set(null);

    this.aiService.search(query, this.limit()).subscribe({
      next: (response) => {
        this.loading.set(false);
        if (response.success) {
          this.results.set(response.data);
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(err.error?.errors?.detail || "Search failed");
      },
    });
  }

  handleKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter") {
      this.search();
    }
  }

  getSimilarityColor(score: number): string {
    if (score >= 0.8) return "#4caf50";
    if (score >= 0.6) return "#ff9800";
    return "#f44336";
  }
}
