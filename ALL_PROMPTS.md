# All Prompts for AI Chat and LangGraph Workflow

## AI CHAT PROMPTS (Single Prompts)

### 1. **System Prompt for Chat (with force_natural=False)**
```
You are TaskFlow AI, a concise task-management assistant for a productivity app. 
Your job is to help users create, review, update, search, summarize, and prioritize tasks. 
Always answer in a practical, user-friendly way. 
If tool results are available, use them as the primary source of truth and mention task IDs when present. 
When tool results contain task lists, include the title, status, and a short description for each task. 
When tool results contain statistics, clearly report completed, pending, and total counts. 
When context is relevant, use it to support the answer; if it is unrelated, ignore it. 
Do not invent deadlines, ownership, or schedule details that are not provided. 
If the user asks to create or update a task, ask for the missing fields only if needed. 
If the request is ambiguous, briefly ask a clarifying question instead of guessing.

When you determine that an agent/tool should be invoked, output EXACTLY one JSON object and nothing else. 
The object must follow this schema: {"agent": optional string, "tool": string, "args": object, "intent": optional string, "confirm": boolean}. 
If you need clarification, ask a plain-language question (no JSON). 
Examples: {"agent":"task_manager_001","tool":"create_task","args":{"title":"My Task"},"intent":"create","confirm":false} or {"tool":"search_tasks","args":{"query":"pending tasks by June 27"},"confirm":false}.
```

### 2. **System Prompt for Chat (with force_natural=True)**
```
You are TaskFlow AI, a concise task-management assistant for a productivity app. 
Answer in plain natural language and do not output JSON proposals. 
When tool results are available, use them as the primary source of truth and mention task IDs when present.
```

### 3. **System Prompt for generate_response (Basic)**
```
You are TaskFlow AI, a concise task-management assistant for a productivity app. 
Always produce a structured JSON proposal when you decide a tool/agent should be invoked.
```

### 4. **Intent Classification Prompt**
```
Classify the intent of the user text below into one of these labels: create, complete, update, deadline, stats, search, list, general.
Return only the single label.

Text: {user_message}
```

### 5. **Proposal Instruction (Embedded in all chat prompts)**
```
When you determine that an agent/tool should be invoked, output EXACTLY one JSON object and nothing else. 
The object must follow this schema: {"agent": optional string, "tool": string, "args": object, "intent": optional string, "confirm": boolean}. 
If you need clarification, ask a plain-language question (no JSON). 
Examples: {"agent":"task_manager_001","tool":"create_task","args":{"title":"My Task"},"intent":"create","confirm":false} or {"tool":"search_tasks","args":{"query":"pending tasks by June 27"},"confirm":false}.
```

---

## LANGRAPH WORKFLOW PROMPTS (Combined Prompts for Multi-Agent Orchestration)

### 1. **LLM Routing Classifier Prompt** (Used when ambiguous_prompt=True)
```
Classify the user request into the best routing category. Return JSON only with keys 'route' and 'confidence'.
Route definitions:
- task: Task management only (create, list, complete, delete tasks)
- task_analysis: Task management + analysis (list tasks, then analyze/estimate/prioritize/report on them)
- task_rag: Task management + document/code retrieval (find tasks related to documentation/codebase)
- rag: Document/code retrieval only (search docs, architecture, source code)
- rag_analysis: Document retrieval + analysis (find docs, then analyze/summarize/compare)
- analysis: Analysis only (analyze, summarize, estimate, prioritize, report without task context)
- task_rag_analysis: All three - tasks + documents + analysis
- chat: General conversation, no specific domain
Use 'uncertain' only when you cannot confidently classify.
User request: {user_input}
```

### 2. **Bulk Action Classifier Prompt** (For semantic intent on status actions)
```
Decide whether this request means to search for matching tasks first and then apply the status action to those results. 
Return JSON only with keys 'use_bulk_search' and 'reason'.
User request: {user_input}
```

### 3. **Task Stage Combined Prompt** (Multiple operations in one flow)
```
User request: {user_input}
Context: {stage_context or task_context}
Results: {stage_tool_results or 'No tool results'}
Workflow steps: {number_of_steps} stages executed

Please:
1. List all tasks matching the criteria
2. For each task, show: ID, Title, Status (✓ Done or ⏳ Pending), Description
3. If requested, apply the specified action (complete, delete, reopen, etc.)
4. Provide a summary of what was done
```

