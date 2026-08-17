# Project Explanation Guide - Django + FastAPI + Angular

## 📋 Overview

This is a **Task Management Application** with:

- **Frontend**: Angular (TypeScript) - The user interface where users interact
- **Backend**: Django REST Framework - Main backend serving the frontend (Port 8000)
- **Alternative Backend**: FastAPI - Reference implementation (Port 8001)
- **Database**: PostgreSQL - Stores all data
- **Authentication**: Google OAuth2 - Users login with Google

---

## 🏗️ Project Structure

```
project/
├── backend/                    # Django REST Framework
│   ├── manage.py              # Django commands tool
│   ├── requirements.txt        # Python packages needed
│   ├── Dockerfile             # Docker setup for Django
│   ├── backend/               # Django configuration folder
│   │   ├── settings.py        # Django configuration
│   │   ├── urls.py            # Main URL routing
│   │   ├── asgi.py            # Web server entry point
│   │   └── wsgi.py            # Another web server format
│   └── tasks/                 # Task management app
│       ├── models.py          # Database table definitions
│       ├── views.py           # API endpoints logic
│       ├── serializers.py     # Convert Python→JSON and vice versa
│       ├── urls.py            # Task URLs
│       ├── auth_views.py      # Google login endpoints
│       ├── services.py        # Business logic (create, update tasks)
│       └── migrations/        # Database schema changes
│
├── backend_fastapi/           # FastAPI (alternative backend)
│   ├── main.py               # Entire app in one file
│   ├── requirements.txt       # Python packages
│   └── Dockerfile            # Docker setup
│
├── frontend/                  # Angular web app
│   ├── package.json          # JavaScript packages needed
│   ├── Dockerfile            # Docker setup + Nginx
│   ├── src/
│   │   ├── index.html        # Main HTML file
│   │   ├── main.ts           # Angular startup
│   │   ├── app/
│   │   │   ├── app.module.ts        # Angular modules
│   │   │   ├── app.service.ts       # HTTP communication with backend
│   │   │   ├── app.component.ts     # Main page component
│   │   │   ├── auth.interceptor.ts  # Add token to requests
│   │   │   ├── task.model.ts        # TypeScript Task interface
│   │   │   ├── login/               # Login page
│   │   │   │   └── login.component.ts
│   │   │   ├── task-list/           # Task list page
│   │   │   │   ├── task-list.component.ts
│   │   │   │   └── task-list.component.html
│   │   │   └── store/               # State management (NgRx)
│   │   │       └── auth.signal-store.ts  # User login state
│   │   └── environments/
│   │       ├── environment.ts       # Local development settings
│   │       └── environment.prod.ts  # Production settings
│   └── nginx.conf             # Web server configuration
│
├── docker-compose.yml         # Django + Frontend + PostgreSQL
├── docker-compose.fastapi.yml # FastAPI + Frontend + PostgreSQL
└── README.md                  # Project documentation
```

---

## 🗄️ Database Schema

### Tables Overview:

```
┌─────────────┐          ┌──────────────┐          ┌───────┐
│   users     │          │  user_roles  │          │ roles │
├─────────────┤          ├──────────────┤          ├───────┤
│ id (PK)     │◄──────►  │ user_id (FK) │ ◄──────► │ id    │
│ email       │          │ role_id (FK) │          │ name  │
│ name        │          └──────────────┘          └───────┘
│ google_id   │
└─────────────┘

┌──────────────┐
│   tasks      │
├──────────────┤
│ id (PK)      │
│ title        │
│ description  │
│ completed    │
│ created_at   │
└──────────────┘
```

### Tables Explained:

| Table          | Purpose                        | Fields                                        |
| -------------- | ------------------------------ | --------------------------------------------- |
| **users**      | Stores user information        | id, email, name, google_id                    |
| **roles**      | Role types (admin, employee)   | id, name                                      |
| **user_roles** | Maps which user has which role | user_id, role_id                              |
| **tasks**      | Todo items                     | id, title, description, completed, created_at |

---

# 🚀 Step-by-Step Explanation

## **PART 1: DJANGO BACKEND**

### **1. django/backend/settings.py** - Configuration File

**What it does**: Tells Django how to work

**Key Parts**:

```python
# Database connection
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'postgres',
        'USER': 'postgres',
        'PASSWORD': 'root',
        'HOST': 'db',  # PostgreSQL container name
        'PORT': '5432',
    }
}

# Allowed frontend URLs
CORS_ALLOWED_ORIGINS = [
    "http://localhost:4200",  # Angular dev server
]

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100
}
```

**In Simple Words**: This is like the recipe book for Django - it says "use PostgreSQL database", "allow requests from Angular", "format responses as JSON"

### **2. django/backend/urls.py** - Main Router

**What it does**: Directs incoming requests to the right place

```python
urlpatterns = [
    path("api/", include("tasks.urls")),  # Forward /api/* to tasks app
    path("api/auth/google/", google_login),  # /api/auth/google/ → login function
    path("api/auth/me/", get_current_user),  # /api/auth/me/ → get user info
]
```

**In Simple Words**: Like a receptionist - when request comes with URL, it says "this goes to the tasks handler", "this goes to login handler"

### **3. django/tasks/models.py** - Database Tables

**What it does**: Defines what data is stored

```python
class Task(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(default="")
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
```

**In Simple Words**: Tells Django "create a table called Task with these columns: title, description, completed, created_at"

### **4. django/tasks/serializers.py** - JSON Converter

**What it does**: Converts Python objects ↔ JSON

```python
class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ['id', 'title', 'description', 'completed', 'created_at']
```

**In Simple Words**:

- When database returns Python Task object → Serializer converts to JSON to send to frontend
- When Angular sends JSON → Serializer converts to Python to save in database

Example:

```python
# Python object
task = Task(title="Buy milk", completed=False)

# Serializer converts to JSON
{
    "id": 1,
    "title": "Buy milk",
    "description": "",
    "completed": false,
    "created_at": "2026-06-10T10:30:00Z"
}
```

### **5. django/tasks/views.py** - API Endpoints

**What it does**: Handles HTTP requests and returns responses

```python
class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer

    def list(self, request):
        """GET /api/tasks/ - Return all tasks"""
        tasks = Task.objects.all()
        serializer = TaskSerializer(tasks, many=True)
        return Response({'data': serializer.data, 'success': True})

    def create(self, request):
        """POST /api/tasks/ - Create new task"""
        serializer = TaskSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({'data': serializer.data, 'success': True},
                          status=201)
        return Response({'errors': serializer.errors}, status=400)
```

**In Simple Words**:

- `list()` = "Show me all tasks" → Returns all tasks
- `create()` = "Add a new task" → Saves new task and returns it
- `update()` = "Change this task" → Updates and returns
- `destroy()` = "Delete this task" → Removes it

### **6. django/tasks/services.py** - Business Logic

**What it does**: Complex operations that multiple views might use

```python
class TaskService:
    @staticmethod
    def get_task_stats():
        """Calculate statistics: total, completed, pending"""
        total = Task.objects.count()
        completed = Task.objects.filter(completed=True).count()
        pending = total - completed

        return {
            'total': total,
            'completed': completed,
            'pending': pending,
            'completion_percentage': (completed / total * 100) if total > 0 else 0
        }
```

**In Simple Words**: Instead of writing stats code in multiple places, write it once here and reuse

### **7. django/tasks/auth_views.py** - Authentication

**What it does**: Handles Google login and user sessions

```python
def google_login(request):
    """User clicks 'Login with Google'"""
    id_token = request.data.get("id_token")  # Token from Google

    # Decode token to get user email
    decoded = jwt.decode(id_token, ...)
    email = decoded.get("email")

    # Create or get user in database
    user, created = User.objects.get_or_create(
        email=email,
        defaults={"username": email, "first_name": decoded.get("name")}
    )

    # Assign default "employee" role if new user
    if not user.roles.exists():
        ensure_user_role(user.id, "employee")

    # Create session token
    access_token = create_access_token(user.id)

    return Response({
        'access_token': access_token,
        'user': {
            'id': user.id,
            'email': user.email,
            'roles': get_user_roles(user)
        }
    })
```

**In Simple Words**:

1. User clicks "Login with Google"
2. Google sends a token to prove identity
3. We decode the token to get email
4. Check if user exists in DB, if not create them
5. Assign them a default role (employee)
6. Send back a token they use for future requests

### **8. django/tasks/urls.py** - Task URLs

