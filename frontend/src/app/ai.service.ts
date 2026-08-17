import { Injectable } from "@angular/core";
import { HttpClient, HttpParams } from "@angular/common/http";
import { Observable } from "rxjs";
import { map, mergeMap } from 'rxjs/operators';

export interface ChatRequest {
  message: string;
  use_context: boolean;
  use_tools: boolean;
}

export interface SearchResult {
  id: number;
  title: string;
  content: string;
  similarity_score: number;
}

export interface ChatResponse {
  message: string;
  context: SearchResult[] | null;
  tool_calls: any[] | null;
  response: string;
}

export interface IndexRequest {
  task_ids?: number[];
}

export interface ToolDefinition {
  name: string;
  description: string;
  parameters: any;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
}

// LangGraph Workflow Interfaces
export interface WorkflowExecuteRequest {
  input: string;
  context?: { [key: string]: any };
}

export interface WorkflowResult {
  task_id: string;
  status: string;
  result: string | any;
  response?: string;
  workflow_stages?: number;
  agent_messages: any[];
  routing_decision?: {
    mode: string;
    route?: string;
    stage?: string;
    confidence?: string;
  };
  error?: string;
  agents_used?: string[];
}

// MCP Interfaces
export interface MCPTool {
  name: string;
  description: string;
  tool_type: string;
  parameters: any[];
  metadata: { [key: string]: any };
}

export interface MCPToolCallRequest {
  tool_name: string;
  arguments?: { [key: string]: any };
}

export interface MCPToolCallResult {
  tool_name: string;
  success: boolean;
  result: any;
  error?: string;
}

export interface MCPResource {
  name: string;
  type: string;
  content: any;
  metadata: { [key: string]: any };
}

export interface MCPPrompt {
  name: string;
  template: string;
  description: string;
  variables: string[];
}

export interface MCPProposal {
  agent?: string;
  tool: string;
  args?: { [key: string]: any };
  intent?: string;
  confirm?: boolean;
  user_context?: string;
}

export interface MCPStatus {
  status: string;
  tools_count: number;
  resources_count: number;
  prompts_count: number;
}

@Injectable({
  providedIn: "root",
})
export class AiService {
  private readonly API_BASE = "/api/ai";
  private readonly AGENTS_BASE = "/api/agents";
  private readonly WORKFLOW_BASE = "/api/workflow";
  private readonly MCP_BASE = "/api/mcp";

  constructor(private http: HttpClient) {}

  // Check if Ollama and embeddings are available
  checkHealth(): Observable<ApiResponse<any>> {
    return this.http.get<ApiResponse<any>>(`${this.API_BASE}/health/`);
  }

  // Vector search across indexed documents
  search(
    query: string,
    limit: number = 5,
  ): Observable<ApiResponse<SearchResult[]>> {
    const body = { query, limit };
    return this.http.post<ApiResponse<SearchResult[]>>(
      `${this.API_BASE}/search/`,
      body,
    );
  }

  // Index tasks as documents with embeddings
  indexDocuments(taskIds?: number[]): Observable<ApiResponse<any>> {
    const body: IndexRequest = taskIds ? { task_ids: taskIds } : {};
    return this.http.post<ApiResponse<any>>(`${this.API_BASE}/index/`, body);
  }

  // Chat with AI agent (with context retrieval and tool calling)
  chat(
    message: string,
    useContext: boolean = true,
    useTools: boolean = true,
  ): Observable<ApiResponse<ChatResponse>> {
    const body: ChatRequest = {
      message,
      use_context: useContext,
      use_tools: useTools,
    };
    return this.http.post<ApiResponse<ChatResponse>>(
      `${this.API_BASE}/chat/`,
      body,
    );
  }

  // Get list of available tools
  getTools(): Observable<ApiResponse<ToolDefinition[]>> {
    return this.http.get<ApiResponse<ToolDefinition[]>>(
      `${this.API_BASE}/tools/`,
    );
  }

  // ----------------------
  // Multi-Agent System APIs
  // ----------------------

  // Get system status
  getAgentSystemStatus(): Observable<ApiResponse<any>> {
    return this.http.get<ApiResponse<any>>(`${this.AGENTS_BASE}/system/status`);
  }

  // List all agents
  listAgents(): Observable<any> {
    return this.http.get<any>(`${this.AGENTS_BASE}/agents`);
  }

  // Execute a task on an agent
  executeAgent(agentId: string, operation: string, params: any = {}): Observable<any> {
    const body = {
      agent_id: agentId,
      operation,
      params: params,
    };
    return this.http.post<any>(`${this.AGENTS_BASE}/execute`, body);
  }

  // Get recent message history
  getAgentMessageHistory(limit: number = 100): Observable<any> {
    return this.http.get<any>(`${this.AGENTS_BASE}/message-history?limit=${limit}`);
  }

  // ----------------------
  // LangGraph Workflow APIs
  // ----------------------

  // Execute a workflow for complex multi-agent tasks
  executeWorkflow(
    input: string,
    context?: { [key: string]: any }
  ): Observable<ApiResponse<WorkflowResult>> {
    const body: WorkflowExecuteRequest = { input, context };
    return this.http.post<ApiResponse<WorkflowResult>>(
      `${this.WORKFLOW_BASE}/execute`,
      body
    );
  }

