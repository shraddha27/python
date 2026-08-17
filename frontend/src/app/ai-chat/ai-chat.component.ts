import { Component, OnInit, signal, computed } from "@angular/core";
import { AiService, ChatResponse, SearchResult } from "../ai.service";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";

interface Message {
  type: "user" | "assistant";
  content: string;
  context?: SearchResult[];
  toolCalls?: any[];
  timestamp: Date;
}

@Component({
  selector: "app-ai-chat",
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: "./ai-chat.component.html",
  styleUrls: ["./ai-chat.component.css"],
})
export class AiChatComponent implements OnInit {
  messages = signal<Message[]>([]);
  currentMessage = signal("");
  loading = signal(false);
  error = signal<string | null>(null);
  useContext = signal(true);
  useTools = signal(true);

  // AI health status
  aiReady = signal(false);
  ollama = signal(false);

  constructor(private aiService: AiService) {}

  ngOnInit(): void {
    this.checkAiHealth();
    // Add welcome message
    this.messages.set([
      {
        type: "assistant",
        content:
          "Hi! I'm your AI assistant. I can help you search tasks, create new ones, and answer questions about your work. What would you like to do?",
        timestamp: new Date(),
      },
    ]);
  }

  checkAiHealth(): void {
    this.aiService.checkHealth().subscribe({
      next: (response) => {
        if (response.success && response.data) {
          this.ollama.set(response.data.ollama);
          this.aiReady.set(response.data.status === "ready");
        }
      },
      error: () => {
        this.aiReady.set(false);
        this.ollama.set(false);
      },
    });
  }

  sendMessage(): void {
    const message = this.currentMessage().trim();
    if (!message || this.loading()) return;

    // Add user message
    this.messages.update((msgs) => [
      ...msgs,
      {
        type: "user",
        content: message,
        timestamp: new Date(),
      },
    ]);

    this.currentMessage.set("");
    this.loading.set(true);
    this.error.set(null);

    this.aiService.chat(message, this.useContext(), this.useTools()).subscribe({
      next: (response) => {
        this.loading.set(false);
        if (response.success && response.data) {
          const data = response.data;
          this.messages.update((msgs) => [
            ...msgs,
            {
              type: "assistant",
              content: data.response,
              context: data.context || undefined,
              toolCalls: data.tool_calls || undefined,
              timestamp: new Date(),
            },
          ]);
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(err.error?.errors?.detail || "Failed to get response");
        console.error("Chat error:", err);
      },
    });
  }

  handleKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  getSimilarityColor(score: number): string {
    if (score >= 0.8) return "#4caf50";
    if (score >= 0.6) return "#ff9800";
    return "#f44336";
  }
}
