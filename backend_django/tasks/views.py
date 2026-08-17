from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.middleware.csrf import get_token
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from .models import Task
from .serializers import TaskSerializer
from .services import TaskService
from .auth_views import get_user_from_token, get_user_roles_by_user_id


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.order_by("-created_at")
    serializer_class = TaskSerializer

    def get_queryset(self):
        """Get tasks with optional filtering"""
        queryset = Task.objects.all()
        
        # Search filter
        search = self.request.query_params.get('search', None)
        if search:
            queryset = TaskService.get_tasks(search_query=search)
        
        # Completion filter
        completed = self.request.query_params.get('completed', None)
        if completed is not None:
            completed_bool = completed.lower() == 'true'
            queryset = TaskService.get_tasks(completed=completed_bool)
        
        return queryset.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        """List all tasks with proper response format and pagination"""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Pagination parameters
        skip = int(request.query_params.get('skip', 0))
        limit = int(request.query_params.get('limit', 10))
        
        # Validate limits
        limit = max(1, min(limit, 100))  # 1-100 items per page
        skip = max(0, skip)
        
        # Get total count
        total = queryset.count()
        
        # Apply pagination
        queryset = queryset[skip:skip + limit]
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                'data': serializer.data,
                'success': True,
                'pagination': {
                    'skip': skip,
                    'limit': limit,
                    'total': total,
                    'has_more': (skip + limit) < total
                }
            },
            status=status.HTTP_200_OK
        )

    def create(self, request, *args, **kwargs):
        """Create a new task with error handling - Admin only"""
        # Check admin permission
        user_data = get_user_from_token(request)
        if not user_data:
            return Response(
                {'errors': {'detail': 'Not authenticated'}, 'success': False},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        roles = get_user_roles_by_user_id(user_data["id"])
        role_names = [r["name"] for r in roles]
        
        if "admin" not in role_names:
            return Response(
                {'errors': {'detail': 'Only admins can create tasks'}, 'success': False},
                status=status.HTTP_403_FORBIDDEN
            )
        
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

    def update(self, request, *args, **kwargs):
        """Update a task with role-based permissions"""
        # Check authentication and role
        user_data = get_user_from_token(request)
        if not user_data:
            return Response(
                {'errors': {'detail': 'Not authenticated'}, 'success': False},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        roles = get_user_roles_by_user_id(user_data["id"])
        role_names = [r["name"] for r in roles]
        is_admin = "admin" in role_names
        
        instance = self.get_object()
        
        # Check if employee is trying to update non-completed fields
        if not is_admin:
            payload = request.data
            print(f"DEBUG: Employee {user_data['id']} - Update payload: {payload}")
            
            # Check if trying to update title or description
            if payload.get('title') or payload.get('description'):
                return Response(
                    {'errors': {'detail': 'Employees can only change task status'}, 'success': False},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # For employees, directly update only the completed field
            if 'completed' in payload:
                instance.completed = payload['completed']
                instance.save()
                
                serializer = self.get_serializer(instance)
                return Response(
                    {'data': serializer.data, 'success': True},
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {'errors': {'detail': 'No valid fields to update'}, 'success': False},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # Admins can update all fields using the serializer
            # Always use partial=True to allow partial updates
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            
            if not serializer.is_valid():
                return Response(
                    {'errors': serializer.errors, 'success': False},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                self.perform_update(serializer)
                return Response(
                    {'data': serializer.data, 'success': True},
                    status=status.HTTP_200_OK
                )
            except Exception as e:
                return Response(
                    {'errors': {'detail': str(e)}, 'success': False},
                    status=status.HTTP_400_BAD_REQUEST
                )

    def destroy(self, request, *args, **kwargs):
        """Delete a task with error handling - Admin only"""
        # Check admin permission
        user_data = get_user_from_token(request)
        if not user_data:
            return Response(
                {'errors': {'detail': 'Not authenticated'}, 'success': False},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        roles = get_user_roles_by_user_id(user_data["id"])
        role_names = [r["name"] for r in roles]
        
        if "admin" not in role_names:
            return Response(
                {'errors': {'detail': 'Only admins can delete tasks'}, 'success': False},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            instance = self.get_object()
            self.perform_destroy(instance)
            return Response(
                {'success': True, 'message': 'Task deleted successfully'},
                status=status.HTTP_204_NO_CONTENT
            )
        except Exception as e:
            return Response(
                {'errors': {'detail': str(e)}, 'success': False},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get task statistics"""
        try:
            stats = TaskService.get_task_stats()
            return Response(
                {'data': stats, 'success': True},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'errors': {'detail': str(e)}, 'success': False},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def bulk_update(self, request):
        """Bulk update multiple tasks"""
        try:
            task_ids = request.data.get('task_ids', [])
            completed = request.data.get('completed', None)
            
            if not task_ids:
                return Response(
                    {'errors': {'task_ids': ['No task IDs provided']}},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            count = TaskService.bulk_update_tasks(task_ids, completed=completed)
            tasks = Task.objects.filter(id__in=task_ids)
            serializer = self.get_serializer(tasks, many=True)
            
            return Response(
                {
                    'data': serializer.data,
                    'success': True,
                    'updated_count': count
                },
                status=status.HTTP_200_OK
            )
        except ValueError as e:
            return Response(
                {'errors': {'detail': str(e)}, 'success': False},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'errors': {'detail': str(e)}, 'success': False},
                status=status.HTTP_400_BAD_REQUEST
            )


@require_http_methods(["GET"])
def csrf_token(request):
    """Get CSRF token endpoint - allows any access to fetch token"""
    # Get or create CSRF token (this triggers Django's CSRF middleware to set the cookie)
    token = get_token(request)
    return JsonResponse({'csrfToken': token})
