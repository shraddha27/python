# End-to-End Flow of the Task Management Application

## 1. Architecture Overview

This application is a full-stack system built from three main parts:

- **Frontend**: Angular application in `frontend/`
- **Django backend**: Main task CRUD, auth, and business logic in `backend_django/`
- **FastAPI backend**: AI features, vector search, multi-agent orchestration, and MCP in `backend_fastapi/`
- **Database**: PostgreSQL stores tasks, users, roles, and vector documents

The application uses the Angular frontend as the user interface. Normal task operations are handled by the Django backend, while AI and retrieval features are handled by the FastAPI backend. Both backends share the same database schema and user model.

---

## 2. High-Level User Flows

### 2.1 Login Flow

1. User opens the app and lands on the login page.
   - Frontend file: `frontend/src/app/login/login.component.ts`
2. The page renders the Google Sign-In button with the configured `googleClientId`.
3. When the user signs in, Google returns an `id_token`.
4. The frontend sends that token to Django:
   - `frontend/src/app/app.service.ts` -> `googleLogin(idToken)`
   - POST to `backend_django/api/auth/google/`
5. Django verifies the token in `backend_django/tasks/auth_views.py` using `google.auth`.
6. If valid, Django creates or retrieves the user and stores them in a shared `users` table.
7. Django issues a JWT access token and sets it as a cookie named `auth_token`.
8. The frontend stores user info in `localStorage` and navigates to `/tasks`.

### 2.2 Task CRUD Flow

1. User visits the task list page.
   - Frontend file: `frontend/src/app/task-list/task-list.component.ts`
2. The component calls `AppService.getTasks()`.
   - `frontend/src/app/app.service.ts`
3. The request reaches Django endpoint `backend_django/api/tasks/`.
   - Routing: `backend_django/tasks/urls.py`
   - View: `backend_django/tasks/views.py` -> `TaskViewSet.list`
4. Django fetches tasks using `TaskService.get_tasks()` in `backend_django/tasks/services.py`.
5. The response includes pagination metadata.
6. For task creation, the frontend calls `AppService.addTask()`.
   - POST to `backend_django/api/tasks/`
   - Django checks authentication and admin role in `TaskViewSet.create`
   - The serializer `backend_django/tasks/serializers.py` validates title/description
   - `TaskService.create_task()` enforces duplicate title and field limits
7. For updates, the frontend calls `AppService.updateTask()`.
   - PUT to `backend_django/api/tasks/{id}/`
   - `TaskViewSet.update` enforces role-based access:
     - Admin users can update all fields
     - Employee users can only update `completed`
8. For deletion, the frontend calls `AppService.deleteTask()`.
   - DELETE to `backend_django/api/tasks/{id}/`
   - Only admins can delete tasks in `TaskViewSet.destroy`
9. Task statistics are loaded by `AppService.getTaskStats()`.
   - Django returns totals, completed, pending, and completion percentage via `TaskService.get_task_stats()`.
10. Bulk updates are supported by `TaskViewSet.bulk_update`.

### 2.3 AI Feature Flow

The AI flow uses `frontend/src/app/ai.service.ts` and FastAPI endpoints.

#### 2.3.1 Embeddings: sentence-transformer and fallback behavior

1. The app generates embeddings using `backend_fastapi/embeddings.py`.
   - The primary implementation uses `sentence-transformers` with the configured model name `all-MiniLM-L6-v2`.
   - Environment variables:
     - `EMBEDDING_MODEL_NAME`: model identifier (default `all-MiniLM-L6-v2`)
     - `LOCAL_EMBEDDING_MODEL_PATH`: local path for a cached model
     - `MODELS_PATH`: cache root for model search
     - `USE_SENTENCE_TRANSFORMERS`: enables local model loading
     - `USE_REMOTE_EMBEDDING_API`: enables remote Hugging Face inference fallback
2. On startup, `_load_sentence_transformer()` tries these paths:
   - `LOCAL_EMBEDDING_MODEL_PATH`
   - `MODELS_PATH/sentence-transformers/{model_name}`
   - `MODELS_PATH/{model_name}`
   - cached Hugging Face folders like `models--{normalized_slug}`
3. If a cached config exists, it loads `SentenceTransformer(str(path))`.
   - If loading fails, it logs a warning and continues.
4. `generate_embedding(text)` calls `_sentence_transformer_embedding(text)`.
   - If the model is available, it returns a normalized 384-d vector.
   - If the model is unavailable, it falls back to deterministic hashing via `_fallback_embedding(text)`.
5. `generate_embeddings_batch(texts)` similarly uses the local model if available, otherwise optionally calls the Hugging Face remote API with `HF_EMBEDDING_API_TOKEN`.
   - Remote API requests are sent to `https://api-inference.huggingface.co/models/{EMBEDDING_MODEL_NAME}`.
   - If remote inference also fails, the fallback embedding is used.
6. The produced embeddings populate search and indexing paths:
   - vector search: `backend_fastapi/main.py` -> `vector_search(db, query_embedding)`
   - task indexing: `backend_fastapi/main.py` -> `index_documents`
   - tool search in `backend_fastapi/rag_tools.py` via `search_tasks` and `vector_search`.

#### 2.3.2 Mistral LLM integration

1. The app uses `backend_fastapi/ollama_client.py` to call Mistral.
   - `MISTRAL_BASE_URL`: base URL for Mistral API (default `https://api.mistral.ai/v1`)
   - `MISTRAL_MODEL`: model name (default `mistral-tiny`)
   - `MISTRAL_API_KEY`: API key required for remote calls
2. `chat_with_tools(user_message, context, tool_results)` builds a chat request:
   - System prompt instructs the model to behave as TaskFlow AI.
   - User payload includes the raw question plus optional context and tool results.
3. If `MISTRAL_API_KEY` is missing, the code uses `_local_model_response(...)` fallback.
   - Fallback is a deterministic response generator based on intent keywords.
   - It can provide guidance for task creation, completion, search, and stats without calling an LLM.