### 4. **RAG Stage Combined Prompt** (Document retrieval within workflow)
```
User request: {user_input}
Task context: {previous_task_results}
Search for documents and code related to: {user_input}
Limit: 5 results
Threshold: 0.7
Return both the relevant documents and analysis if requested.
```

### 5. **Analysis Stage Combined Prompt** (Analysis after task/RAG stages)
```
User request: {user_input}
Context from previous stages: {stage_context}
Tool results so far: {stage_tool_results}

Please provide analysis including:
- Summary of findings
- Key statistics or trends
- Priority recommendations (if applicable)
- Insights and explanations
```

### 6. **Final Chat Synthesis Prompt** (Multi-stage finalization)
```
User request: {user_input}
Context: {stage_context or task_context or 'No extra context'}
Results: {stage_tool_results or 'No tool results'}
Workflow steps: {workflow_log_count} stages executed

Based on all the information gathered from the workflow stages above, provide a concise, natural-language response to the user's original request.
Include relevant task IDs, statistics, and actionable recommendations.
```

### 7. **Coordinator Agent Final Prompt** (Full orchestration flow)
```
User request: {message}
Context: {stage_context or context or 'No extra context provided'}
Tool results: {stage_tool_results or tool_results or 'No tool results'}
Workflow steps: {list_of_completed_workflow_steps}

Please synthesize all the information from the workflow stages and provide a clear, helpful response to the user's original request.
```

---

## WORKFLOW ROUTING LOGIC (Automatic Prompt Selection)

### Routing Keywords by Category:

**Task Keywords:**
- mark, complete, delete, reopen, list, show, task, tasks, task#, taskid

**RAG Keywords:**
- search, find, related, about, look, documents, document, docs, doc, context, retrieve, documentation, architecture, design, reference, info, inspect, review, understand, explain, details, source

**Analysis Keywords:**
- analyze, analysis, summary, stats, trend, urgent, report, count, summarize, insight, insights, compare, assess, explain, priority, prioritize, importance, important, estimate, projection, forecast

**Compound Prompt Indicators:**
- " and then ", " if ", " then ", " also ", " plus ", " and "

---

## WORKFLOW STAGES (Combined Prompt Execution Order)

### Stage 1: Router Node
Analyzes user input and determines which stages to execute:
- **task_only**: Task management only
- **rag_only**: Document retrieval only
- **analysis_only**: Analysis only
- **chat_only**: General chat
- **task_rag**: Task + document retrieval
- **task_analysis**: Task + analysis
- **rag_analysis**: Document retrieval + analysis
- **task_rag_analysis**: All three (full flow)

### Stage 2: Task Stage Node
- Routes through TaskAgent for task management operations
- Supports: list, create, complete, delete, reopen tasks
- Can execute bulk operations on searched tasks
- Accumulates results in `stage_tool_results`

### Stage 3: RAG Stage Node
- Routes through RAGAgent for semantic search
- Performs vector search on documents and codebase
- Accumulates context in `stage_context`
- Returns relevant documents/code snippets

### Stage 4: Analysis Stage Node
- Routes through AnalysisAgent
- Performs data analysis on accumulated results
- Generates insights, statistics, trends
- Builds on previous stage results

### Stage 5: Chat Final Node
- Routes through ChatAgent
- Synthesizes all stage results
- Produces final natural-language response
- Scans for auto-executable proposals

---

## LOCAL FALLBACK PROMPTS (When API unavailable)

Used by `_local_model_response()` function:

**Create Intent Response:**
```
{LOCAL_AGENT_NAME}: I can help create a task. 
Please send the title, priority, and any notes or due date you want saved.
```

**Complete Intent Response:**
```
{LOCAL_AGENT_NAME}: I can help mark a task complete. 
Send the task ID or title and I'll route the update.
```

**Update Intent Response:**
```
{LOCAL_AGENT_NAME}: I can help update a task. 
Tell me which field should change and what the new value should be.
```

**Search Intent Response:**
```
{LOCAL_AGENT_NAME}: I don't have enough indexed context yet, 
but I can still help narrow the search terms you should use.
```

**General Response:**
```
{LOCAL_AGENT_NAME}: I'm running in local fallback mode. 
I can still help with task summaries, search hints, and next-step guidance.
```

---

## INTENT CLASSIFICATION LABELS & KEYWORDS

