"""
Multi-Agent System Guide

This document describes the multi-agent system architecture implemented in the project.
"""

# Multi-Agent System Architecture

## Overview

The project now includes a multi-agent system that enables specialized agents to handle different tasks:

- **Task Manager Agent**: Manages task creation, updates, tracking, and completion
- **Chat Agent**: Handles conversational AI and chat operations
- **RAG Agent**: Manages Retrieval-Augmented Generation and semantic search
- **Analysis Agent**: Performs data analysis and generates insights

## Agent Types

### 1. Task Manager Agent
**ID**: `task_manager_001`
**Role**: TASK_MANAGER

Responsibilities:
- Create and manage tasks
- Track task status
- Update task information
- Generate task analytics

Example operations:
```python
{
    "agent_id": "task_manager_001",
    "operation": "list_tasks",
    "params": {}
}
```

### 2. Chat Agent
**ID**: `chat_agent_001`
**Role**: CHAT_AGENT

Responsibilities:
- Process conversational messages
- Maintain chat context
- Generate responses
- Manage conversation history

Example operations:
```python
{
    "agent_id": "chat_agent_001",
    "operation": "send_message",
    "params": {"text": "Hello, how can I help?"}
}
```

### 3. RAG Agent
**ID**: `rag_agent_001`
**Role**: RAG_AGENT

Responsibilities:
- Semantic search on document corpus
- Index documents for retrieval
- Generate embeddings
- Manage knowledge base

Example operations:
```python
{
    "agent_id": "rag_agent_001",
    "operation": "search",
    "params": {"query": "What is the project status?"}
}
```

### 4. Analysis Agent
**ID**: `analyzer_001`
**Role**: ANALYZER

Responsibilities:
- Analyze data sets
- Generate insights and reports
- Identify patterns
- Provide recommendations

Example operations:
```python
{
    "agent_id": "analyzer_001",
    "operation": "analyze_data",
    "params": {"data": [...]}
}
```

## API Endpoints

### System Status
```
GET /api/agents/system/status

Response:
{
    "total_agents": 4,
    "agents_by_role": {
        "task_manager": 1,
        "chat_agent": 1,
        "rag_agent": 1,
        "analyzer": 1
    },
    "agents": [...],
    "message_history_size": 150
}
```

### List All Agents
```
GET /api/agents/agents

Response:
[
    {
        "agent_id": "task_manager_001",
        "role": "task_manager",
        "name": "Task Manager",
        "status": "idle"
    },
    ...
]
```

### Get Specific Agent
```
GET /api/agents/agents/{agent_id}

Response:
{
    "agent_id": "chat_agent_001",
    "role": "chat_agent",
    "name": "Chat Agent",
    "status": "idle"
}
```

### Get Agents by Role
```
GET /api/agents/agents/role/{role}

Example: GET /api/agents/agents/role/task_manager

Response:
[
    {
        "agent_id": "task_manager_001",
        "role": "task_manager",
        "name": "Task Manager",
        "status": "idle"
    }
]
```

### Execute Task on Agent
```
POST /api/agents/execute

Request:
{
    "agent_id": "task_manager_001",
    "operation": "list_tasks",
    "params": {}
}

Response:
{
    "status": "success",
    "data": {...}
}
```

### Message History
```
GET /api/agents/message-history?limit=100

Response:
{
    "limit": 100,
    "messages": [
        {
            "sender": "task_manager_001",
            "recipient": "chat_agent_001",
            "type": "task_request",
            "timestamp": "2026-06-19T10:00:00Z"
        },
        ...
    ]
}
```

## Agent Lifecycle

1. **Registration**: Agent is registered with the AgentManager on startup
2. **Idle**: Agent waits for messages or task requests
3. **Processing**: Agent is actively executing a task or processing a message
4. **Response**: Agent sends response back to requester
5. **Error**: Agent encountered an error (optional state)

## Inter-Agent Communication

Agents can communicate via messages:

```python
message = AgentMessage(
    sender_id="agent_001",
    recipient_id="agent_002",
    message_type="task_request",
    content={"task": "data", ...}
)

response = await agent_manager.send_message(message)
```

## Adding New Agents

To add a new agent:

1. **Create Agent Class** (in `agents/agents.py`):
```python
class MyCustomAgent(Agent):
    def __init__(self):
        super().__init__(
            agent_id="custom_agent_001",
            role=AgentRole.YOUR_ROLE,
            name="My Custom Agent",
            description="Does something useful"
        )
    
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        # Implement task execution
        pass
    
    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        # Implement message handling
        pass
```

2. **Register in Startup** (in `main.py`):
```python
agent_manager.register_agent(MyCustomAgent())
```

3. **Use via API**:
```bash
curl -X POST http://localhost:8000/api/agents/execute \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "custom_agent_001",
    "operation": "your_operation",
    "params": {...}
  }'
```

## Configuration

### Environment Variables
- `AGENTS_MAX_HISTORY`: Maximum messages to keep in history (default: 1000)
- `AGENTS_TIMEOUT`: Task execution timeout in seconds (default: 60)

### Agent Manager Settings
```python
manager = AgentManager()
manager.max_history = 2000  # Increase message history
```

## Best Practices

1. **Error Handling**: Always return status and error message in responses
2. **Logging**: Use the logger for debugging: `self.logger.info("message")`
3. **Status Updates**: Update agent status during long operations
4. **Message Types**: Use consistent message type naming (e.g., "task_request", "search_query")
5. **Timeouts**: Implement reasonable timeouts for agent operations
6. **Async Operations**: Use async/await for I/O operations

## Troubleshooting

### Agent Not Found
- Check agent_id spelling
- Verify agent is registered in startup
- Check system status to see all available agents

### Timeout Errors
- Agent is taking too long to respond
- Increase timeout setting
- Check agent logs for errors

### Message Queue Overflow
- Too many messages are being generated
- Reduce message history limit
- Implement message filtering

## Future Enhancements

- [ ] Agent persistence (save/load agent state)
- [ ] Dynamic agent creation/destruction
- [ ] Agent resource limits (CPU, memory)
- [ ] Inter-agent learning and optimization
- [ ] Agent clustering for distributed processing
- [ ] Web UI for agent monitoring and control
- [ ] Agent performance metrics and analytics