4. When Mistral is enabled, the app sends a POST to `/chat/completions` with:
   - `model`
   - `messages`: system + user
   - `temperature`: 0.7
5. The response is parsed from `choices[0].message.content`.
   - If the request fails, the app catches the exception, logs it, and falls back to `_local_model_response(...)`.
6. `check_ollama_health()` simply returns whether a Mistral API key is configured, which drives the `/api/ai/health/` status.

#### 2.3.3 Vector Search

1. User enters a query in the vector search page.
   - Frontend file: `frontend/src/app/vector-search/vector-search.component.ts`
2. The component calls `AiService.search(query, limit)`.
3. Backend route: `backend_fastapi/main.py` -> `@app.post("/api/ai/search/")`
4. FastAPI fetches `DocumentModel` rows from `documents`.
5. It generates an embedding for the query using `backend_fastapi/embeddings.py`.
6. It ranks documents by similarity using `_rank_document_search_result`
   and returns the closest results.
7. The frontend displays the semantic search results.

#### 2.3.4 Document Indexing

1. User chooses tasks to index in the AI indexing page.
   - Frontend file: `frontend/src/app/ai-indexing/ai-indexing.component.ts`
2. The component calls `AiService.indexDocuments(taskIds)`.
3. Backend route: `backend_fastapi/main.py` -> `@app.post("/api/ai/index/")`
4. FastAPI verifies the requesting user and admin role.
5. It queries tasks, generates embeddings for each task, and writes them to `documents`.
6. Each document stores `task_id`, `title`, `content`, and `embedding`.
7. This creates or refreshes the vector search corpus used by AI features.

#### 2.3.3 AI Chat Flow

1. User types a question in the AI chat page.
   - Frontend file: `frontend/src/app/ai-chat/ai-chat.component.ts`
2. The component calls `AiService.chat(message, useContext, useTools)`.
3. Backend route: `backend_fastapi/main.py` -> `@app.post("/api/ai/chat/")`
4. FastAPI authenticates the user with `get_current_user_dep(request)`.
   - The request is validated using the JWT token in the `auth_token` cookie.
   - The user record and roles are loaded from the shared database.
5. The backend creates the initial response object:
   - `message`: original user text
   - `context`: null until context documents are found
   - `tool_calls`: null until tools execute
   - `response`: empty string until the LLM result arrives

##### Detailed AI chat internals

6. If `use_context` is enabled, the backend retrieves relevant documents:
   - `generate_embedding(payload.message)` is executed in a thread pool to avoid blocking the FastAPI event loop.
   - `vector_search(db, query_embedding, limit=3)` queries `backend_fastapi/main.py` using `pgvector`.
   - Returned documents are filtered to `similarity_score >= 0.2`.
   - The selected documents become `context_docs` and are formatted into a short context summary.
   - The frontend receives `context` as an array of `SearchResult` objects.
7. If `use_tools` is enabled, the backend attempts to map the user request to a tool call:
   - `payload.message` is normalized and analyzed.
   - `_is_deadline_question(payload.message)` detects deadline-related questions.
   - `_resolve_task_id_for_action(...)` attempts to identify a specific task by explicit ID or inferred query.
   - `_tool_from_semantic_intent(...)` evaluates semantic intent labels such as `list_tasks`, `search_tasks`, `get_task_stats`, `complete_task`, `reopen_task`, `delete_task`, and `create_task`.
     - This function is the primary tool router when the request has a higher-level intent label.
     - It maps semantic intents to concrete tool names and argument schemas.
     - For task-specific operations that require a `task_id`, it uses `_resolve_task_id_for_action()` and may inspect `candidate_docs` from context.
     - For `create_task`, it extracts `title` and `description` from the natural-language request.
   - `_infer_tool_from_keywords(...)` applies keyword heuristics when semantic intent does not yield a tool.
     - It checks phrase patterns such as `show tasks`, `list tasks`, `sort`, `priority`, `related to`, `completed tasks`, `pending tasks`, `details`, `delete`, and so on.
     - It returns the same tool names as `_tool_from_semantic_intent` but based on explicit wording instead of an intent label.
     - It also falls back to `search_tasks` when a task ID is not found for a details-style request.
   - `looks_like_explicit_create_task_request(message)` detects requests that clearly include both title and description.
8. When a tool is selected, the backend executes it via `_tool_call(db, tool_name, tool_args, tool_calls)`:
   - This appends a `tool_calls` entry with the tool name, arguments, and result.
   - Tool execution uses the same database session as the chat request.
   - Tools may call:
     - `search_tasks` for semantic task search
     - `get_task_details` for task summaries and deadline detection
     - `create_task` to insert a new task
     - `complete_task` / `reopen_task` / `delete_task` to update task status
     - `list_tasks` or `sort_tasks_by_time` for structured task listings
     - `get_task_stats` for task counts and completion summaries
   - Tool definitions come from `backend_fastapi/rag_tools.py` and are mirrored as MCP-style tool metadata.
9. The backend composes the final prompt for the language model:
   - It includes the original user question.
   - It includes relevant context from indexed documents when available.
   - It includes tool results if any were executed.
   - Example composition logic lives in `backend_fastapi/ollama_client.py` in `chat_with_tools()`.
10. The LLM is called with `chat_with_tools(user_message, context=context_text, tool_results=tool_results_text)`:
   - If `MISTRAL_API_KEY` is configured, it calls the Mistral chat completion API.
   - Otherwise, it falls back to a local response generator.
   - The system prompt is crafted to make the model behave as a task-management assistant.
11. The resulting LLM answer is returned as `response` in the API payload.
12. The final API response is structured as:
   - `success`: boolean
   - `data`: object with `message`, `context`, `tool_calls`, and `response`
   - `message`: user query text
   - `context`: retrieved documents (if enabled)
   - `tool_calls`: executed tool trace and results
   - `response`: generated assistant text

##### What this means for the UI

