import os
os.environ['USE_SENTENCE_TRANSFORMERS'] = 'false'
os.environ['USE_REMOTE_EMBEDDING_API'] = 'false'
os.environ['DATABASE_URL'] = 'sqlite:///./test_prioritize.db'

import asyncio
import json

from backend_fastapi.models import Base, engine, SessionLocal, TaskModel
from backend_fastapi.mcp_server import MCPServer, MCPToolRegistry
from backend_fastapi.agents.agent_manager import AgentManager
from backend_fastapi.agents.agents import TaskAgent
from backend_fastapi.rag_tools import list_tasks, sort_tasks_by_time

# Prepare DB
Base.metadata.create_all(bind=engine)

# Seed tasks
db = SessionLocal()
try:
    db.query(TaskModel).delete()
    db.commit()
    tasks = []
    for i in range(1, 13):
        completed = True if i % 4 == 0 else False
        t = TaskModel(title=f'Task {i}', description=f'Description {i}', completed=completed)
        db.add(t)
        tasks.append(t)
    db.commit()
    for t in tasks:
        db.refresh(t)
    print('Seeded tasks with IDs:', [t.id for t in tasks])
finally:
    db.close()

# List pending tasks
db = SessionLocal()
try:
    pending = list_tasks(limit=100, offset=0, completed=False, db=db)
    print('\nPending tasks (unsorted):')
    print(json.dumps(pending, indent=2))

    # Prioritize
    prioritized = sort_tasks_by_time(limit=100, offset=0, completed=False, db=db)
    print('\nPrioritized pending tasks:')
    print(json.dumps(prioritized, indent=2))
finally:
    db.close()

# Setup MCP and Agent
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

async def run_flow():
    # Complete task ID 9
    task_id_to_complete = 9
    print(f"\nCompleting task {{task_id_to_complete}} via agent...")
    payload = {'operation': 'complete_task', 'task_id': task_id_to_complete, 'mcp_server': mcp}
    result = await agent_manager.execute_task('task_manager_001', payload)
    print('Complete result:')
    print(json.dumps(result, indent=2))

    # Verify
    db = SessionLocal()
    try:
        t9 = db.query(TaskModel).filter(TaskModel.id == task_id_to_complete).first()
        print('DB verification for task 9:', {'id': t9.id, 'completed': bool(t9.completed)})
    finally:
        db.close()

if __name__ == '__main__':
    asyncio.run(run_flow())