```python
router = DefaultRouter()
router.register(r"tasks", TaskViewSet)

urlpatterns = [
    path("", include(router.urls)),  # /api/tasks/, /api/tasks/{id}/, etc.
    path("auth/google/", google_login),  # /api/auth/google/
    path("auth/me/", get_current_user),  # /api/auth/me/
]
```

**In Simple Words**: Maps URLs to their handlers

- `/api/tasks/` → list, create
- `/api/tasks/{id}/` → get, update, delete
- `/api/auth/google/` → login
- `/api/auth/me/` → get current user info

---

## **PART 2: FASTAPI BACKEND**

### **backend_fastapi/main.py** - Complete FastAPI App

FastAPI puts everything in one file (unlike Django which spreads it).

```python
# 1. DATABASE MODELS
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True)
    name = Column(String(255))
    roles = relationship("UserRole", back_populates="user")

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True)  # "admin" or "employee"

class UserRole(Base):
    __tablename__ = "user_roles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    description = Column(Text, default="")
    completed = Column(Boolean, default=False)

# 2. PYDANTIC SCHEMAS (like Django Serializers)
class TaskSchema(BaseModel):
    id: int
    title: str
    description: str = ""
    completed: bool = False

    class Config:
        from_attributes = True  # Convert SQLAlchemy → Pydantic

# 3. ENDPOINTS (like Django views)
@app.get("/tasks/")
def get_tasks(db: Session = Depends(get_db)):
    """Get all tasks"""
    tasks = db.query(Task).all()
    return {"data": tasks, "success": True}

@app.post("/tasks/")
def create_task(task: TaskSchema, db: Session = Depends(get_db)):
    """Create new task"""
    db_task = Task(**task.dict())
    db.add(db_task)
    db.commit()
    return {"data": db_task, "success": True}
```

**In Simple Words**: FastAPI is like Django but:

- Simpler syntax
- Everything in one file instead of spread across files
- Uses Pydantic instead of DRF serializers
- Faster performance

---

## **PART 3: ANGULAR FRONTEND**

### **1. frontend/src/environments/environment.ts** - Configuration

```typescript
export const environment = {
  apiUrl: "http://localhost:8000/api", // Django backend URL
  production: false,
};
```

**In Simple Words**: Says "talk to http://localhost:8000/api to get data"

### **2. frontend/src/app/app.service.ts** - HTTP Communication

**What it does**: Talks to the Django backend

```typescript
@Injectable({
  providedIn: "root",
})
export class AppService {
  private apiUrl = `${environment.apiUrl}/tasks/`;

  constructor(private http: HttpClient) {}

  // Get all tasks
  getTasks(): Observable<Task[]> {
    return this.http.get<ApiResponse<Task[]>>(this.apiUrl).pipe(
      map((response) => response.data as Task[]), // Extract data from response
      catchError(this.handleError),
    );
  }

  // Add new task
  addTask(task: Partial<Task>): Observable<Task> {
    return this.http.post<ApiResponse<Task>>(this.apiUrl, task).pipe(
      map((response) => response.data as Task),
      catchError(this.handleError),
    );
  }

  // Google login
  googleLogin(idToken: string): Observable<any> {
    return this.http
      .post<any>(`${this.apiUrl}auth/google/`, { id_token: idToken })
      .pipe(catchError(this.handleError));
  }
}
```

**In Simple Words**:

- `getTasks()`: Makes HTTP GET request to `/api/tasks/`
- `addTask()`: Makes HTTP POST request to `/api/tasks/` with task data
- `googleLogin()`: Sends Google token to `/api/auth/google/`

### **3. frontend/src/app/task.model.ts** - TypeScript Types

```typescript
export interface Task {
  id: number;
  title: string;
  description: string;
  completed: boolean;
  created_at: string; // ISO date format
}

export interface ApiResponse<T> {
  data: T;
  success: boolean;
}
```

**In Simple Words**: Defines what a Task object looks like in TypeScript

### **4. frontend/src/app/store/auth.signal-store.ts** - State Management

**What it does**: Stores user login info globally

