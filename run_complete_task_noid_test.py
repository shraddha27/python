import os
os.environ['USE_SENTENCE_TRANSFORMERS'] = 'false'
os.environ['USE_REMOTE_EMBEDDING_API'] = 'false'
os.environ['DATABASE_URL'] = 'sqlite:///./test_complete_noid.db'

import asyncio
import json

from backend_fastapi.models import Base, engine, SessionLocal, TaskModel
from backend_fastapi.mcp_server import MCPServer, MCPToolRegistry
from backend_fastapi.agents.agent_manager import AgentManager
from backend_fastapi.agents.agents import TaskAgent

# Prepare DB
Base.metadata.create_all(bind=engine)

# Seed tasks
db = SessionLocal()
try:
    db.query(TaskModel).delete()
    db.commit()
    tasks = []
    for i in range(1, 11):
        t = TaskModel(title=f'Task {i}', description=f'Description {i}', completed=False)
        db.add(t)
        tasks.append(t)
    db.commit()
    for t in tasks:
        db.refresh(t)
    print('Seeded tasks with IDs:', [t.id for t in tasks])
finally:
    db.close()

# Setup agents and MCP
agent_manager = AgentManager()
agent_manager.register_agent(TaskAgent())

mcp = MCPServer()

async def complete_task_handler(task_id: int):
    db = SessionLocal()
    try:
        from backend_fastapi.rag_tools import complete_task as ct
        return ct(task_id=task_id, db=db)
    finally:
        db.close()

complete_def = MCPToolRegistry.complete_task_tool()
mcp.register_tool(name=complete_def['name'], description=complete_def['description'], parameters=complete_def['parameters'], handler=complete_task_handler)

async def run_test():
    # Call agent with only user_input (LangGraph style)
    payload = {
        'operation': 'complete_task',
        'user_input': 'complete task 9',
        'mcp_server': mcp,
    }
    print('Calling TaskAgent to complete task 9 via user_input only')
    result = await agent_manager.execute_task('task_manager_001', payload)
    print('Agent result:')
    print(json.dumps(result, indent=2))

    # Verify DB
    db = SessionLocal()
    try:
        t9 = db.query(TaskModel).filter(TaskModel.id == 9).first()
        print('DB check for task 9:', {'id': t9.id, 'completed': bool(t9.completed)})
    finally:
        db.close()

if __name__ == '__main__':
    asyncio.run(run_test())