- `use_context` lets the chat system ground answers in indexed task content.
- `use_tools` lets the chat system call backend operations safely before answering.
- If a tool provides a task list or stats, the LLM uses those results as the primary source of truth.
- If no tool is relevant, the LLM still answers based on general task knowledge and available context.

### 2.4 Multi-Agent System and Workflow

This application supports a coordinated multi-agent workflow that routes user requests to specialized agents and returns a single final response.

#### 2.4.1 Entry points and REST routes

- `POST /api/workflow/execute` in `backend_fastapi/main.py` executes a LangGraph workflow.
- `GET /api/workflow/status` returns workflow/MCP readiness.
- `GET /api/agents/system/status` returns overall agent system status.
- `GET /api/agents/agents` lists registered agents.
- `POST /api/agents/execute` runs a specific agent task directly.
- `GET /api/agents/message-history` returns recent agent messages.
- `GET /api/mcp/tools`, `/api/mcp/resources`, `/api/mcp/prompts`, and `/api/mcp/status` expose MCP assets.

Frontend components:

- `frontend/src/app/agents/agents.component.ts` displays agent health, agent list, and direct agent execution.
- `frontend/src/app/langraph-workflow/langraph-workflow.component.ts` submits complex workflow requests to `/api/workflow/execute`.

#### 2.4.2 Initialization flow

At FastAPI startup (`backend_fastapi/main.py`):

1. The app initializes a standard `AgentManager` instance for the agent system.
2. It registers these agents:
   - `TaskAgentSpec()`
   - `ChatAgentSpec()`
   - `RAGAgentSpec()`
   - `AnalysisAgentSpec()`
   - `CoordinatorAgentSpec()`
3. It initializes the MCP server (`MCPServer`).
4. It registers standard tools with MCP:
   - `create_task`
   - `search_tasks`
   - `complete_task`
   - `reopen_task`
   - `delete_task`
   - `vector_search`
5. It registers prompt templates such as `task_creation` and `search_query`.

This makes the multi-agent system available to both direct agent routes and the LangGraph workflow.

#### 2.4.3 Workflow execution flow

A workflow request follows these steps:

1. HTTP client calls `POST /api/workflow/execute`.
   - The payload is validated by `WorkflowExecuteRequest`.
   - The current user is authenticated using `get_current_user_dep(request)`.
   - User context is added to the workflow payload.
2. `LangGraphWorkflow.execute_workflow(...)` is invoked.
3. The workflow state machine begins at the `router` node.
4. The router inspects the user input and computes keyword counts for:
   - task intent
   - RAG/retrieval intent
   - analysis/introspection intent
5. The router decides a path among these execution modes:
   - `task_rag_analysis` for combined task + retrieval + analysis requests
   - `task_rag` for task + retrieval requests
   - `task_analysis` for task + analysis requests
   - `task_only` for task-only requests
   - `rag_analysis` for retrieval + analysis requests
   - `rag_only` for retrieval-only requests
   - `analysis_only` for analysis-only requests
   - `chat_only` for plain conversational requests
6. The workflow transitions through nodes based on the chosen path:
   - `task_stage`
   - `rag_stage`
   - `analysis_stage`
   - `chat_final`
   - `finalize`

#### 2.4.4 Agent execution stages

During workflow execution, each stage may call one or more agents:

- `TaskAgent` handles task-related operations.
  - It can execute operations like `list_tasks`, `get_task`, `create_task`, `complete_task`, `reopen_task`, and `delete_task`.
  - It uses MCP tool calls to perform semantic search or direct task manipulation.
  - It normalizes combined user requests and can act on explicit task IDs or inferred task references.
- `RAGAgent` handles retrieval operations.
  - It executes semantic search via the `vector_search` MCP tool.
  - It returns `results` and `count`.
- `AnalysisAgent` handles analysis operations.
  - It executes `analyze_data` or `generate_report` with aggregated context and tool results.
  - It currently returns structured insight placeholders.
- `ChatAgent` handles the final response generation.
  - It calls `chat_with_tools(...)` with the accumulated `message`, `context`, and `tool_results`.
  - This produces the final natural-language assistant answer.

#### 2.4.5 Example workflow request

For a prompt like “Find tasks related to design, summarize them, and complete the highest-priority one”: 

1. The router detects task intent, retrieval intent, and analysis intent.
   - `LangGraphWorkflow._router_node()` normalizes the request and lowercases it.
   - It matches the text against keyword groups in `backend_fastapi/agents/langraph_workflow.py`:
     - task keywords like `find`, `task`, `tasks`, `complete`
     - RAG keywords like `search`, `related`, `design`, `context`
     - analysis keywords like `summarize`, `summary`, `priority`, `analyze`
   - It computes boolean flags:
     - `has_task` = explicit create request or task keyword count >= 1
     - `has_rag` = retrieval keyword count >= 1 or related content words
     - `has_analysis` = analysis keyword count >= 1 or summary/priority words
   - For this prompt, all three flags become true because it contains task-related language (`tasks`, `complete`), retrieval-related language (`find`, `related`, `design`), and analysis-related language (`summarize`, `priority`).
2. It routes to `task_rag_analysis`.
   - `wants_full_flow` becomes true when the input mixes task, RAG, and analysis intents.
   - The router assigns `state.current_agent = "task_rag_analysis"`.
   - LangGraph uses this to wire the next node to `task_stage` via `_route_stages()` and `workflow.add_conditional_edges(...)`.

#### Detailed `task_rag_analysis` data flow

2.1. Task stage entry
   - The workflow enters `task_stage` because `task_rag_analysis` maps to `task_stage` first.
   - Payload prepared by `LangGraphWorkflow._task_stage_node()`:
     ```json
     {
       "operation": "search_and_create",
       "user_input": "Find tasks related to design, summarize them, and complete the highest-priority one",
       "mcp_server": <MCPServer instance>
     }
     ```
   - `TaskAgent.execute(...)` receives that payload.

