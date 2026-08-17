"""
Service layer for Task business logic
Handles custom validation, calculations, and operations
"""

from django.db.models import Q
from datetime import datetime
from .models import Task


class TaskService:
    """Service class for Task operations with business logic"""

    @staticmethod
    def create_task(title, description="", user=None):
        """
        Create a new task with validation
        
        Args:
            title: Task title (required)
            description: Task description
            user: User instance (if using user-based tasks)
            
        Returns:
            Task instance
            
        Raises:
            ValueError: If validation fails
        """
        # Custom validation logic
        if not title or not title.strip():
            raise ValueError("Title cannot be empty")
        
        if len(title.strip()) < 3:
            raise ValueError("Title must be at least 3 characters long")
        
        if len(title) > 255:
            raise ValueError("Title cannot exceed 255 characters")
        
        if description and len(description) > 1000:
            raise ValueError("Description cannot exceed 1000 characters")
        
        # Check for duplicate titles (case-insensitive)
        existing = Task.objects.filter(
            title__iexact=title.strip()
        ).first()
        
        if existing:
            raise ValueError("A task with this title already exists")
        
        # Create task
        task = Task.objects.create(
            title=title.strip(),
            description=description.strip() if description else ""
        )
        
        return task

    @staticmethod
    def update_task(task, title=None, description=None, completed=None):
        """
        Update task with validation
        
        Args:
            task: Task instance
            title: New title (optional)
            description: New description (optional)
            completed: Completion status (optional)
            
        Returns:
            Updated Task instance
            
        Raises:
            ValueError: If validation fails
        """
        if title is not None:
            if not title.strip():
                raise ValueError("Title cannot be empty")
            
            if len(title.strip()) < 3:
                raise ValueError("Title must be at least 3 characters long")
            
            if len(title) > 255:
                raise ValueError("Title cannot exceed 255 characters")
            
            # Check for duplicate titles (exclude current task)
            existing = Task.objects.filter(
                title__iexact=title.strip()
            ).exclude(id=task.id).first()
            
            if existing:
                raise ValueError("A task with this title already exists")
            
            task.title = title.strip()
        
        if description is not None:
            if len(description) > 1000:
                raise ValueError("Description cannot exceed 1000 characters")
            task.description = description.strip() if description else ""
        
        if completed is not None:
            task.completed = completed
        
        task.save()
        return task

    @staticmethod
    def delete_task(task):
        """
        Delete a task with business logic
        
        Args:
            task: Task instance
            
        Returns:
            Boolean indicating success
        """
        task.delete()
        return True

    @staticmethod
    def get_tasks(search_query=None, completed=None, sort_by="-created_at"):
        """
        Get tasks with optional filtering and sorting
        
        Args:
            search_query: Search in title and description
            completed: Filter by completion status (True/False/None for all)
            sort_by: Sort field
            
        Returns:
            QuerySet of Task objects
        """
        queryset = Task.objects.all()
        
        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) | 
                Q(description__icontains=search_query)
            )
        
        if completed is not None:
            queryset = queryset.filter(completed=completed)
        
        return queryset.order_by(sort_by)

    @staticmethod
    def get_task_stats():
        """
        Get task statistics
        
        Returns:
            Dictionary with task stats
        """
        total = Task.objects.count()
        completed = Task.objects.filter(completed=True).count()
        pending = total - completed
        
        return {
            "total": total,
            "completed": completed,
            "pending": pending,
            "completion_percentage": (completed / total * 100) if total > 0 else 0
        }

    @staticmethod
    def bulk_update_tasks(task_ids, completed=None):
        """
        Bulk update multiple tasks
        
        Args:
            task_ids: List of task IDs
            completed: New completion status
            
        Returns:
            Number of tasks updated
        """
        if not task_ids:
            raise ValueError("No task IDs provided")
        
        queryset = Task.objects.filter(id__in=task_ids)
        
        if not queryset.exists():
            raise ValueError("No tasks found with provided IDs")
        
        if completed is not None:
            updated = queryset.update(completed=completed)
            return updated
        
        return 0
