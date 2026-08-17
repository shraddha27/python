import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AiService, WorkflowResult, MCPTool, MCPStatus } from '../ai.service';

@Component({
  selector: 'app-langraph-workflow',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './langraph-workflow.component.html',
  styleUrls: ['./langraph-workflow.component.css']
})
export class LangGraphWorkflowComponent implements OnInit {
  workflowInput: string = '';
  workflowResult: WorkflowResult | null = null;
  mcpStatus: MCPStatus | null = null;
  mcpTools: MCPTool[] = [];
  chatMessages: Array<{ role: 'user' | 'assistant'; content: string; meta?: string }> = [];
  selectedFile: File | null = null;
  selectedFileName = '';

  loading = false;
  error: string | null = null;
  successMessage: string | null = null;
  generatedProposalResult: any = null;

  constructor(private aiService: AiService) { }

  ngOnInit(): void {
    this.loadMCPStatus();
    this.loadMCPTools();
    this.resetChat();
  }

  loadMCPStatus(): void {
    this.aiService.getMCPStatus().subscribe({
      next: (response) => {
        this.mcpStatus = response.data;
      },
      error: (err) => {
        console.error('Failed to load MCP status:', err);
      }
    });
  }

  loadMCPTools(): void {
    this.aiService.getMCPTools().subscribe({
      next: (response) => {
        this.mcpTools = response.data.tools;
      },
      error: (err) => {
        console.error('Failed to load MCP tools:', err);
      }
    });
  }