2.2. TaskAgent processing
   - Inside `TaskAgent._search_and_create_summary()` the agent:
     - checks for explicit completion/reopen/delete actions using `looks_like_task_status_update_request()`;
     - if there are action keywords together with search/list keywords, it preserves them as a combined request;
     - calls `search_tasks` through MCP using `ToolCallRequest(tool_name="search_tasks", arguments={"query": user_input, "limit": 10})`.
   - Search results are returned from the MCP tool and become `tasks` plus a `count`.
   - If the prompt includes a task-status action and a task ID can be inferred, the agent also executes the corresponding MCP tool (`complete_task`, `reopen_task`, or `delete_task`).
   - For this prompt, the agent is likely to perform a semantic search and assemble task matches while recognizing the explicit task completion intent.
   - The returned TaskAgent result shape looks like:
     ```json
     {
       "status": "success",
       "message": "Found X matching task(s)",
       "tasks_found": X,
       "tasks": [ ... ],
       "found_tasks": [ ... ]
     }
     ```
   - `state.stage_tool_results` is appended with a terse TaskAgent summary.

2.3. Task-to-RAG handoff
   - After `task_stage` completes, `_normalize_next_stage("task_rag_analysis")` returns `rag_analysis`.
   - The workflow advances to `rag_stage`.

2.4. RAG stage entry
   - `LangGraphWorkflow._rag_stage_node()` builds:
     ```json
     {
       "operation": "search",
       "query": "Find tasks related to design, summarize them, and complete the highest-priority one",
       "mcp_server": <MCPServer instance>
     }
     ```
   - `RAGAgent.execute(...)` receives this payload.

2.5. RAGAgent processing
   - `RAGAgent._search()` calls the MCP `vector_search` tool with:
     - `query` = user input
     - `limit` = 5
     - `threshold` = 0.7
   - The MCP tool computes an embedding, performs vector similarity search, and returns result docs.
   - The returned RAG result shape is:
     ```json
     {
       "status": "success",
       "results": [ ... ],
       "count": N
     }
     ```
   - `state.stage_context` is appended with the RAG results.

2.6. RAG-to-analysis handoff
   - `_rag_stage_transition()` sees `current_agent == "task_rag_analysis"` and routes to `analysis`.
   - The workflow enters `analysis_stage`.

2.7. Analysis stage entry
   - `LangGraphWorkflow._analysis_stage_node()` builds:
     ```json
     {
       "operation": "analyze_data",
       "message": "Find tasks related to design, summarize them, and complete the highest-priority one",
       "context": state.stage_context,
       "tool_results": state.stage_tool_results
     }
     ```
   - `AnalysisAgent.execute(...)` receives this payload.

2.8. AnalysisAgent processing
   - `AnalysisAgent._analyze_data()` currently returns a placeholder summary:
     ```json
     {"status": "success", "insights": []}
     ```
   - Its output is appended to `state.stage_tool_results`.

2.9. Analysis-to-chat handoff
   - `analysis_stage` always transitions to `chat_final`.
   - The workflow enters `chat_final`.

2.10. Chat stage entry
   - `LangGraphWorkflow._chat_final_node()` builds a final prompt with:
     - `User request` = original user input
     - `Context` = RAG results or task context
     - `Results` = accumulated `stage_tool_results`
     - `Workflow steps` = count of stage log entries
   - Payload sent to `ChatAgent.execute(...)` is:
     ```json
     {
       "operation": "send_message",
       "message": final_prompt,
       "context": state.stage_context,
       "tool_results": state.stage_tool_results
     }
     ```

2.11. ChatAgent processing
   - `ChatAgent._send_message()` calls `chat_with_tools(user_message, context, tool_results)`.
   - `chat_with_tools()` invokes Mistral (or the local fallback) and returns the assistant text.
   - Final response payload is:
     ```json
     {"status": "success", "response": "..."}
     ```

2.12. Final output
   - `LangGraphWorkflow._finalize_node()` marks the workflow completed.
   - The returned API payload includes the `workflow_log`, `result`, `status`, and `task_id`.

3. `TaskAgent` may execute a search for relevant tasks or task management actions.
4. `RAGAgent` performs vector search to retrieve document/context.
5. `AnalysisAgent` analyzes the retrieved tasks and generates summary insight.
6. `ChatAgent` composes the final answer, including task IDs, summary, and next steps.
7. The workflow API returns:
   - `task_id`
   - `status`
   - `error`
   - `result`
   - `workflow_log`

#### 2.4.6 Direct agent and MCP interaction

The system also supports direct interaction with agents and MCP tools:

- `POST /api/agents/execute` lets the frontend invoke one agent task directly.
- `GET /api/agents/message-history` helps debug how agents communicate.
- `POST /api/mcp/tools/call` lets external clients call MCP tools directly.
- `GET /api/mcp/status` verifies tool and prompt readiness.

#### 2.4.7 How the workflow is logged

The workflow returns a `workflow_log` containing:

- agent identifiers
- actions executed by each agent
- intermediate results from task, RAG, and analysis stages

This log is captured in `WorkflowState.workflow_log` and returned by `execute_workflow`.

---

#### 2.4.7 Detailed End-to-End Multi-Agent Flow (LangGraph + MCP)

This section walks a single user request through the full LangGraph orchestration and MCP-enabled multi-agent pipeline, showing exact code locations and runtime handoffs.

