import { Component, OnInit, signal } from "@angular/core";
import { CommonModule } from "@angular/common";
import { AiService } from "../ai.service";

interface AgentStatus {
  agent_id: string;
  role: string;
  name: string;
  status: string;
}

@Component({
  selector: "app-agents",
  standalone: true,
  imports: [CommonModule],
  templateUrl: "./agents.component.html",
  styleUrls: ["./agents.component.css"],
})
export class AgentsComponent implements OnInit {
  system = signal<any>(null);
  agents = signal<AgentStatus[]>([]);
  loading = signal(false);
  error = signal<string | null>(null);

  constructor(private aiService: AiService) {}

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.error.set(null);
    this.aiService.getAgentSystemStatus().subscribe({
      next: (res) => {
        this.system.set(res.data || null);
        this.aiService.listAgents().subscribe({
          next: (agents) => {
            this.agents.set(agents || []);
            this.loading.set(false);
          },
          error: (err) => {
            this.error.set("Failed to list agents");
            this.loading.set(false);
            console.error(err);
          },
        });
      },
      error: (err) => {
        this.error.set("Agent system unavailable");
        this.loading.set(false);
        console.error(err);
      },
    });
  }

  execute(agentId: string): void {
    this.aiService.executeAgent(agentId, "list_tasks").subscribe({
      next: (res) => {
        alert(`Execute result: ${JSON.stringify(res)}`);
        this.refresh();
      },
      error: (err) => {
        alert(`Execute failed: ${err.message || err}`);
      },
    });
  }
}
