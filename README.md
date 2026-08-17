# Task Management App

A full-stack task management app with:

- Angular frontend
- Django REST backend for core task CRUD and auth
- FastAPI backend for AI assistant and vector search
- PostgreSQL database
- Docker Compose for local development

## Big Picture

The app works like this:

1. The user opens the Angular app in the browser.
2. Angular sends API requests to the backend.
3. Django handles normal task actions like create, update, delete, and login.
4. FastAPI handles AI features like semantic search, chat, and embeddings.
5. PostgreSQL stores users, tasks, roles, and vector documents.

In simple words, Angular is the screen, Django is the main task engine, FastAPI is the AI engine, and PostgreSQL is the memory.

## Overall Flow

### 1. User logs in

- The login page is in [frontend/src/app/login/login.component.ts](frontend/src/app/login/login.component.ts)
- After login, the app stores the auth state in the Angular signal store.
- The auth interceptor adds the token to future requests.

### 2. User manages normal tasks

- The task list page is in [frontend/src/app/task-list/task-list.component.ts](frontend/src/app/task-list/task-list.component.ts)
- The UI calls [frontend/src/app/app.service.ts](frontend/src/app/app.service.ts)
- Django APIs in [backend_django/tasks/views.py](backend_django/tasks/views.py) handle the real work
- Task data is defined in [backend_django/tasks/models.py](backend_django/tasks/models.py)
- Validation and JSON conversion are handled in [backend_django/tasks/serializers.py](backend_django/tasks/serializers.py)
- Reusable business rules live in [backend_django/tasks/services.py](backend_django/tasks/services.py)

### 3. User uses the AI assistant

- The AI chat screen is in [frontend/src/app/ai-chat/ai-chat.component.ts](frontend/src/app/ai-chat/ai-chat.component.ts)
- Semantic search is in [frontend/src/app/vector-search/vector-search.component.ts](frontend/src/app/vector-search/vector-search.component.ts)
- AI requests go through [frontend/src/app/ai.service.ts](frontend/src/app/ai.service.ts)
- FastAPI receives those requests in [backend_fastapi/main.py](backend_fastapi/main.py)
- Search ranking logic is in [backend_fastapi/rag_tools.py](backend_fastapi/rag_tools.py)
- Embeddings are created in [backend_fastapi/embeddings.py](backend_fastapi/embeddings.py)

### 4. Search and AI context

- When the user searches, the query is turned into an embedding.
- That embedding is compared with stored task documents in PostgreSQL.
- The backend returns the best matches with a similarity score.
- The AI chat also uses those matches as context when answering.

### 5. Save, update, or delete a task

- When a task is created or updated, the backend also refreshes the vector document.
- When a task is deleted, its vector document is removed too.
- This keeps normal CRUD and AI search in sync.

## How The AI Part Works

Here is the AI flow in very simple words:

1. You type a question in the AI chat.
2. The frontend sends that question to the FastAPI backend.
3. FastAPI first tries to understand what you want. It checks whether you want to search, list, get details, or ask about a due date.
4. If needed, FastAPI converts your question into an embedding. An embedding is just a long list of numbers that represents the meaning of the text.
5. The backend compares your question embedding with stored task embeddings in PostgreSQL.
6. The best matching tasks are returned as context.
7. If your question is about a specific task, the backend can also get the task details and read the due date from the title or description.
8. Then the AI model in Ollama gets the user question, the useful context, and any tool results.
9. Ollama writes the final answer in normal language.

### What Embeddings Do

- Embeddings help the app match by meaning, not only by exact words.
- For example, “project work” and “work task” can still be close in meaning.
- That is why the AI can find related tasks even when the exact words are different.

### What The Vector Search Does

- Every task is stored as a document with title, description, and embedding.
- When you search, the backend compares your question with those stored embeddings.
- The closest matches are returned first.
- This is called semantic search.

### What Ollama Does

- Ollama is the local AI model that writes the final reply.
- It does not just guess from memory.
- It gets the question plus the task context from the backend.
- Then it formats a helpful answer in simple language.

### Example

If you ask:

> When to complete review and edit work task?

The AI flow is:

- find the task that matches the words and meaning
- read the due date from the task description
- answer with the date in plain English

So the AI part is not only chatting. It is also searching, reading task data, and then writing the answer for you.

## Important Code, Explained Simply

### Frontend

- [frontend/src/app/app.module.ts](frontend/src/app/app.module.ts): wires the app together
- [frontend/src/app/app.service.ts](frontend/src/app/app.service.ts): talks to the APIs
- [frontend/src/app/auth.interceptor.ts](frontend/src/app/auth.interceptor.ts): adds login token to requests
- [frontend/src/app/csrf.interceptor.ts](frontend/src/app/csrf.interceptor.ts): adds CSRF protection
- [frontend/src/app/task-list/task-list.component.ts](frontend/src/app/task-list/task-list.component.ts): shows and edits tasks
- [frontend/src/app/ai-chat/ai-chat.component.ts](frontend/src/app/ai-chat/ai-chat.component.ts): AI assistant chat UI
- [frontend/src/app/vector-search/vector-search.component.ts](frontend/src/app/vector-search/vector-search.component.ts): semantic task search UI

### Django backend

- [backend_django/tasks/models.py](backend_django/tasks/models.py): defines the task table
- [backend_django/tasks/views.py](backend_django/tasks/views.py): handles HTTP requests for tasks
- [backend_django/tasks/serializers.py](backend_django/tasks/serializers.py): checks input and formats output
- [backend_django/tasks/services.py](backend_django/tasks/services.py): contains shared task logic
- [backend_django/tasks/auth_views.py](backend_django/tasks/auth_views.py): handles authentication

### FastAPI AI backend

- [backend_fastapi/main.py](backend_fastapi/main.py): main AI API entry point
- [backend_fastapi/rag_tools.py](backend_fastapi/rag_tools.py): finds matching tasks for AI search
- [backend_fastapi/embeddings.py](backend_fastapi/embeddings.py): turns text into vectors for search
- [backend_fastapi/ollama_client.py](backend_fastapi/ollama_client.py): talks to Ollama for AI responses

## Why There Are Two Backends

- Django is used for the main task app and authentication flow.
- FastAPI is used for AI assistant features because it is easier to keep the AI and vector search logic separate.
- Both use the same PostgreSQL database.

## Database Tables

- `users`: stores user accounts
- `roles`: stores role names like admin and employee
- `user_roles`: connects users to roles
- `tasks`: stores task records
- `documents`: stores embedded task text for vector search

## Docker Setup

Two Compose files are available:

- `docker-compose.yml`: Django-based stack
- `docker-compose.fastapi.yml`: FastAPI AI stack

## Run Locally

To start the FastAPI stack:

```bash
docker compose -f docker-compose.fastapi.yml up --build
```

To start the Django stack:

```bash
docker compose up --build
```

Then open:

- Frontend: `http://localhost:4200`
- Django API: `http://localhost:8000`
- FastAPI AI API: `http://localhost:8000` when running the FastAPI stack

## Short Presentation Version

If you need a simple explanation for a trainer, say this:

"The frontend is built with Angular. Normal task operations go to Django, which checks the data and stores it in PostgreSQL. AI search and assistant features go to FastAPI, which converts task text into embeddings and finds similar tasks by meaning. When a task changes, the vector document is updated too, so the AI search stays in sync with the real task list."
