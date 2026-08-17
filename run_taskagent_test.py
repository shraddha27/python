import os
os.environ['USE_SENTENCE_TRANSFORMERS'] = 'false'
os.environ['USE_REMOTE_EMBEDDING_API'] = 'false'
os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

import asyncio
import json

from backend_fastapi import models
from backend_fastapi.models import Base, engine, SessionLocal, TaskModel
from backend_fastapi.mcp_server import MCPServer, MCPToolRegistry, ToolCallRequest
from backend_fastapi.agents.agent_manager import AgentManager
from backend_fastapi.agents.agents import TaskAgent
from backend_fastapi.rag_tools import list_tasks

# Prepare DB
Base.metadata.create_all(bind=engine)

# Seed tasks
db = SessionLocal()
try:
    # Clear any existing tasks
    db.query(TaskModel).delete()
    db.commit()
    # Add sample tasks
    t1 = TaskModel(title='Buy groceries', description='Milk, eggs, bread', completed=False)
    t2 = TaskModel(title='Finish report', description='Complete the Q2 report', completed=True)
    db.add_all([t1, t2])
    db.commit()
finally:
    db.close()

# Setup agents and MCP
agent_manager = AgentManager()
agent_manager.register_agent(TaskAgent())

mcp = MCPServer()

async def list_tasks_handler(limit: int = 100, offset: int = 0, completed: bool = None):
    db = SessionLocal()
    try:
        return list_tasks(limit=limit, offset=offset, completed=completed, db=db)
    finally:
        db.close()

list_def = MCPToolRegistry.list_tasks_tool()
mcp.register_tool(name=list_def['name'], description=list_def['description'], parameters=list_def['parameters'], handler=list_tasks_handler)

# Execute TaskAgent list_tasks operation
async def run_test():
    payload = {
        'operation': 'list_tasks',
        'user_input': 'list all tasks',
        'mcp_server': mcp,
    }
    result = await agent_manager.execute_task('task_manager_001', payload)
    print('Agent result:')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    asyncio.run(run_test())