```typescript
@Injectable({
  providedIn: 'root',
})
export class AuthStore extends signalStore(
  withState(initialState),
  withComputed(({ user }) => ({
    isAdmin: computed(
      () => user()?.roles?.some((r) => r.name?.toLowerCase() === 'admin') ?? false
    ),
    isEmployee: computed(
      () => user()?.roles?.some((r) => r.name?.toLowerCase() === 'employee') ?? false
    ),
  })),
  withMethods((store) => ({
    googleLogin: (idToken: string, appService: AppService) => {
      appService.googleLogin(idToken).subscribe({
        next: (response: any) => {
          patchState(store, {
            user: response.user,
            token: response.access_token,
          });
          localStorage.setItem('auth_token', response.access_token);
        },
      });
    },

    getCurrentUser: (appService: AppService) => {
      appService.getCurrentUser().subscribe({
        next: (user: AuthUser) => {
          patchState(store, { user });
          localStorage.setItem('auth_user', JSON.stringify(user));
        },
      });
    },
  }))
)
```

**In Simple Words**:

- Stores logged-in user info globally
- `isAdmin()` → checks if user has admin role
- `googleLogin()` → saves token and user after login
- Other components can access this anywhere

### **5. frontend/src/app/login/login.component.ts** - Login Page

**What it does**: Handles Google login button

```typescript
@Component({
  selector: "app-login",
  templateUrl: "./login.component.html",
})
export class LoginComponent {
  private authStore = inject(AuthStore);

  googleLogin() {
    // Trigger Google authentication
    // When user approves, Google sends id_token
    // Pass it to store which saves user globally

    google.accounts.id.initialize({
      client_id: "YOUR_CLIENT_ID",
    });

    google.accounts.id.renderButton(
      document.getElementById("googleSignInButton"),
      { theme: "outline" },
    );
  }

  handleCredentialResponse(response: CredentialResponse) {
    // response.credential = Google token
    this.authStore.googleLogin(response.credential, this.appService);
    this.router.navigate(["/tasks"]); // Go to task list
  }
}
```

**In Simple Words**:

1. Show "Login with Google" button
2. User clicks it
3. Google popup appears
4. User approves
5. Google sends token to us
6. We send token to Django backend
7. Backend returns user info
8. We save it and show task list

### **6. frontend/src/app/task-list/task-list.component.ts** - Main App

**What it does**: Shows tasks and handles create/update/delete

```typescript
@Component({
  selector: "app-task-list",
  templateUrl: "./task-list.component.html",
})
export class TaskListComponent implements OnInit {
  tasks: Task[] = [];
  newTitle = "";
  loading = false;

  private service = inject(AppService);
  authStore = inject(AuthStore);

  ngOnInit() {
    this.loadTasks();
  }

  loadTasks() {
    this.loading = true;
    this.service.getTasks().subscribe({
      next: (tasks) => {
        this.tasks = tasks; // Save tasks for display
        this.loading = false;
      },
      error: (error) => {
        console.error("Failed to load tasks", error);
        this.loading = false;
      },
    });
  }

  createTask() {
    if (!this.newTitle.trim()) return;

    this.loading = true;
    this.service
      .addTask({
        title: this.newTitle,
        description: "",
      })
      .subscribe({
        next: () => {
          this.newTitle = "";
          this.loadTasks(); // Reload to see new task
        },
        error: (error) => {
          console.error("Failed to create task", error);
          this.loading = false;
        },
      });
  }

  toggleCompletion(task: Task) {
    this.service
      .updateTask({
        ...task,
        completed: !task.completed,
      })
      .subscribe({
        next: () => this.loadTasks(),
      });
  }
}
```

**In Simple Words**:

1. When page loads → `loadTasks()` → fetch all tasks from Django
2. Display tasks in HTML
3. When user clicks "Create" → `createTask()` → send to Django → reload list
4. When user clicks "Complete" → toggle completion → send to Django

### **7. frontend/src/app/task-list/task-list.component.html** - Task List UI

```html
<!-- Admin-only: Form to create task -->
<form *ngIf="authStore.isAdmin()" (submit)="createTask()">
  <input [(ngModel)]="newTitle" placeholder="Task title" />
  <button [disabled]="loading">{{ loading ? "Adding..." : "Add Task" }}</button>
</form>

<!-- Show all tasks -->
<div *ngFor="let task of tasks" class="task-card">
  <h3>{{ task.title }}</h3>
  <p>{{ task.description }}</p>

  <!-- All users can complete/reopen -->
  <button (click)="toggleCompletion(task)">
    {{ task.completed ? "Reopen" : "Complete" }}
  </button>

  <!-- Only admin can delete -->
  <button *ngIf="authStore.isAdmin()" (click)="deleteTask(task.id)">
    Delete
  </button>
</div>
```