  uploadWorkflowFile(file: File, prompt: string): Observable<ApiResponse<any>> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    formData.append('prompt', prompt);
    return this.http.post<ApiResponse<any>>(
      `${this.WORKFLOW_BASE}/upload`,
      formData
    );
  }

  // Get workflow status
  getWorkflowStatus(): Observable<ApiResponse<any>> {
    return this.http.get<ApiResponse<any>>(`${this.WORKFLOW_BASE}/status`);
  }

  // ----------------------
  // MCP (Model Context Protocol) APIs
  // ----------------------

  // List all available MCP tools
  getMCPTools(): Observable<ApiResponse<{ tools: MCPTool[]; count: number }>> {
    return this.http.get<ApiResponse<{ tools: MCPTool[]; count: number }>>(
      `${this.MCP_BASE}/tools`
    );
  }

  // Get a specific MCP tool definition
  getMCPTool(toolName: string): Observable<MCPTool> {
    return this.http.get<MCPTool>(`${this.MCP_BASE}/tools/${toolName}`);
  }

  // Call an MCP tool
  callMCPTool(
    toolName: string,
    args: { [key: string]: any }
  ): Observable<ApiResponse<MCPToolCallResult>> {
    const body: MCPToolCallRequest = { tool_name: toolName, arguments: args };
    return this.http.post<ApiResponse<MCPToolCallResult>>(
      `${this.MCP_BASE}/tools/call`,
      body
    );
  }

  // Call an MCP tool and request a natural-language assistant response
  callMCPToolNatural(
    toolName: string,
    args: { [key: string]: any },
    userMessage?: string,
  ): Observable<any> {
    const body: any = { tool_name: toolName, arguments: args };
    if (userMessage) {
      body.user_message = userMessage;
    }
    return this.http.post<any>(`${this.MCP_BASE}/tools/call_natural`, body);
  }

  // List all available MCP resources
  getMCPResources(): Observable<ApiResponse<{ resources: MCPResource[]; count: number }>> {
    return this.http.get<ApiResponse<{ resources: MCPResource[]; count: number }>>(
      `${this.MCP_BASE}/resources`
    );
  }

  // Get a specific MCP resource
  getMCPResource(resourceName: string): Observable<MCPResource> {
    return this.http.get<MCPResource>(`${this.MCP_BASE}/resources/${resourceName}`);
  }

  // List all available MCP prompts
  getMCPPrompts(): Observable<ApiResponse<{ prompts: MCPPrompt[]; count: number }>> {
    return this.http.get<ApiResponse<{ prompts: MCPPrompt[]; count: number }>>(
      `${this.MCP_BASE}/prompts`
    );
  }

  // Get a specific MCP prompt
  getMCPPrompt(promptName: string): Observable<MCPPrompt> {
    return this.http.get<MCPPrompt>(`${this.MCP_BASE}/prompts/${promptName}`);
  }

  // Render a prompt template with variables
  renderMCPPrompt(
    promptName: string,
    variables: { [key: string]: string }
  ): Observable<{ prompt: string; rendered: string }> {
    const body = { variables };
    return this.http.post<{ prompt: string; rendered: string }>(
      `${this.MCP_BASE}/prompts/${promptName}/render`,
      body
    );
  }

  // Get MCP server status
  getMCPStatus(): Observable<ApiResponse<MCPStatus>> {
    return this.http.get<ApiResponse<MCPStatus>>(`${this.MCP_BASE}/status`);
  }

  // Propose an MCP tool call (LLM-driven proposal)
  proposeMCPTool(proposal: MCPProposal): Observable<ApiResponse<MCPToolCallResult>> {
    return this.http.post<ApiResponse<MCPToolCallResult>>(`${this.MCP_BASE}/tools/propose`, proposal);
  }

  private extractJsonFromText(text: string): string | null {
    if (!text) {
      return null;
    }

    const trimmed = text.trim();
    const start = trimmed.indexOf('{');
    if (start === -1) {
      return null;
    }

    let depth = 0;
    let inString = false;
    let escape = false;
    for (let i = start; i < trimmed.length; i++) {
      const char = trimmed[i];
      if (escape) {
        escape = false;
        continue;
      }
      if (char === '\\') {
        escape = true;
        continue;
      }
      if (char === '"') {
        inString = !inString;
        continue;
      }
      if (inString) {
        continue;
      }
      if (char === '{') {
        depth += 1;
      } else if (char === '}') {
        depth -= 1;
        if (depth === 0) {
          return trimmed.slice(start, i + 1);
        }
      }
    }
    return null;
  }

  // Ask the LLM to generate a Proposal JSON from a prompt, then submit it to the MCP propose endpoint
  proposeFromPrompt(message: string): Observable<any> {
    return this.chat(message, false, false).pipe(
      map(response => response.data.response),
      mergeMap((text: any) => {
        let proposal: any = null;
        if (typeof text === 'string') {
          const trimmed = text.trim();
          try {
            proposal = JSON.parse(trimmed);
          } catch {
            const jsonText = this.extractJsonFromText(trimmed);
            if (!jsonText) {
              throw { error: 'LLM did not return valid JSON proposal', detail: trimmed };
            }
            try {
              proposal = JSON.parse(jsonText);
            } catch (e) {
              throw { error: 'LLM returned malformed JSON proposal', detail: e };
            }
          }
        } else {
          proposal = text;
        }
        const proposalWithContext: MCPProposal = {
          ...proposal,
          args: { ...(proposal?.args || {}) },
          user_context: message,
        };
        // First execute the proposal via the propose endpoint
        return this.proposeMCPTool(proposalWithContext).pipe(
          mergeMap((res: any) => {
            const nested = res?.data ?? res;
            const toolName = nested?.result?.tool || (proposalWithContext?.tool) || (nested?.tool_name);
            const toolArgs = nested?.result?.args || proposalWithContext?.args || nested?.result || {};
            // Call the natural-language helper to get assistant text for display
            return this.callMCPToolNatural(toolName, toolArgs, message).pipe(
              map((naturalRes: any) => {
                return {
                  raw: res,
                  natural: naturalRes,
                };
              })
            );
          })
        );
      }),
    );
  }
}