```
INTENT_LABELS = ["create", "complete", "update", "deadline", "stats", "search", "list", "general"]

INTENT_KEYWORDS = {
    "create": ["create task", "new task", "add task", "make task", "create a task"],
    "complete": ["complete", "finish", "mark done", "done", "close task"],
    "update": ["update", "edit", "rename", "change task", "modify"],
    "deadline": ["deadline", "due", "when", "overdue", "by when"],
    "stats": ["stats", "count", "how many", "completed", "pending", "total tasks"],
    "search": ["search", "find", "look for", "where is", "query"],
    "list": ["list", "show", "what tasks", "tasks", "task list"],
}
```

---

## JSON PROPOSAL FORMAT (For agent/tool invocation)

```json
{
  "agent": "task_manager_001",
  "tool": "create_task",
  "args": {
    "title": "string",
    "description": "string (optional)"
  },
  "intent": "create",
  "confirm": false
}
```

**Available Tools:**
- `create_task`: Create new task
- `complete_task`: Mark task as completed
- `update_task`: Update task details
- `search_tasks`: Search for tasks by query
- `list_tasks`: List all tasks with filters
- `delete_task`: Delete a task
- `reopen_task`: Reopen a completed task
- `vector_search`: Semantic document search
- `sort_tasks_by_time`: Sort tasks by deadline

---

## AGENT-SPECIFIC RESPONSE TEMPLATES

### TaskAgent Response
```json
{
  "status": "success|error",
  "message": "Human-readable message",
  "tasks": [{"id": int, "title": string, "status": string, "description": string}],
  "count": int,
  "created_task": object (optional),
  "workflow_log": array
}
```

### ChatAgent Response
```json
{
  "status": "success|error",
  "response": "Natural language response text"
}
```

### RAGAgent Response
```json
{
  "status": "success|error",
  "results": [{"document": string, "similarity": float, "context": string}],
  "count": int
}
```

### AnalysisAgent Response
```json
{
  "status": "success|error",
  "insights": [string],
  "summary": string,
  "statistics": object
}
```

---

## KEY CONFIGURATION VARIABLES

