import asyncio
import json

from backend_fastapi import state
from backend_fastapi.startup import startup_event

if __name__ == '__main__':
    import traceback
    try:
        print('Running startup_event...')
        startup_event()
        if not getattr(state, 'langraph_workflow', None):
            print('LangGraph workflow not initialized')
        else:
            print('Invoking LangGraph workflow: list all tasks')
            result = asyncio.run(state.langraph_workflow.execute_workflow(user_input='list all tasks', task_context={'user_id': 1, 'user_email': 'tester@example.com'}))
            print('Result:')
            print(json.dumps(result, indent=2))
    except Exception as e:
        print('Exception occurred:')
        traceback.print_exc()
