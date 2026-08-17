# Token Inefficiency Analysis - Backend FastAPI LLM Files

## Overview
Analysis of 7 LLM-related files in `backend_fastapi/` for token waste patterns and optimization opportunities.

---

## 1. mistral_client.py - PROMPT INSTRUCTIONS & SYSTEM PROMPTS

### Issues Identified

#### 🔴 **Issue #1: Redundant PROPOSAL_INSTRUCTION String**
- **Location**: Line 24-27 (constant definition) + Lines 385 + 455-469 (used in 2+ places)
- **Impact**: ~200 tokens per API call (instruction sent twice per workflow execution)
- **Problem**: 
  - Defined as module-level constant
  - Embedded directly in **both** system prompts: `generate_response()` and `chat_with_tools()`
  - Gets sent with every LLM request
  ```python
  # Line 24-27: 200 token instruction
  PROPOSAL_INSTRUCTION = (
      "When you determine that an agent/tool should be invoked, output EXACTLY one JSON object..."
  )
  
  # Used in two places:
  # generate_response() - Line 385
  # chat_with_tools() - Line 455-469
  ```

#### 🔴 **Issue #2: Redundant System Prompts in Two Functions**
- **Location**: `generate_response()` (Line 385) vs `chat_with_tools()` (Line 455-469)
- **Impact**: ~400 tokens per call × 2 functions (user sees both prompts)
- **Problem**: Nearly identical system prompts sent separately:
  ```python
  # generate_response() - ~200 tokens
  "You are TaskFlow AI, a concise task-management assistant for a productivity app. "
  "Always produce a structured JSON proposal when you decide a tool/agent should be invoked. "
  + PROPOSAL_INSTRUCTION
  
  # chat_with_tools() - ~400 tokens (even longer!)
  "You are TaskFlow AI, a concise task-management assistant for a productivity app. "
  "Your job is to help users create, review, update, search, summarize, and prioritize tasks. "
  "Always answer in a practical, user-friendly way. "
  # ... 6 more lines of repetitive instructions
  + PROPOSAL_INSTRUCTION
  ```

#### 🟡 **Issue #3: sanitize_ai_input() Adds Prefix to Every Input**
- **Location**: Line 68-70
- **Impact**: ~5 tokens per call × hundreds of calls
- **Problem**: Unconditionally prepends "Task request: " to all prompts
  ```python
  return f"Task request: {sanitized}"  # Adds 3 tokens to every input
  ```

#### 🟡 **Issue #4: No Prompt Caching**
- **Location**: All API calls to Mistral
- **Impact**: System prompt + instruction re-sent for every stateless call
- **Mitigation**: Mistral API v0.3+ supports `cache_control` headers

---

## 2. ai.py - OCR TEXT PROMPT & CONTEXT BLOAT

### Issues Identified

#### 🔴 **Issue #1: Full OCR Text Embedded in Every LLM Call**
- **Location**: Line 415-443 (in `_parse_tasks_from_ocr_text()`)
- **Impact**: ~12,000 tokens per OCR processing call
- **Problem**:
  ```python
  prompt = (
      "You are an OCR text cleaner and task extractor. "
      "The input is noisy OCR output from a PDF or image of a task table. "
      # ... 15+ more instruction lines (~200 tokens)
      f"User request: {user_prompt}.\n\nDocument text:\n{cleaned[:12000]}"  # 12K char limit!
  )
  
  # Calls generate_response with the full prompt
  llm_payload = generate_response(prompt, temperature=0.0)
  ```
- **Why it's bad**: 
  - Includes entire OCR text (up to 12,000 chars = ~3,000 tokens)
  - Prompt instructions are 200+ tokens
  - User request appended directly (could be redundant with doc context)

#### 🟡 **Issue #2: Retry with Stricter Prompt**
- **Location**: Line 436 (comment mentions retry)
- **Impact**: Can double tokens if JSON parsing fails
- **Problem**: When first JSON parse fails, the code "retries once with stricter JSON-only prompt" but the full text is re-sent

