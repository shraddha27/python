"""
SERVICE LAYER EXAMPLES & USAGE PATTERNS

This file demonstrates how to use the TaskService layer
for various business logic operations.
"""

from tasks.services import TaskService
from tasks.models import Task

# ============================================================================
# EXAMPLE 1: CREATE TASK WITH VALIDATION
# ============================================================================

try:
    task = TaskService.create_task(
        title="Buy groceries",
        description="Milk, eggs, and bread from the supermarket"
    )
    print(f"✓ Task created: {task.title} (ID: {task.id})")
except ValueError as e:
    print(f"✗ Error: {e}")

# Output: ✓ Task created: Buy groceries (ID: 1)


# ============================================================================
# EXAMPLE 2: DUPLICATE TITLE PREVENTION
# ============================================================================

try:
    # This will fail because a task with title "Buy groceries" already exists
    duplicate = TaskService.create_task(
        title="Buy groceries",
        description="Try again with same title"
    )
except ValueError as e:
    print(f"✗ Error: {e}")

# Output: ✗ Error: A task with this title already exists


# ============================================================================
# EXAMPLE 3: TITLE VALIDATION
# ============================================================================

# Too short
try:
    TaskService.create_task(title="AB")
except ValueError as e:
    print(f"✗ Title too short: {e}")

# Output: ✗ Title too short: Title must be at least 3 characters long

# Too long
try:
    TaskService.create_task(title="A" * 300)
except ValueError as e:
    print(f"✗ Title too long: {e}")

# Output: ✗ Title too long: Title cannot exceed 255 characters

# Empty
try:
    TaskService.create_task(title="   ")
except ValueError as e:
    print(f"✗ Empty title: {e}")

# Output: ✗ Empty title: Title cannot be empty


# ============================================================================
# EXAMPLE 4: UPDATE TASK WITH VALIDATION
# ============================================================================

task = Task.objects.first()  # Get a task

try:
    updated_task = TaskService.update_task(
        task=task,
        title="New title",
        description="Updated description",
        completed=True
    )
    print(f"✓ Task updated: {updated_task.title}")
except ValueError as e:
    print(f"✗ Update failed: {e}")

# Output: ✓ Task updated: New title


# ============================================================================
# EXAMPLE 5: GET TASKS WITH SEARCH
# ============================================================================

# Get all tasks
all_tasks = TaskService.get_tasks()
print(f"✓ Total tasks: {all_tasks.count()}")

# Search for tasks
search_results = TaskService.get_tasks(search_query="grocery")
print(f"✓ Found {search_results.count()} tasks matching 'grocery'")

# Get only completed tasks
completed_tasks = TaskService.get_tasks(completed=True)
print(f"✓ Completed tasks: {completed_tasks.count()}")

# Get only pending tasks
pending_tasks = TaskService.get_tasks(completed=False)
print(f"✓ Pending tasks: {pending_tasks.count()}")

# Search AND filter
results = TaskService.get_tasks(search_query="work", completed=False)
print(f"✓ Found {results.count()} pending tasks with 'work' in title/description")


# ============================================================================
# EXAMPLE 6: GET TASK STATISTICS
# ============================================================================

stats = TaskService.get_task_stats()
print(f"""
✓ Task Statistics:
  - Total: {stats['total']}
  - Completed: {stats['completed']}
  - Pending: {stats['pending']}
  - Completion Rate: {stats['completion_percentage']:.1f}%
""")

# Output:
# ✓ Task Statistics:
#   - Total: 10
#   - Completed: 7
#   - Pending: 3
#   - Completion Rate: 70.0%


# ============================================================================
# EXAMPLE 7: BULK UPDATE TASKS
# ============================================================================

try:
    task_ids = [1, 2, 3, 4, 5]
    updated_count = TaskService.bulk_update_tasks(
        task_ids=task_ids,
        completed=True
    )
    print(f"✓ Updated {updated_count} tasks to completed")
except ValueError as e:
    print(f"✗ Bulk update failed: {e}")

# Output: ✓ Updated 5 tasks to completed


# ============================================================================
# EXAMPLE 8: DELETE TASK
# ============================================================================

task = Task.objects.first()
task_title = task.title

try:
    success = TaskService.delete_task(task)
    if success:
        print(f"✓ Task '{task_title}' deleted successfully")
except ValueError as e:
    print(f"✗ Delete failed: {e}")

# Output: ✓ Task 'Buy groceries' deleted successfully


# ============================================================================
# EXAMPLE 9: ERROR HANDLING IN VIEWS (from views.py)
# ============================================================================

"""
In a DRF view, errors are automatically caught and returned:

def create(self, request, *args, **kwargs):
    serializer = self.get_serializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(
            {'errors': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        self.perform_create(serializer)
        return Response(
            {'data': serializer.data, 'success': True},
            status=status.HTTP_201_CREATED
        )
    except Exception as e:
        return Response(
            {'errors': {'detail': str(e)}, 'success': False},
            status=status.HTTP_400_BAD_REQUEST
        )

REQUEST:
POST /api/tasks/
{
    "title": "AB"
}

RESPONSE (400):
{
    "errors": {
        "title": ["Title must be at least 3 characters long."]
    },
    "success": false
}
"""


# ============================================================================
# EXAMPLE 10: FRONTEND SERVICE ERROR HANDLING
# ============================================================================

"""
In Angular (app.service.ts), errors are handled and transformed:

addTask(task: Partial<Task>): Observable<Task> {
  return this.http.post<ApiResponse<Task>>(this.apiUrl, task).pipe(
    catchError(this.handleError)
  );
}

private handleError(error: HttpErrorResponse): Observable<never> {
  let apiError: ApiError = { message: 'An error occurred' };
  
  if (error.error && typeof error.error === 'object') {
    if (error.error.errors) {
      apiError.errors = error.error.errors;
    }
    if (error.error.detail) {
      apiError.detail = error.error.detail;
    }
  }
  
  return throwError(() => apiError);
}

In the component, you can then display field errors:

this.appService.addTask(task).subscribe({
  next: (task) => { /* Success */ },
  error: (error: ApiError) => {
    if (error.errors) {
      this.fieldErrors = this.flattenErrors(error.errors);
    } else {
      this.generalError = error.message;
    }
  }
});
"""


# ============================================================================
# VALIDATION SUMMARY
# ============================================================================

VALIDATIONS = {
    "title": {
        "required": True,
        "min_length": 3,
        "max_length": 255,
        "unique": True,
        "no_empty_strings": True,
    },
    "description": {
        "required": False,
        "max_length": 1000,
    },
}

print("\n✓ Service Layer Implementation Complete!")
print("  - Task creation with validation")
print("  - Task updates with validation")
print("  - Search and filtering")
print("  - Statistics calculation")
print("  - Bulk operations")
print("  - Error handling and messages")