  executeWorkflow(): void {
    const userInput = this.workflowInput.trim();
    if (!userInput && !this.selectedFile) {
      this.error = 'Please enter a workflow input or choose a file';
      return;
    }

    this.loading = true;
    this.error = null;
    this.successMessage = null;
    this.workflowResult = null;
    this.generatedProposalResult = null;
    const displayText = this.selectedFile
      ? `${userInput ? `${userInput}\n` : ''}File: ${this.selectedFile.name}`
      : userInput;
    this.chatMessages.push({ role: 'user', content: displayText });
    this.workflowInput = '';

    if (this.selectedFile) {
      this.aiService.uploadWorkflowFile(this.selectedFile, userInput || 'Create tasks from this document').subscribe({
        next: (response) => {
          this.loading = false;
          const responseData: any = response?.data ?? {};
          this.workflowResult = {
            task_id: responseData.task_id || 'workflow_upload',
            status: responseData.status || 'success',
            result: responseData.response || 'File processed successfully',
            workflow_stages: 1,
            agent_messages: [{ agent_id: 'ocr_upload', message_type: 'workflow_agent', content: null }],
            error: responseData.error || undefined,
            agents_used: ['ocr_upload'],
          };
          this.chatMessages.push({
            role: 'assistant',
            content: this.getFriendlyWorkflowText(responseData.response || 'File processed successfully'),
            meta: `File: ${this.selectedFile?.name || 'unknown'} • Tasks: ${responseData.task_count || 0}`,
          });
          this.successMessage = 'File processed and tasks created';
          this.selectedFile = null;
          this.selectedFileName = '';
        },
        error: (err) => {
          this.loading = false;
          this.error = err.error?.detail || err.error?.data?.error || (err?.error || err?.message) || 'Failed to process file';
          this.chatMessages.push({
            role: 'assistant',
            content: this.error || 'The workflow could not process the file.',
          });
          console.error('Workflow upload error:', err);
        }
      });
      return;
    }

    this.aiService.executeWorkflow(userInput).subscribe({
      next: (response) => {
        this.loading = false;

        const responseData: any = response?.data ?? {};
        // Prefer the explicit `response` field added to the workflow API. If the
        // backend returned a `natural` wrapper (from call_natural) prefer the
        // assistant-synthesized `assistant_response`. Fall back to legacy shapes.
        let workflowResponseText: string = '';
        if (responseData && typeof responseData.response === 'string' && responseData.response.trim()) {
          workflowResponseText = responseData.response;
        } else if (responseData && responseData.natural && typeof responseData.natural.assistant_response === 'string' && responseData.natural.assistant_response.trim()) {
          workflowResponseText = responseData.natural.assistant_response;
        } else if (responseData && typeof responseData.result === 'string') {
          workflowResponseText = responseData.result;
        } else if (responseData && responseData.result && typeof responseData.result.response === 'string') {
          workflowResponseText = responseData.result.response;
        } else if (responseData && responseData.result && typeof responseData.result.assistant_response === 'string') {
          workflowResponseText = responseData.result.assistant_response;
        } else if (responseData && responseData.natural && typeof responseData.natural === 'string') {
          workflowResponseText = responseData.natural;
        } else if (responseData.result) {
          workflowResponseText = JSON.stringify(responseData.result, null, 2);
        }

        const agentsUsed: string[] = Array.isArray(responseData.agents_used)
          ? responseData.agents_used
          : [];

        this.workflowResult = {
          task_id: responseData.task_id || 'workflow_execution',
          status: responseData.status || 'success',
          result: workflowResponseText,
          workflow_stages: responseData.workflow_stages,
          routing_decision: responseData.routing_decision,
          agent_messages: agentsUsed.map((agent: string) => ({ agent_id: agent, message_type: 'workflow_agent', content: null })),
          error: responseData.error || undefined,
          agents_used: agentsUsed,
        };

        const metaParts: string[] = [];
        if (responseData.workflow_stages !== undefined) {
          metaParts.push(`Stages: ${responseData.workflow_stages}`);
        }
        if (responseData.agents_used && responseData.agents_used.length > 0) {
          metaParts.push(`Agents: ${responseData.agents_used.join(', ')}`);
        } else if (responseData.routing_decision?.mode) {
          metaParts.push(`Route: ${responseData.routing_decision.mode}`);
        }
        if (responseData.status === 'awaiting_confirmation') {
          metaParts.push('Status: awaiting confirmation');
        } else if (responseData.status) {
          metaParts.push(`Status: ${responseData.status}`);
        }

        this.chatMessages.push({
          role: 'assistant',
          content: this.getFriendlyWorkflowText(workflowResponseText),
          meta: metaParts.join(' • ') || undefined,
        });
        this.successMessage = 'Workflow executed successfully';
      },
      error: (err) => {
        this.loading = false;
        this.error = err.error?.detail || err.error?.data?.error || (err?.error || err?.message) || 'Failed to execute workflow';
        this.chatMessages.push({
          role: 'assistant',
          content: this.error || 'The workflow could not be completed.',
        });
        console.error('Workflow execution error:', err);
      }
    });
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] || null;
    if (file) {
      this.selectedFile = file;
      this.selectedFileName = file.name;
      this.error = null;
    }
  }

  onEnterSend(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.executeWorkflow();
    }
  }

  // Legacy direct proposal method is removed from main UI.

  clearForm(): void {
    this.workflowInput = '';
    this.workflowResult = null;
    this.generatedProposalResult = null;
    this.error = null;
    this.successMessage = null;
    this.resetChat();
  }

  private resetChat(): void {
    this.chatMessages = [
      {
        role: 'assistant',
        content: 'Hello! I can help run workflows, create tasks, or complete and reopen them. What would you like to do?',
      }
    ];
  }

  private getFriendlyWorkflowText(responseText: string): string {
    if (!responseText) {
      return 'Workflow completed.';
    }

    const cleaned = responseText
      .replace(/^### Summary\s*/i, '')
      .replace(/^### Response\s*/i, '')
      .replace(/\n{3,}/g, '\n\n')
      .trim();

    return cleaned || 'Workflow completed.';
  }

  private normalizeProposalResponse(response: any): { raw: any; success: boolean; error?: string; resultPayload: any } {
    const raw = response?.data ?? response;

    if (raw && typeof raw === 'object' && 'success' in raw && 'result' in raw) {
      return {
        raw,
        success: raw.success === true,
        error: raw.error,
        resultPayload: raw.result,
      };
    }

    if (raw && typeof raw === 'object' && 'data' in raw) {
      const nested = raw.data;
      if (nested && typeof nested === 'object' && 'success' in nested && 'result' in nested) {
        return {
          raw: nested,
          success: nested.success === true,
          error: nested.error,
          resultPayload: nested.result,
        };
      }
    }

    return {
      raw,
      success: true,
      resultPayload: raw,
    };
  }

  formatJson(obj: any): string {
    return JSON.stringify(obj, null, 2);
  }

  getWorkflowResponse(result: any): string {
    if (!result) {
      return '';
    }

    if (typeof result === 'string') {
      return result;
    }

    if (typeof result === 'object' && typeof result.response === 'string') {
      return result.response;
    }

    return this.formatJson(result);
  }

  getDisplayWorkflowResponse(text: string): string {
    if (!text) {
      return '';
    }

    const normalized = text.replace(/\r\n/g, '\n').trim();
    const responseStart = normalized.toLowerCase().indexOf('### response');
    if (responseStart >= 0) {
      return normalized.slice(0, responseStart).trim();
    }

    return normalized;
  }

  formatWorkflowResponse(text: string): string {
    if (!text) {
      return '';
    }

    const normalized = text
      .replace(/\r\n/g, '\n')
      .replace(/^### Details\s*$/gm, '')
      .replace(/^Context:\s*.*$/gm, '')
      .replace(/^Results:\s*.*$/gm, '')
      .replace(/^[-•] Context:.*$/gm, '')
      .replace(/^[-•] Results:.*$/gm, '')
      .trim();
    const codeBlocks: string[] = [];
    const placeholder = (index: number) => `__CODE_BLOCK_${index}__`;

    const textWithCodePlaceholders = normalized.replace(/```(?:\w*)\n([\s\S]*?)```/g, (_, code) => {
      codeBlocks.push(code);
      return placeholder(codeBlocks.length - 1);
    });

    const escaped = this.escapeHtml(textWithCodePlaceholders);

    let html = escaped
      .replace(/^### (.+)$/gm, '<h4>$1</h4>')
      .replace(/^## (.+)$/gm, '<h3>$1</h3>')
      .replace(/^# (.+)$/gm, '<h2>$1</h2>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
      .replace(/^[-•] (.+)$/gm, '<div class="workflow-bullet">• $1</div>')
      .replace(/^(\d+)\. (.+)$/gm, '<div class="workflow-number">$1. $2</div>');

    html = html
      .split('\n\n')
      .map((block) => block.trim())
      .filter(Boolean)
      .join('</p><p>');

    if (html) {
      html = `<p>${html}</p>`;
    }

    html = html.replace(/\n/g, '<br/>');

    html = html.replace(/__CODE_BLOCK_(\d+)__/g, (_, index) => {
      const code = codeBlocks[Number(index)];
      return `<pre>${this.escapeHtml(code)}</pre>`;
    });

    return html;
  }

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}