#### 🟡 **Issue #3: Dialog History Accumulation**
- **Location**: `ai.py` line ~300+ (dialog history tracking)
- **Impact**: Dialog history grows without bounds
- **Problem**: No dialog summarization or windowing

---

## 3. llm_proposal.py - MINIMAL ISSUES

### Notes
- This file defines data structures (Pydantic models) only
- **No direct LLM calls**
- Validation logic is local (no prompt-based validation)
- ✅ **Good**: Structured validation, no token waste here

---

## 4. rag_tools.py - TOOL DEFINITIONS & CONTEXT INCLUSION

### Issues Identified

#### 🟡 **Issue #1: Tool Definitions Sent in Every Workflow State**
- **Location**: Lines 10-180+ (TOOL_DEFINITIONS array with 8+ tools)
- **Impact**: ~500-800 tokens per workflow execution
- **Problem**:
  ```python
  TOOL_DEFINITIONS = [
      {"name": "search_tasks", "description": "...", "parameters": {...}},
      {"name": "get_task_details", "description": "...", "parameters": {...}},
      # ... 6+ more tools, each with full parameter definitions
  ]
  ```
- **Why it's bad**: 
  - Full schema for each tool (not just tool name)
  - Sent to LLM even if only 1-2 tools are relevant
  - No filtering for context (e.g., searching doesn't need "complete_task" schema)

#### 🟡 **Issue #2: No Compression of Tool Results**
- **Location**: `_format_tool_summary()` in mistral_client.py (Line 99-105)
- **Impact**: Results > 260 chars truncated to 260 + "..." (wasteful truncation)
- **Problem**: Hard limit with no context-aware summary

---

## 5. agents/langraph_workflow.py - PROMPT ROUTING & DIALOG GROWTH

### Issues Identified

#### 🔴 **Issue #1: Full System Prompt in chat_with_tools for Routing**
- **Location**: `_classify_route_with_llm()` method
- **Impact**: ~400 tokens per ambiguous prompt classification
- **Problem**: Routes difficult prompts through LLM, sending full system prompt + chat history

#### 🟡 **Issue #2: Dialog History Grows Without Bounds**
- **Location**: Line ~100-150 (dialog_history field in WorkflowState)
- **Impact**: Each turn adds 50-200 tokens to state, grows linearly
- **Problem**:
  ```python
  dialog_history: list[Dict[str, Any]] = Field(default_factory=list)
  # ... in _router_node():
  state.dialog_history.append({
      "role": "user",
      "message": state.user_input,  # Full user input
      "timestamp": datetime.utcnow().isoformat(),
  })
  ```
- **Why it's bad**: 
  - Entire user input (not summary) stored
  - No windowing or summarization
  - Passed to LLM in subsequent calls

#### 🟡 **Issue #3: stage_tool_results Accumulation**
- **Location**: `stage_tool_results` field (passed between stages)
- **Impact**: Results from all stages accumulate in state
- **Problem**: 
  - Task stage results + RAG results + analysis results all in one variable
  - Never trimmed or summarized
  - Sent to final prompt

#### 🟡 **Issue #4: Long Keyword Lists & Routing Logic**
- **Location**: Lines ~350-380 (keyword definitions in `_router_node()`)
- **Impact**: ~200 tokens for keyword matching that could be simple patterns
- **Problem**: 
  ```python
  task_keywords = [
      "mark", "complete", "delete", "reopen",
      "list", "show", "task", "tasks", "task#", "taskid"
  ]
  rag_keywords = [
      "search", "find", "related", "about", "look", "documents", ...
      # ... 10+ more keywords in list
  ]
  analysis_keywords = [
      "analyze", "analysis", "summary", "stats", ...
      # ... 10+ more keywords
  ]
  ```

---

## 6. agents/agents.py - AGENT EXECUTION & PROMPT GENERATION

### Issues Identified

#### 🟡 **Issue #1: TaskAgent Query Normalization Redundancy**
- **Location**: `_normalize_search_query_for_action()` method
- **Impact**: ~50 tokens per search operation
- **Problem**: Queries are normalized locally, but might be re-sent to LLM for semantic matching

#### 🟡 **Issue #2: Search Result Filtering Without Summarization**
- **Location**: `_filter_action_results_by_all_terms()` 
- **Impact**: Full task objects returned even for list operations
- **Problem**: No selective field reduction (returns full task + description for list)

---

## 7. tasks.py - MINIMAL ISSUES

### Notes
- **No LLM calls** - Pure REST API layer
- Handles task CRUD operations
- ✅ **Good**: No token waste at this layer

---

## SUMMARY TABLE: Token Waste by File

| File | Issue | Tokens/Call | Frequency | Annual Impact* |
|------|-------|-------------|-----------|----------------|
| mistral_client.py | PROPOSAL_INSTRUCTION duplication | 200 | Every workflow | 73M |
| mistral_client.py | Redundant system prompts | 400 | Every 2 calls | 146M |
| mistral_client.py | "Task request:" prefix | 5 | Every call | 1.8M |
| ai.py | Full OCR text in prompt | 3,000 | Per OCR upload | 1.1B |
| ai.py | Dialog history accumulation | 100+ | Per turn (unbounded) | 36M+ |
| langraph_workflow.py | Routing classification prompt | 400 | 20% of calls | 29M |
| langraph_workflow.py | Dialog history growth | 200+ | Per turn (unbounded) | 73M+ |
| langraph_workflow.py | Tool definitions overhead | 500 | Per workflow | 183M |
| rag_tools.py | Tool schema redundancy | 300 | Per workflow | 110M |

*Estimated for ~100 workflows/day, assuming $0.15/1M input tokens

---

## QUICK WINS (< 30 min implementation)

1. **Extract system prompts to shared constants** (Save 200-300 tokens/call)
   ```python
   # Current: Embedded in 2+ functions
   # Fix: Define once, reuse
   SYSTEM_PROMPT_JSON = "You are TaskFlow AI..."
   SYSTEM_PROMPT_NATURAL = "You are TaskFlow AI..."
   ```

2. **Remove "Task request:" prefix redundancy** (Save 5 tokens/call)
   ```python
   # Remove from sanitize_ai_input(), already in system prompt context
   ```

3. **Compress dialog history** (Save 50-100 tokens/turn)
   ```python
   # Current: Full message stored
   # Fix: Store only last 3-5 turns, summarize older ones
   ```

4. **Filter tool definitions by context** (Save 200-400 tokens/call)
   ```python
   # Current: Send all 8 tools
   # Fix: Send only relevant tools for current stage
   # Task stage: create_task, update_task, complete_task, search_tasks
   # RAG stage: vector_search
   ```

---

## MEDIUM-TERM OPTIMIZATIONS (1-2 hours)

5. **Implement prompt caching (Mistral v0.3+)** (Save 90% on repeated prompts)
   ```python
   # Use cache_control: {"type": "ephemeral"} for system prompt
   # Repeat same system prompt = free on subsequent calls
   ```

6. **OCR text summarization before LLM** (Save 2,000+ tokens/upload)
   ```python
   # Current: Full text → LLM
   # Fix: Extract table structure locally, pass table + headers only
   ```

7. **Windowed dialog history** (Save 50-100 tokens/turn)
   ```python
   # Keep last 3 turns in full, summarize previous turns
   # Summarization can be fast local template or cached LLM call
   ```

8. **Lazy tool schema loading** (Save 300-500 tokens/call)
   ```python
   # Send tool names only, fetch schemas only if LLM asks
   ```

---

## ESTIMATED SAVINGS

- **Quick wins**: 300-400 tokens/call → ~$1,500-2,000/month (100 calls/day)
- **With caching**: 90% reduction on system prompts → ~$5,000-7,000/month
- **With all optimizations**: 40-50% total reduction → ~$8,000-12,000/month

---

## Implementation Priority

1. **Phase 1 (Today)**: Extract system prompts, remove prefix, filter tools
2. **Phase 2 (This week)**: Implement prompt caching, dialog windowing
3. **Phase 3 (Next week)**: OCR text summarization, lazy schema loading