**In Simple Words**: HTML that displays tasks and buttons

### **8. frontend/src/app/auth.interceptor.ts** - Add Token to Requests

```typescript
@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  constructor(private appService: AppService) {}

  intercept(
    request: HttpRequest,
    next: HttpHandler,
  ): Observable<HttpEvent<unknown>> {
    const token = this.appService.getAuthToken();

    if (token) {
      // Add Authorization header to every request
      request = request.clone({
        setHeaders: {
          Authorization: `Bearer ${token}`, // Django checks this
        },
      });
    }

    return next.handle(request);
  }
}
```

**In Simple Words**: Automatically adds login token to every request sent to Django

---

## **PART 4: How It All Works Together**

### **Scenario: User Login & Create Task**

```
┌─────────────────────────────────────────────────────────────┐
│  STEP 1: User clicks "Login with Google"                    │
└─────────────────────────────────────────────────────────────┘
  Frontend (Angular)          →    Google OAuth
  User approves
                              ←    Google sends token

┌─────────────────────────────────────────────────────────────┐
│  STEP 2: Frontend sends token to Django                      │
└─────────────────────────────────────────────────────────────┘
  POST /api/auth/google/
  { id_token: "xxx.yyy.zzz" }
                              →    Django Backend
                                   (auth_views.py)
                                   ├─ Decode token
                                   ├─ Get email from token
                                   ├─ Look for user in DB
                                   │  (if not found, create user)
                                   ├─ Get user's roles from DB
                                   └─ Create JWT token
                              ←    {
                                     access_token: "abc123",
                                     user: {
                                       id: 1,
                                       email: "user@gmail.com",
                                       roles: [{name: "employee"}]
                                     }
                                   }

┌─────────────────────────────────────────────────────────────┐
│  STEP 3: Frontend saves token and shows task list            │
└─────────────────────────────────────────────────────────────┘
  AuthStore saves token to localStorage
  Redirect to /tasks page

┌─────────────────────────────────────────────────────────────┐
│  STEP 4: Load tasks                                          │
└─────────────────────────────────────────────────────────────┘
  GET /api/tasks/
  (with Authorization header: "Bearer abc123")
                              →    Django checks token
                                   (auth_interceptor.py verifies)
                                   ├─ Decode token to get user_id
                                   └─ Query all tasks
                              ←    {
                                     data: [
                                       {id: 1, title: "Buy milk", completed: false},
                                       {id: 2, title: "Study", completed: false}
                                     ],
                                     success: true
                                   }

┌─────────────────────────────────────────────────────────────┐
│  STEP 5: Create new task (Admin only)                       │
└─────────────────────────────────────────────────────────────┘
  User clicks "Add Task"

  POST /api/tasks/
  {
    title: "Complete project",
    description: "Finish the Django app"
  }
  (with Authorization header)
                              →    Django
                                   ├─ Verify user is admin
                                   ├─ Create Task in DB
                                   └─ Return new task
                              ←    {
                                     data: {
                                       id: 3,
                                       title: "Complete project",
                                       completed: false,
                                       created_at: "2026-06-10T10:00:00Z"
                                     },
                                     success: true
                                   }

  Frontend reloads task list, shows new task
```

---

## **PART 5: Key Concepts Explained Simply**

### **Roles & Permissions**

```
Database:
┌─────────────────────┐
│ User: john@gmail    │  ──┐
└─────────────────────┘    │
                           ├─→ user_roles.user_id=1, role_id=2
┌─────────────────────┐    │
│ Role: admin (id=2)  │  ──┘
└─────────────────────┘

Result: john@gmail has admin role

In Frontend:
authStore.isAdmin()  → Checks john's roles → returns true
                    → Shows "Create Task" button
                    → Shows "Delete" buttons

In Backend:
@permission_classes([IsAdminUser])  → Only admins can access
OR
if not user.is_admin: return error
```

**In Simple Words**: Roles are like job titles:

- Admin = can create and delete tasks
- Employee = can only complete tasks