1. Client request
   - Frontend calls `POST /api/workflow/execute` with `input` and optional `context`.
   - File: [backend_fastapi/main.py](backend_fastapi/main.py#L2006)

2. Authentication and context enrichment
   - `get_current_user_dep(request)` validates JWT in `auth_token` cookie and attaches `user.id` and `user.email` to the workflow context.
   - File: [backend_fastapi/main.py](backend_fastapi/main.py#L684)

3. LangGraph kickoff
   - `langraph_workflow.execute_workflow(...)` is invoked with `user_input` and `task_context`.
   - File: [backend_fastapi/main.py](backend_fastapi/main.py#L2016)
   - Implementation: [backend_fastapi/agents/langraph_workflow.py](backend_fastapi/agents/langraph_workflow.py#L1)

4. Router node (intent decomposition)
   - The `router` node normalizes the input, counts keyword matches, and decides the execution path (`task_rag_analysis`, `rag_only`, etc.).
   - Key functions: `_is_explicit_create_task_request`, `_extract_task_query`.
   - File: [backend_fastapi/agents/langraph_workflow.py](backend_fastapi/agents/langraph_workflow.py#L40-L170)

5. Stage sequencing (LangGraph state transitions)
   - LangGraph transitions through `task_stage`, `rag_stage`, `analysis_stage`, `chat_final` according to router output.
   - Each node invokes a handler (`_task_stage_node`, `_rag_stage_node`, `_analysis_stage_node`, `_chat_final_node`) that prepares payloads for agents.
   - File: [backend_fastapi/agents/langraph_workflow.py](backend_fastapi/agents/langraph_workflow.py#L170-L320)

6. MCP server and tool availability
   - `MCPServer` is initialized at startup and standard tools are registered (`create_task`, `search_tasks`, `vector_search`, `complete_task`, `reopen_task`, `delete_task`).
   - File: [backend_fastapi/main.py](backend_fastapi/main.py#L352-L520) and [backend_fastapi/mcp_server.py](backend_fastapi/mcp_server.py#L1)

7. Task stage execution (TaskAgent)
   - The workflow calls `TaskAgent.execute(...)` for operations like `list_tasks`, `create_task`, or `complete_task`.
   - `TaskAgent` uses `mcp_server.call_tool(...)` (ToolCallRequest) to perform searches or task mutations.
   - File: [backend_fastapi/agents/agents.py](backend_fastapi/agents/agents.py#L1-L260)

8. RAG stage execution (RAGAgent)
   - The workflow calls `RAGAgent.execute(...)` for `search` operations.
   - `RAGAgent` uses the MCP `vector_search` tool which wraps `generate_embedding` + `vector_search(db, embedding)`.
   - Files: [backend_fastapi/agents/agents.py](backend_fastapi/agents/agents.py#L260-L420), [backend_fastapi/embeddings.py](backend_fastapi/embeddings.py#L1)

9. Analysis stage execution (AnalysisAgent)
   - The workflow calls `AnalysisAgent.execute(...)` with aggregated `stage_context` and `stage_tool_results` to compute summaries or metrics.
   - File: [backend_fastapi/agents/agents.py](backend_fastapi/agents/agents.py#L720-L920)

10. Final composition (ChatAgent)
   - `ChatAgent` receives the final assembled prompt and calls `chat_with_tools(user_message, context, tool_results)`.
   - `chat_with_tools` calls Mistral or local fallback and uses a system prompt tailored for task management.
   - Files: [backend_fastapi/agents/agents.py](backend_fastapi/agents/agents.py#L320-L380), [backend_fastapi/ollama_client.py](backend_fastapi/ollama_client.py#L1)

11. Workflow return
   - `LangGraphWorkflow` compiles `WorkflowState` to include `workflow_log`, aggregated `result`, and `task_id`.
   - The HTTP response returns: `task_id`, `status`, `error`, `result`, `workflow_log`.
   - File: [backend_fastapi/main.py](backend_fastapi/main.py#L2020-L2038)

12. Observability and debugging
   - Message routing and agent events are logged via `_log_agent_event` and `_log_agent_result` in `agents.py`.
   - `AgentManager.message_history` stores recent agent messages and is exposed by `/api/agents/message-history`.
   - Files: [backend_fastapi/agents/agents.py](backend_fastapi/agents/agents.py#L1), [backend_fastapi/agents/agent_manager.py](backend_fastapi/agents/agent_manager.py#L1)

Notes and safety
 - All MCP tool calls happen server-side and return structured results; no tool executes arbitrary code outside registered handlers.
 - Tools use the same DB session for consistency and commit/rollback semantics.
 - Permission checks (e.g., admin-only indexing) are enforced before tool calls in controller endpoints.

---

#### 2.4.8 Single Chat-Agent Flow and Comparison to LangGraph+MCP

Single-chat-agent flow (simpler, single-pass design):

1. Client calls `POST /api/ai/chat/` with `message`, `use_context`, `use_tools`.
    - File: [backend_fastapi/main.py](backend_fastapi/main.py#L1940)
2. Authentication: `get_current_user_dep(request)` validates the user and roles.
    - File: [backend_fastapi/main.py](backend_fastapi/main.py#L684)
3. Context retrieval (if `use_context`):
    - `generate_embedding(payload.message)` runs in a thread pool.
    - `vector_search(db, query_embedding, limit=3)` returns top docs and similarity scores.
    - Files: [backend_fastapi/embeddings.py](backend_fastapi/embeddings.py#L1), [backend_fastapi/main.py](backend_fastapi/main.py#L1654)
4. Intent/keyword detection and tool inference (if `use_tools`):
    - `_is_deadline_question`, `_tool_from_semantic_intent`, and `_infer_tool_from_keywords` are used to select a tool and arguments.
    - Files: [backend_fastapi/rag_tools.py](backend_fastapi/rag_tools.py#L1), [backend_fastapi/main.py](backend_fastapi/main.py#L1497)
5. Synchronous tool execution (single agent style):
    - `_tool_call(db, tool_name, tool_args, tool_calls)` executes the selected tool(s) and appends results to `tool_calls`.
    - Tools are handled by functions in `rag_tools.py` or MCP handlers when available.
    - File: [backend_fastapi/main.py](backend_fastapi/main.py#L1497)
6. Single LLM call (compose and respond):
    - The backend calls `chat_with_tools(user_message, context_text, tool_results_text)` once, using tool outputs and context.
    - File: [backend_fastapi/ollama_client.py](backend_fastapi/ollama_client.py#L210)
7. Return structured payload containing `message`, `context`, `tool_calls`, and `response`.

Comparison: LangGraph+MCP vs Single Chat-Agent

- **Modularity & Separation of Concerns**:
   - LangGraph+MCP: High — specialized agents (`TaskAgent`, `RAGAgent`, `AnalysisAgent`, `ChatAgent`) each handle focused responsibilities; MCP exposes tools with clear contracts. Easier to extend and test agents independently.
   - Single Chat-Agent: Low — monolithic flow handles detection, search, tool-calling, and response composition in one path.

- **Correctness & Safety**:
   - LangGraph+MCP: Better for safety-critical operations — agents can validate tool inputs, and MCP centralizes tool permissions and validation.
   - Single Chat-Agent: Easier to make mistakes when combining logic; requires careful guardrails in the single code path.

- **Latency & Resource Use**:
   - LangGraph+MCP: Potentially higher latency due to multi-stage agent calls and handoffs, but stages can run concurrently when designed so.
   - Single Chat-Agent: Lower end-to-end latency for straightforward queries because it performs a single composed round-trip to the LLM after local tool calls.

- **Observability & Debugging**:
   - LangGraph+MCP: Superior — `workflow_log`, `AgentManager.message_history`, and agent-level logs provide rich traceability.
   - Single Chat-Agent: Simpler logs, but harder to isolate which substep produced which result.

- **Maintainability & Extensibility**:
   - LangGraph+MCP: Easier to add new agents/tools and to plug workflows (LangGraph nodes). Good for complex multi-step business rules.
   - Single Chat-Agent: Faster to implement simple features; becomes tangled as complexity grows.

- **Testing**:
   - LangGraph+MCP: Agents and MCP tools are unit-testable; workflows are testable via state transitions.
   - Single Chat-Agent: Requires more integration-style tests because logic is centralized.

- **When to use which**:
   - Use LangGraph+MCP when requests are multi-step, require coordination (search -> analyze -> act), need traceability, or when tools require strict validation and audit trails.
   - Use Single Chat-Agent when requests are simple Q&A, or when low latency for single-shot answers is critical and the operations are limited.

---

## 3. Frontend Code Path Details
 
#### 2.4.9 Why use MCP (Model Context Protocol) instead of simple tools

This project exposes both simple tool functions (e.g., functions in `rag_tools.py`) and a structured MCP server (`MCPServer`) that registers tools with explicit parameter schemas, handlers, resources and prompts. Below are concrete benefits, examples, and recommended usage patterns.

- Centralized tool registry and discovery
   - `MCPServer` keeps a single authoritative list of tools, accessible via `/api/mcp/tools` and programmatically via `mcp_server.list_tools()`.
   - Files: [backend_fastapi/mcp_server.py](backend_fastapi/mcp_server.py#L1), [backend_fastapi/routes_mcp.py](backend_fastapi/routes_mcp.py#L1)

- Strong contract and parameter validation
   - Each tool is defined with `ToolParameter` metadata. This provides parameter names, types, descriptions, and `required` flags so callers and UIs can validate before execution.
   - Files: [backend_fastapi/mcp_server.py](backend_fastapi/mcp_server.py#L20)

- Unified async-safe execution and error handling
   - `MCPServer.call_tool()` normalizes sync and async handlers, returns `ToolCallResult` with `success`, `result`, and `error` fields, and catches exceptions consistently.
   - File: [backend_fastapi/mcp_server.py](backend_fastapi/mcp_server.py#L120)

- Resource & prompt management
   - Register prompt templates and resources centrally (`mcp_server.register_prompt`, `register_resource`) so workflows and agents reuse canonical prompts and datasets.
   - Files: [backend_fastapi/main.py](backend_fastapi/main.py#L440), [backend_fastapi/mcp_server.py](backend_fastapi/mcp_server.py#L60)

- Observability, tracing and auditability
   - MCP calls produce structured results that are easy to log, serialize, and include in `WorkflowState.workflow_log`.
   - Agent `workflow` entries and `AgentManager.message_history` hold call traces for audits.
   - Files: [backend_fastapi/agents/agents.py](backend_fastapi/agents/agents.py#L1), [backend_fastapi/agents/agent_manager.py](backend_fastapi/agents/agent_manager.py#L1)

- Security and permissions
   - MCP tool registration centralizes permission checks and can enforce RBAC at the tool layer before executing sensitive operations (e.g., indexing, deletion).
   - Example: `index_documents` endpoint enforces admin role before calling indexer tools.
   - File: [backend_fastapi/main.py](backend_fastapi/main.py#L1872)

- Testability and mocking
   - Tools registered in MCP are simple callables that can be replaced or mocked in tests via `set_mcp_server()` or by injecting a test `MCPServer` instance.
   - Files: [backend_fastapi/routes_mcp.py](backend_fastapi/routes_mcp.py#L1)

- Versioning and lifecycle of tools
   - Tools in MCP can include `metadata` fields (version, owner) so clients can adapt to tool changes without breaking contracts.
   - File: [backend_fastapi/mcp_server.py](backend_fastapi/mcp_server.py#L1)

- Composability with LangGraph workflows
   - LangGraph nodes call agents which in turn call MCP tools; MCP becomes the lingua franca across agents so complex workflows compose reliably.
   - File: [backend_fastapi/agents/langraph_workflow.py](backend_fastapi/agents/langraph_workflow.py#L1)

Concrete examples

- Calling a tool via MCP (HTTP)

Request (POST /api/mcp/tools/call):

{
   "tool_name": "search_tasks",
   "arguments": { "query": "design API", "limit": 5 }
}

Successful response (200):

{
   "tool_name": "search_tasks",
   "success": true,
   "result": { "results": [ /* task items */ ], "count": 3 }
}

- Calling a tool programmatically (inside an agent)

```
from mcp_server import ToolCallRequest
result = await mcp_server.call_tool(ToolCallRequest(tool_name="vector_search", arguments={"query":"auth flow"}))
if result.success:
      docs = result.result.get("results", [])
```

- Direct function call (simple tool)

```
# direct execution (less structured)
from rag_tools import search_tasks
results = search_tasks("design API", db)
```

Why prefer MCP in production

- Structured inputs/outputs reduce accidental misuse of tools.
- Centralized registration simplifies client UIs and reduces duplicated discovery logic.
- MCP hides sync/async complexity and integrates retries/fallbacks in one place.
- It supports safer orchestration when multiple agents or workflows must share the same tools.

When simple tools are acceptable

- Quick prototypes, local scripts, or one-off admin actions where strict contracts are unnecessary.
- Low-complexity systems where adding MCP infrastructure would add overhead without benefits.

Recommendation

- For this repository, continue using direct helper functions in `rag_tools.py` for quick local utilities and tests, but rely on `MCPServer` for any tool that will be used by agents, workflows, or exposed to external clients. This keeps agility for development while ensuring production-grade safety for orchestrated tasks.


### 3.1 App Module and Routing

`frontend/src/app/app.module.ts`

- Registers browser, forms, HTTP client, and routing.
- Declares `TaskListComponent` and `LoginComponent`.
- Imports standalone AI and workflow components.
- Registers interceptors:
  - `CsrfInterceptor`
  - `HttpErrorInterceptor`
  - `AuthInterceptor`
- Defines routes:
  - `/login`
  - `/tasks`
  - `/ai/chat`
  - `/ai/search`
  - `/ai/index`
  - `/ai/agents`
  - `/ai/workflow`

### 3.2 Auth Interceptors and Token Flow

`frontend/src/app/auth.interceptor.ts`

- Adds `withCredentials: true` to every HTTP request.
- Ensures cookies are sent to Django and FastAPI.

`frontend/src/app/csrf.interceptor.ts`

- For non-safe HTTP methods, fetches a CSRF token from `CsrfService`.
- Adds `X-CSRFToken` header to POST/PUT/DELETE requests.
- Persists the CSRF token from response headers when present.

### 3.3 App Service for Django Tasks

`frontend/src/app/app.service.ts`

- `googleLogin(idToken)` calls `backend_django/api/auth/google/`
- `logout()` calls `backend_django/api/auth/logout/`
- `getCurrentUser()` calls `backend_django/api/auth/me/`
- Task operations:
  - `getTasks(...)`
  - `addTask(task)`
  - `updateTask(task)`
  - `deleteTask(taskId)`
  - `getTaskStats()`
  - `bulkUpdateTasks(...)`

### 3.4 AI Service for FastAPI

`frontend/src/app/ai.service.ts`

- `checkHealth()` -> `/api/ai/health/`
- `search(query, limit)` -> `/api/ai/search/`
- `indexDocuments(taskIds)` -> `/api/ai/index/`
- `chat(message, useContext, useTools)` -> `/api/ai/chat/`
- `getTools()` -> `/api/ai/tools/`
- Agent APIs:
  - `/api/agents/system/status`
  - `/api/agents/agents`
  - `/api/agents/execute`
  - `/api/agents/message-history`
- Workflow APIs:
  - `/api/workflow/execute`
  - `/api/workflow/status`
- MCP APIs:
  - `/api/mcp/tools`
  - `/api/mcp/tools/{name}`
  - `/api/mcp/tools/call`
  - `/api/mcp/resources`
  - `/api/mcp/prompts`
  - `/api/mcp/status`

### 3.5 Task List UI

`frontend/src/app/task-list/task-list.component.ts`

- Loads tasks and stats on init.
- Supports pagination and page navigation.
- Creates tasks with client-side validation.
- Toggles completion status.
- Deletes tasks with confirmation.
- Displays server field errors and general errors.

### 3.6 AI Chat UI

`frontend/src/app/ai-chat/ai-chat.component.ts`

- Renders a conversation UI.
- Sends chat messages to the AI backend.
- Supports toggles for context and tool usage.
- Displays AI response text and tool-context metadata.

### 3.7 Vector Search UI

`frontend/src/app/vector-search/vector-search.component.ts`

- Calls FastAPI vector search.
- Displays search results with similarity score colors.
- Search executes on Enter or button click.

### 3.8 AI Indexing UI

`frontend/src/app/ai-indexing/ai-indexing.component.ts`

- Loads existing tasks from Django.
- Allows indexing all tasks or selected tasks.
- Calls `/api/ai/index/` and displays indexed count.

### 3.9 Agents and Workflow UI

- `frontend/src/app/agents/agents.component.ts`
  - Displays agent system status.
  - Lists agents and runs `list_tasks` on an agent.
- `frontend/src/app/langraph-workflow/langraph-workflow.component.ts`
  - Executes workflow requests.
  - Shows MCP status and available tools.

---

## 4. Django Backend Flow

### 4.1 URL Routing

`backend_django/tasks/urls.py`

- Registers task routes with `DefaultRouter`.
- Adds `csrf-token/`, `auth/google/`, `auth/me/`, and `auth/logout/`.

### 4.2 Task Model

`backend_django/tasks/models.py`

- `Task` model fields:
  - `title`
  - `description`
  - `completed`
  - `created_at`

### 4.3 Task Serializer

`backend_django/tasks/serializers.py`

- Validates `title` and `description`.
- Rejects empty or duplicate titles.
- Uses `TaskService` for create/update logic.

### 4.4 Task ViewSet

`backend_django/tasks/views.py`

- `list`: query filtering, search, completed filter, pagination.
- `create`: admin-only task creation.
- `update`: role-aware update rules.
- `destroy`: admin-only deletion.
- `stats`: returns task totals and completion percentage.
- `bulk_update`: updates multiple tasks in one request.

### 4.5 Task Service

`backend_django/tasks/services.py`

- Business logic for creation, update, deletion, stats, and bulk updates.
- Enforces validation:
  - Title length and whitespace
  - Description length
  - Duplicate task titles
- Supports text search on title and description.

### 4.6 Authentication and Roles

`backend_django/tasks/auth_views.py`

- `google_login`: verifies Google token, creates user, assigns roles, returns JWT cookie.
- `get_current_user`: reads token and returns user info.
- `logout_view`: clears the auth cookie.
- Role tables:
  - `users`
  - `roles`
  - `user_roles`

### 4.7 CSRF Support

- `csrf_token` endpoint in `backend_django/tasks/views.py` provides CSRF tokens.
- `CsrfInterceptor` in frontend attaches tokens to state-changing requests.

---

## 5. FastAPI AI Backend Flow

### 5.1 Core App and Startup

`backend_fastapi/main.py`

- Initializes the FastAPI application.
- Configures CORS for allowed origins.
- Creates database tables and pgvector extension on startup.
- Sets up default `admin` and `employee` roles.
- Initializes the multi-agent system and MCP server.

### 5.2 Database Models

- `User`, `Role`, `UserRole` in shared auth model.
- `TaskModel` for task records.
- `DocumentModel` for vector documents.

### 5.3 Authentication

- JWT token validation using `auth_token` cookie or `Authorization: Bearer ...`.
- `get_current_user_dep(request)` extracts token, validates, and loads user roles.
- `require_role()` decorator enforces role-based endpoint access.

### 5.4 Task APIs

FastAPI also exposes task CRUD endpoints in `backend_fastapi/main.py`:

- `GET /api/tasks/`
- `POST /api/tasks/`
- `GET /api/tasks/{task_id}/`
- `PUT /api/tasks/{task_id}/`
- `DELETE /api/tasks/{task_id}/`
- `POST /api/tasks/bulk_update/`
- `GET /api/tasks/stats/`

These mirror the same task functionality as Django and provide alternate access through FastAPI.

### 5.5 AI Health and Tools

- `GET /api/ai/health/` checks Ollama/LLM availability and agent system readiness.
- `GET /api/ai/tools/` returns available tool definitions from `backend_fastapi/rag_tools.py`.

### 5.6 Vector Search and Indexing

- `POST /api/ai/search/` performs semantic similarity search over `documents`.
- `POST /api/ai/index/` writes task text and embeddings to `documents`.
- Embedding generation is handled by `backend_fastapi/embeddings.py`.

### 5.7 Chat Endpoint

`POST /api/ai/chat/`

- Authenticates the user.
- Retrieves context documents when enabled.
- Detects tool-oriented intent and calls helper tools.
- Uses `_run_chat_agent()` to generate the final assistant response.

### 5.8 Agent System

- `backend_fastapi/agents/routes.py` exposes agents endpoints.
- Agent router includes:
  - `GET /api/agents/system/status`
  - `GET /api/agents/agents`
  - `GET /api/agents/agents/{agent_id}`
  - `GET /api/agents/agents/role/{role}`
  - `POST /api/agents/execute`
  - `GET /api/agents/message-history`
- `backend_fastapi/agents/agent_manager.py` manages agent registration and execution.
- `backend_fastapi/agents/agents.py` contains concrete agent implementations.

### 5.9 LangGraph Workflow and MCP

- `POST /api/workflow/execute` runs a LangGraph workflow for complex tasks.
- `GET /api/workflow/status` returns workflow and MCP readiness.
- `backend_fastapi/mcp_server.py` registers tools, resources, and prompts.
- Standard MCP tools include task creation, search, complete/reopen, delete, and stats.

---

## 6. Embeddings and RAG Details

### 6.1 Embedding Generation

`backend_fastapi/embeddings.py`

- Supports local `sentence-transformers` if available.
- Falls back to deterministic hashing when a local model is unavailable.
- Can optionally call Hugging Face remote embedding API.
- Produces fixed-size embeddings for task and query text.

### 6.2 Vector Documents

- `DocumentModel` stores text and embedding vectors.
- `documents` are created from task title + description.
- The FastAPI startup routine ensures `pgvector` is installed and indexes exist.

### 6.3 Search Ranking Logic

`backend_fastapi/rag_tools.py` contains:

- tool definitions for agent use
- semantic search helpers
- deadline detection and task detail extraction
- task status update inference
- query normalization
- permissive filtering after semantic ranking

---

## 7. Database Tables and Synchronization

### Tables

- `users` — stores user profile and shared app identity
- `roles` — stores role names (`admin`, `employee`)
- `user_roles` — maps users to roles
- `tasks` — stores task data
- `documents` — stores embeddings and text for semantic search

### Shared State

- Both Django and FastAPI read from the same database.
- Django handles task CRUD and user authentication.
- FastAPI reuses tasks and user records to enable AI search and agent actions.

---

## 8. Docker and Deployment

- `docker-compose.yml` can run the Django + Angular stack.
- `docker-compose.fastapi.yml` can run the FastAPI AI stack.
- `frontend/Dockerfile` builds the Angular app.
- `backend_django/Dockerfile` builds the Django API.
- `backend_fastapi/Dockerfile` builds the FastAPI AI backend.

---

## 9. Summary of Supported Features

- Google authentication and JWT session cookie
- Role-based task permissions (`admin` vs `employee`)
- Task list, create, update, delete, stats, and bulk update
- CSRF protection for Django requests
- Semantic task search over vector embeddings
- Document indexing for AI retrieval
- AI chat with context and tool-calling
- Multi-agent system health, execution, and message history
- LangGraph workflow execution and MCP tool interfaces

---

## 10. Recommended Starting Points

- Start with the user-facing login and task UI in `frontend/src/app/`
- Inspect Django task logic in `backend_django/tasks/`
- Explore FastAPI AI routes in `backend_fastapi/main.py`
- Review agent and MCP architecture in `backend_fastapi/agents/` and `backend_fastapi/mcp_server.py`
- Check embedding behavior in `backend_fastapi/embeddings.py`

This file documents the end-to-end request flows, the major code paths, and the complete feature set of the project.