- `ENABLE_LLM_ROUTING_CLASSIFIER`: Enable/disable LLM-based ambiguous prompt classification (default: true)
- `MISTRAL_BASE_URL`: Base URL for Mistral API (default: https://api.mistral.ai/v1)
- `MISTRAL_MODEL`: Model to use (default: mistral-tiny)
- `MISTRAL_API_KEY`: API key for Mistral
- `HTTP_TIMEOUT`: Request timeout in seconds (default: 45.0)
- `VERIFY_SSL`: SSL verification (default: false)

---

## STAKEHOLDER & DEVELOPER Q&A

### SINGLE AI CHAT PROMPT QUESTIONS

#### Functionality & Behavior
1. **What happens if a user asks the chat agent something completely unrelated to task management?**
   - The system will attempt to classify intent, fall back to "general", and provide guidance within the task management domain.

2. **When should `force_natural=True` vs `force_natural=False` be used?**
   - Use `force_natural=True` for chat interfaces where users expect conversational responses.
   - Use `force_natural=False` when you want structured JSON proposals for automated tool invocation.

3. **Can the chat agent refuse to create a task or execute a tool?**
   - Yes, if the request is ambiguous, the chat agent will ask clarifying questions rather than guessing.

4. **How does the system handle conflicting intents** (e.g., "complete the task and then reopen it")?
   - The router analyzes compound prompts and either triggers the LLM classifier or follows rule-based routing to select the most appropriate workflow path.

5. **What happens when tool results are empty or null?**
   - The system provides a fallback response: "I don't have enough indexed context yet, but I can still help narrow the search terms."

#### Prompt Customization
6. **Can we modify the system prompt for different user types** (e.g., power users vs. casual users)?
   - Yes, the system prompt can be modified per request or session. Recommend creating variants in the configuration.

7. **How do we handle multi-language support?**
   - The current prompts are in English. For multi-language, translate the system prompt and intent keywords, then implement language detection.

8. **Can we add role-based prompts** (e.g., admin vs. team member)?
   - Yes, add context to the system prompt about user permissions and visibility constraints before calling `chat_with_tools()`.

9. **How sensitive is the system to prompt wording?**
   - Moderately sensitive. The system uses keyword matching first, then falls back to LLM classification if keywords are ambiguous. Minor wording changes usually don't affect routing.

10. **What's the recommended max length for a single chat prompt?**
    - Keep user messages under 500 characters for reliable intent classification. Longer messages may trigger ambiguous_prompt handling.

#### Performance & Cost
11. **Which single prompts are most expensive in terms of API calls?**
    - Intent classification with LLM (`_classify_intent_with_model`) is expensive. Use keyword-based classification first.
    - Proposal instructions are embedded, so no additional cost.

12. **Can we batch chat requests to reduce API latency?**
    - No, chat is synchronous. Use async handlers to parallelize multiple user requests.

13. **What's the fallback behavior if the Mistral API is unavailable?**
    - System uses `_local_model_response()` - a lightweight deterministic response without LLM inference.

14. **How often should prompts be retested after updates?**
    - Test after any system prompt modification, keyword addition, or intent label change. Recommend weekly regression testing.

#### Quality & Reliability
15. **How do we measure prompt effectiveness?**
    - Track: intent classification accuracy, tool invocation success rate, user confirmation rate for proposals, fallback activation rate.

16. **What's the expected accuracy of intent classification?**
    - Keyword-based: ~85-90% for common intents. LLM-based: ~95%+ but slower and more expensive.

17. **How do we handle edge cases** (e.g., sarcasm, ambiguous language)?
    - Current system doesn't handle sarcasm well. For edge cases, the ambiguous_prompt classifier triggers and asks for clarification.

18. **Can we A/B test different system prompts?**
    - Yes, add an `prompt_variant` parameter to route different system prompts and collect metrics on success rates.

---

### COMBINED LANGRAPH WORKFLOW PROMPT QUESTIONS

#### Routing & Orchestration
1. **When is the LLM Routing Classifier used vs. rule-based routing?**
   - LLM classifier is used when: `ambiguous_prompt=True` AND `ENABLE_LLM_ROUTING_CLASSIFIER=true` AND signal_count ≤ 1 or compound_prompt detected.
   - Rule-based routing is used for clear single-intent or multi-intent combinations.

2. **What happens if the router detects 3+ intents** (task, RAG, analysis)?
   - If user input contains all three, it automatically triggers `task_rag_analysis` - the full multi-agent flow.

3. **How does the system decide between `task_only` vs `task_rag`?**
   - Task-only: User wants specific task actions (create/complete/list/delete). No document retrieval.
   - Task-RAG: User asks for tasks AND context/documentation (e.g., "find tasks related to authentication").

4. **Can a workflow stage be skipped?**
   - Yes, the router determines which stages run. If no RAG keywords detected, RAG stage is skipped entirely.

5. **What happens if a user asks for something that spans all 4 workflow stages?**
   - Full workflow executes: router → task_stage → rag_stage → analysis_stage → chat_final → finalize.
   - Example: "List my pending tasks, search related documentation, analyze the complexity, and summarize what I should focus on."

#### Multi-Stage Context Passing
6. **How is context accumulated across workflow stages?**
   - Each stage appends to `stage_context` and `stage_tool_results`. The next stage receives all accumulated context.
   - Example: Task stage finds 5 tasks → RAG stage searches docs about those tasks → Analysis stage prioritizes them.

7. **Can a later stage override decisions made by earlier stages?**
   - No, each stage builds on previous results. But a stage can flag results as "uncertain" to trigger manual review.

8. **What if the task stage fails** - does the workflow abort?
   - No, the workflow logs the error and continues. Later stages receive the error message and can adapt accordingly.

9. **How much context can each stage pass before exceeding token limits?**
   - Recommend keeping `stage_context` + `stage_tool_results` under 8,000 tokens for Mistral. Truncate old results if needed.

10. **Can we parallelize workflow stages** (e.g., task + RAG simultaneously)?
    - Current architecture is sequential by design. Parallelization would require graph restructuring in LangGraph.

#### Bulk Operations & Search
11. **When does the system treat an action as "bulk"** (e.g., complete all pending tasks)?
    - When: user input contains selection keywords ("any", "all", "these", "them", "pending") AND `last_searched_tasks` is available.

12. **How does `_should_use_bulk_search_action()` decide to search before completing tasks?**
    - Uses LLM classifier on the request. Example: "mark any pending task complete" → searches for pending tasks first, then completes them.

13. **Can we execute multiple bulk operations in one request?**
    - Yes, if the user input is parsed as multiple actions. Example: "complete done tasks and delete old ones" → two bulk operations.

14. **What happens if a bulk search returns 0 results?**
    - System returns success with count=0 and message: "No matching tasks to complete/delete/reopen."

#### Multi-Agent Communication
15. **How do agents communicate with each other in the workflow?**
    - Agents don't directly communicate. The workflow orchestrator (LangGraph) passes state and results between stages.

16. **Can one agent's output be directly fed as input to another agent's prompt?**
    - Yes, this is the core design. Task results are serialized and passed to RAG/Analysis prompts as context.

17. **What if one agent's response is in an unexpected format?**
    - The workflow has error handling. Unexpected formats are logged, and the next stage receives the raw text + error flag.

18. **How do we prevent context explosion** (prompts getting infinitely longer)?
    - Use `_format_tool_summary()` to truncate results. Each stage keeps only 260 chars of context for previous results.

#### Response Synthesis
19. **How does the Final Chat node decide what to emphasize in the response?**
    - Uses the full `workflow_log` to understand what stages executed, then synthesizes a response that addresses the user's original intent.

20. **Can the user see the intermediate stage results** (task results, RAG results, analysis)?
    - Currently, no. The final response is synthesized. To expose intermediate results, add them to the `workflow_log` field in the response.

21. **What happens if multiple workflow stages generate conflicting recommendations?**
    - The Final Chat node receives all results and can note the conflict. Example: "Task analysis suggests 10 items, but RAG shows only 3 related documents."

22. **How are JSON proposals detected and executed automatically?**
    - After each stage and final chat, `_scan_and_execute_proposal_from_text()` searches for `{ }` JSON objects and validates them against the proposal schema.

#### Performance & Scalability
23. **What's the typical latency for a full `task_rag_analysis` workflow?**
    - ~5-15 seconds depending on: API response times, number of tasks/documents searched, analysis complexity.

24. **Can we cache workflow results for similar queries?**
    - Not built-in, but you could add a cache layer before the router node to store recent workflow results.

25. **How many concurrent workflows can the system handle?**
    - Depends on your infrastructure. Each workflow is async, so 100+ concurrent requests are feasible with proper async execution.

26. **Should we use LLM routing classifier for high-traffic scenarios?**
    - No, disable it (`ENABLE_LLM_ROUTING_CLASSIFIER=false`). Use rule-based routing only to reduce latency and costs.

#### Error Handling & Debugging
27. **What happens if the MCP server is unavailable during a workflow?**
    - Agents return `{"status": "error", "message": "MCP server not available"}`. The workflow logs the error and continues with fallback responses.

28. **How do we debug a workflow that produces unexpected output?**
    - Check the `workflow_log` field in the response. It contains every agent call, result, and timestamp. Look for failed operations or unusual routing decisions.

29. **Can we replay a workflow with the same input?**
    - Yes, store the `task_id` and `dialog_history` from the `WorkflowState`. Replay by providing the same `user_input` and `task_context`.

30. **What's logged when a prompt fails?**
    - Full error stack trace in the logger. Check logs for: "Error in [stage_name]", "LLM routing classifier failed", "MCP server error".

---

### GENERAL SYSTEM QUESTIONS

#### Design & Architecture
1. **Why are there 5 single prompts and 7 combined prompts?**
   - Single prompts handle straightforward user intents (create, list, search, etc.).
   - Combined prompts orchestrate multi-stage workflows where results flow between agents (task → RAG → analysis → chat).

2. **Could we reduce the number of prompts?**
   - Theoretically, yes. But each prompt is optimized for its specific context and agent capability. Consolidating would reduce flexibility.

3. **What's the relationship between single prompts and combined prompts?**
   - Single prompts are building blocks. Combined prompts orchestrate them. Example: single `Chat Prompt` is used in the `Final Chat Synthesis` combined prompt.

4. **Why is the router node separate from the task/RAG/analysis stages?**
   - Separation of concerns. The router makes a one-time routing decision. Stages execute operations. This makes the system modular and testable.

5. **Should every workflow execution go through the router?**
   - Yes. The router determines the optimal path. Even simple requests benefit from intent detection.

#### Integration & Extension
6. **How would we add a new agent type** (e.g., Calendar Agent)?
   - Create a new Agent subclass, add keywords to the router, create a new workflow stage node, and add a combined prompt for orchestration.

7. **Can we use this system with a different LLM provider** (not Mistral)?
   - Yes, replace the `mistral_client.py` with your provider's API client. The prompts are provider-agnostic (use common JSON/text formats).

8. **How do we integrate this with external tools** (Slack, email, calendar)?
   - Add tool definitions to `TOOL_DEFINITIONS` (RAG tools), then implement tool call handlers in the relevant agent's execute() method.

9. **Can we run this system offline?**
   - Yes, use the local fallback mode (`_local_model_response()`). Disable the Mistral API key, and the system uses deterministic responses.

#### Measurement & Analytics
10. **What metrics should we track to evaluate prompt effectiveness?**
    - Intent classification accuracy, tool invocation success rate, user confirmation rate, fallback activation %, workflow completion time, error rate per stage.

11. **How do we A/B test prompt changes?**
    - Add a `prompt_version` parameter. Route 50% of users to version A, 50% to version B. Compare metrics over time.

12. **Can we extract user feedback on prompt quality?**
    - Yes, add a post-response feedback mechanism ("Was this helpful? Yes/No/Unclear"). Store feedback linked to the workflow_log.

#### Governance & Compliance
13. **Are there any prompts that could expose sensitive data?**
    - The prompts don't inherently expose data, but tool results (tasks, documents) might. Ensure MCP server enforces access control.

14. **How do we audit which prompts were used for a specific user request?**
    - Each response includes `workflow_log` with: agent_id, action, timestamp. Store this in your audit log for compliance.

15. **Can we add approval workflows** (e.g., require approval before completing 5+ tasks)?
    - Yes, modify the task stage to check `confirm: true` in proposals and pause execution until human approval.

---

## EXAMPLE USER PROMPTS FOR AI CHAT AGENT (Single Prompts)

### Create Task Examples
```
"Create a task titled 'Review Q3 budget' with description 'analyze quarterly spending report'"
"Add a new task: prepare presentation for client meeting"
"Make a task for fixing the authentication bug"
"Create task title: 'Database optimization' description: 'optimize slow queries in user table'"
```

### Complete Task Examples
```
"Mark task #42 as done"
"Complete task with id 7"
"Finish the authentication task"
"Done with task #105"
```

### Update Task Examples
```
"Update task #15, change title to 'New Title'"
"Rename task #8 to 'API refactoring - Phase 2'"
"Task #3 description should be 'Updated description here'"
"Edit task with id 22, update description to 'Deploy to production next week'"
```

### List/Show Tasks Examples
```
"Show me all tasks"
"List my pending tasks"
"What tasks do I have?"
"Display all completed tasks"
"Show tasks that are open"
```

### Search Examples
```
"Find tasks about authentication"
"Search for documentation about the API"
"Look for tasks related to the database"
"Where are the frontend tasks?"
```

### Intent Classification Examples
```
"How many tasks do I have?" → **stats**
"When is the deadline for task #5?" → **deadline**
"Create a task and show me all pending ones" → **compound** (create + list)
"Mark these as done" → **complete**
"What's in our documentation about deployment?" → **search**
```

### Ambiguous/Clarification Examples
```
"Do something with my tasks" 
→ System: "I can help! Would you like to list, complete, delete, or create a task? Please clarify."

"Check the thing"
→ System: "I'm not sure what you want me to do. Could you be more specific about which task and what action?"
```

---

## EXAMPLE USER PROMPTS FOR LANGRAPH WORKFLOW (Combined Prompts)

### TASK ONLY (Single Task Stage)
```
User: "Create a task for refactoring the payment module"
Route: task_only
Expected Flow: router → task_stage → chat_final → finalize
Output: Task created, then synthesized response confirming creation
```

### RAG ONLY (Document Retrieval)
```
User: "Search our documentation for information about JWT authentication"
Route: rag_only
Expected Flow: router → rag_stage → chat_final → finalize
Output: Retrieves relevant docs about JWT, synthesizes findings
```

### ANALYSIS ONLY (Data Analysis)
```
User: "Analyze my task completion rates and trends"
Route: analysis_only
Expected Flow: router → analysis_stage → chat_final → finalize
Output: Statistics on completed vs pending, trends, recommendations
```

### CHAT ONLY (General Conversation)
```
User: "What's the weather today?"
Route: chat_only
Expected Flow: router → chat_final → finalize
Output: Natural language response; system stays in task management domain
```

### TASK + RAG (Task + Document Retrieval)
```
User: "Find tasks related to the authentication system and show me relevant documentation"
Route: task_rag
Expected Flow: router → task_stage → rag_stage → chat_final → finalize
Output: 
  1. Task stage finds 3 pending auth tasks
  2. RAG stage retrieves JWT/OAuth documentation
  3. Final chat synthesizes: "I found 3 auth tasks and pulled the relevant docs..."
```

### TASK + ANALYSIS (Tasks + Analysis)
```
User: "List my pending tasks and prioritize them by urgency"
Route: task_analysis
Expected Flow: router → task_stage → analysis_stage → chat_final → finalize
Output:
  1. Task stage lists 8 pending tasks
  2. Analysis stage prioritizes by keywords (deadline, important, urgent)
  3. Final chat shows ranked list: "Top priority: ..., High: ..., Medium: ..."
```

### RAG + ANALYSIS (Retrieval + Analysis)
```
User: "Search for documentation about microservices and analyze the architectural patterns"
Route: rag_analysis
Expected Flow: router → rag_stage → analysis_stage → chat_final → finalize
Output:
  1. RAG stage retrieves microservices docs
  2. Analysis stage identifies patterns: API gateway, service discovery, message queues
  3. Final chat summarizes: "Key patterns found: ..."
```

### TASK + RAG + ANALYSIS (Full Multi-Agent Flow)
```
User: "Show me all backend tasks, find related architecture documentation, analyze the complexity, and prioritize what I should work on first"
Route: task_rag_analysis
Expected Flow: router → task_stage → rag_stage → analysis_stage → chat_final → finalize
Output:
  1. Task stage finds 5 backend tasks
  2. RAG stage retrieves 3 architecture docs about microservices
  3. Analysis stage evaluates complexity: "High: API gateway work, Medium: caching layer, Low: logging"
  4. Final chat: "Based on docs and complexity analysis, I recommend starting with the logging task..."
```

---

## EXAMPLE PROMPTS BY INTENT

### CREATE Intent
```
Basic: "Create a task"
Detailed: "Create a task titled 'Database migration' with description 'Migrate from PostgreSQL to MySQL'"
Implicit: "Add a task for fixing the bug in the checkout flow"
Expected: JSON proposal or confirmation request
```

### COMPLETE Intent
```
Explicit ID: "Mark task #12 as complete"
Descriptive: "Complete the authentication task"
Bulk: "Mark all pending tasks as done"
Expected: Confirmation then execution
```

### UPDATE Intent
```
Field update: "Update task #5, change title to 'Phase 2 Frontend Refactor'"
Multi-field: "Task #8 title: 'New Name' description: 'Updated details'"
Alternative: "Update task #8 to have title 'Phase 2 Frontend Refactor'"
Expected: Confirm changes then execute

⚠️ IMPORTANT: Assignment keywords that work: "to", "as", "is", "=", ":"
❌ Does NOT work: "should", "-" (dash), "be"
```

### DEADLINE Intent
```
Query: "When is task #15 due?"
List: "Show me tasks due this week"
Semantic: "What's overdue?"
Expected: Date information or deadline list
```

### STATS Intent
```
Count: "How many tasks do I have?"
Completion: "How many tasks are completed?"
Trending: "Show me completion stats for this month"
Expected: Numbers and statistics
```

### SEARCH Intent
```
Docs: "Find documentation about REST APIs"
Tasks: "Search for tasks about the mobile app"
Codebase: "Look for architecture patterns in our code"
Expected: Relevant documents/code snippets
```

### LIST Intent
```
All: "Show all tasks"
Filtered: "List pending tasks"
Status: "What tasks are open?"
Expected: Structured task list
```

---

## COMPOUND PROMPT EXAMPLES (Trigger Full Workflows)

### Example 1: List → Prioritize
```
User: "Show me all incomplete tasks and tell me which ones are most important"
Detection: has_task (list) + has_analysis (priority)
Route: task_analysis
Execution:
  1. Task stage lists pending tasks
  2. Analysis stage ranks by urgency keywords
  3. Chat synthesizes prioritized list
```

### Example 2: Search → Find → Analyze
```
User: "Search documentation about the API, find related tasks, and tell me what's the most critical work"
Detection: has_rag + has_task + has_analysis
Route: task_rag_analysis
Execution:
  1. Task stage finds API-related tasks
  2. RAG stage retrieves API documentation
  3. Analysis stage identifies critical vs nice-to-have
  4. Chat: "API tasks found: X. Critical: ... Documentation shows: ..."
```

### Example 3: Create + List + Analyze
```
User: "Create a task for the new feature, show me all related tasks, and analyze the workload"
Detection: explicit_create + has_task + has_analysis
Route: task_analysis (with create)
Execution:
  1. Task stage creates the new task then lists related ones
  2. Analysis stage estimates workload impact
  3. Chat: "Created task X. Related tasks: Y. Estimated effort: Z"
```

### Example 4: Complete + Search + Update
```
User: "Mark any pending authentication tasks as complete and show me the updated documentation"
Detection: has_task (complete + search) + has_rag
Route: task_rag
Execution:
  1. Task stage searches for auth tasks, completes them
  2. RAG stage retrieves updated auth documentation
  3. Chat: "Completed X auth tasks. Latest docs show: ..."
```

---

## EDGE CASE PROMPTS

### Ambiguous Prompts
```
"Do something"
→ Router: ambiguous_prompt=true, may trigger LLM classifier
→ Response: "I'm not sure what you'd like. Would you like to create, complete, or list tasks?"

"Check everything"
→ Router: Unclear intent, compound_prompt detection
→ Response: System asks for clarification

"The thing about the stuff"
→ Router: Minimal signal, falls back to chat_only
→ Response: General assistant response
```

### Confirmation Prompts
```
After system suggests: "I can create a task titled 'Review code'. Confirm?"
User: "Yes"
→ Router: Detects follow-up confirmation
→ Execution: Creates the task immediately
```

### Conflicting Requests
```
"Complete task #5 but don't mark it done"
→ Router: Conflicting intent detected
→ Response: "I'm confused - complete and not done are opposite actions. Which did you mean?"

"List only completed and pending tasks"
→ Router: Both statuses requested
→ Execution: Lists all tasks (ignores status filter)
```

---

## EXAMPLE CONVERSATION FLOW

### Single Chat Session
```
User 1: "Create a task for database optimization"
System: "I can create a task titled 'Database optimization'. Any description or priority?"
User 2: "Yes, description: 'Optimize slow queries in user table', priority high"
System: {"agent":"task_manager_001","tool":"create_task","args":{"title":"Database optimization","description":"Optimize slow queries in user table"},"confirm":false}
[Task created with ID 42]
System (synthesized): "Created task #42: Database optimization. The system will monitor slow queries and alert you to critical issues."

User 3: "Show me all tasks"
System: [Lists 8 pending tasks with IDs and descriptions]

User 4: "Complete task #42"
System: "Marking task #42 (Database optimization) as complete..."
[Task marked done]
System (synthesized): "Task #42 is now complete. Nice work!"
```

### Multi-Stage Workflow Session
```
User: "List my API tasks, find related documentation, and analyze the workload"
System detects: task + rag + analysis
Route: task_rag_analysis

[Stage 1 - Task]
System: Found 3 API tasks:
  - #12: REST API refactoring
  - #25: GraphQL endpoint optimization
  - #33: API rate limiting

[Stage 2 - RAG]
System: Found related docs:
  - "REST vs GraphQL performance comparison"
  - "Rate limiting best practices"
  - "API versioning strategy"

[Stage 3 - Analysis]
System: Complexity assessment:
  - High: API rate limiting (new framework needed)
  - Medium: GraphQL optimization (requires profiling)
  - Low: REST refactoring (straightforward)

[Stage 4 - Final Chat]
System: "You have 3 API tasks. Based on the documentation and complexity analysis, I recommend starting with REST refactoring (lowest risk), then GraphQL optimization, and finally rate limiting (requires most work). The rate limiting task will likely take 2-3 days based on the documentation I found."
```

---

### RECOMMENDED WORKFLOW FOR ASKING QUESTIONS

1. **Understand Context**: What is the user trying to accomplish? (Create task? Search? Analyze?)
2. **Identify Path**: Which workflow stages will execute? (task only? task+RAG? full flow?)
3. **Check Performance**: Will this route be fast enough? (Disabled LLM routing for high-traffic?)
4. **Validate Output**: What format does the user expect? (JSON? Natural language? Structured list?)
5. **Measure Success**: How will we know if this prompt worked? (Track intent accuracy? User satisfaction?)

---

## WORKFLOW STATE CONTEXT

The `WorkflowState` object carries:
- `user_input`: Original user query
- `stage_context`: Accumulated context from stages
- `stage_tool_results`: Accumulated tool results
- `current_agent`: Current routing decision
- `dialog_history`: Full conversation history
- `last_created_task`: Most recently created task
- `last_searched_tasks`: Results from last search
- `pending_task_creation`: Pending confirmation for task creation
- `workflow_log`: Complete log of all agent calls