### **JWT Tokens**

```
Timeline:
1. User logs in
   → Backend creates JWT: "eyJhbGc.eyJzdWI.SflKxw"
   → Frontend saves to localStorage

2. User makes request
   → Frontend adds header: Authorization: Bearer eyJhbGc.eyJzdWI.SflKxw
   → Backend receives request
   → Backend decodes token (checks signature is valid)
   → Backend extracts user_id from token
   → Backend verifies user exists in DB
   → ✓ Request approved

3. Token expires (after 7 days)
   → User needs to login again
```

**In Simple Words**: Token = proof of identity that backend trusts

### **Request Flow With Code**

**Frontend TypeScript**:

```typescript
// 1. Send request
this.http.get("/api/tasks/").subscribe((response) => {
  // 4. Receive response
  console.log(response.data); // Array of tasks
});

// Behind the scenes:
// 2. Interceptor adds token
// Headers: { Authorization: "Bearer token123" }
```

**Backend Python** (Django):

```python
# 3. Receive request
@api_view(['GET'])
def get_tasks(request):
    # Check token in Authorization header
    token = request.META.get('HTTP_AUTHORIZATION')  # "Bearer token123"

    # Verify token is valid
    user_id = jwt.decode(token, SECRET_KEY)

    # Get tasks from database
    tasks = Task.objects.all()

    # Convert to JSON
    serializer = TaskSerializer(tasks, many=True)

    # Return response
    return Response({
        'data': serializer.data,
        'success': True
    })
```

---

## **PART 6: File-by-File Checklist**

### **Django Backend Files**

| File             | Purpose         | Analogy        |
| ---------------- | --------------- | -------------- |
| `settings.py`    | Configuration   | Recipe book    |
| `urls.py`        | Route requests  | Reception desk |
| `models.py`      | Database schema | Blueprint      |
| `serializers.py` | Python ↔ JSON   | Translator     |
| `views.py`       | Handle requests | Kitchen        |
| `services.py`    | Reusable logic  | Recipe         |
| `auth_views.py`  | Login handling  | Security       |

### **Angular Frontend Files**

| File                       | Purpose          | Analogy  |
| -------------------------- | ---------------- | -------- |
| `app.service.ts`           | Talk to backend  | Phone    |
| `task.model.ts`            | TypeScript types | Label    |
| `auth.signal-store.ts`     | User state       | Memory   |
| `login.component.ts`       | Login page       | Entrance |
| `task-list.component.ts`   | Main page logic  | Brain    |
| `task-list.component.html` | UI display       | Screen   |
| `auth.interceptor.ts`      | Add token        | Stamp    |

---

## **🎓 Teaching Summary**

When explaining to your trainer, structure it like this:

1. **Start with the database**: "Tables store users, roles, and tasks"
2. **Explain Django**: "Backend receives requests, talks to DB, returns JSON"
3. **Explain Frontend**: "Angular shows UI, sends requests to Django"
4. **Explain authentication**: "User logs in with Google, gets token, uses token for future requests"
5. **Explain roles**: "Tokens include user info, backend checks roles to decide what user can do"
6. **Explain the flow**: "User → Google → Django → Database → Django → Angular → User"

---

## **Common Questions & Answers**

### **Q: Why two backends (Django and FastAPI)?**

A: Django is the main one. FastAPI is just a reference showing the same app could be built differently.

### **Q: Why use tokens instead of sessions?**

A: Tokens work better with SPAs (Single Page Apps) and are easier to scale across servers.

### **Q: Why do we need interceptors?**

A: To automatically add the auth token to every request without typing it each time.

### **Q: Why separate backend from frontend?**

A: They can run on different servers, scales better, easier to maintain.

### **Q: How does "only admins can create tasks" work?**

A: Frontend hides button if not admin. Backend double-checks in code before allowing create.

---

## **⚡ Quick Start Analogy**

Think of it like a restaurant:

- **Database**: Kitchen storage (food ingredients)
- **Django**: Chef (receives orders, cooks, follows recipes)
- **Angular**: Restaurant staff (takes orders, shows food to customers)
- **Users**: Customers (place orders, eat)
- **Roles**: Admin is head chef (can modify menu), Employee is waiter (can only take orders)
- **Token**: Receipt (proof you paid, lets you get food)

---
