from rest_framework import serializers
from .models import Task
from .services import TaskService


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ["id", "title", "description", "completed", "created_at"]
        extra_kwargs = {
            'title': {'required': True, 'allow_blank': False},
            'description': {'required': False, 'allow_blank': True},
        }

    def validate_title(self, value):
        """Validate title field"""
        if not value or not value.strip():
            raise serializers.ValidationError("Title cannot be empty.")
        
        if len(value.strip()) < 3:
            raise serializers.ValidationError("Title must be at least 3 characters long.")
        
        if len(value) > 255:
            raise serializers.ValidationError("Title cannot exceed 255 characters.")
        
        return value

    def validate_description(self, value):
        """Validate description field"""
        if value and len(value) > 1000:
            raise serializers.ValidationError("Description cannot exceed 1000 characters.")
        return value

    def validate(self, data):
        """Object-level validation"""
        if self.instance is None and not data.get('title'):
            raise serializers.ValidationError({
                'title': ['Title is required.']
            })

        if 'title' in data and not data.get('title'):
            raise serializers.ValidationError({
                'title': ['Title is required.']
            })
        
        # Check for duplicate titles on create
        if self.instance is None:  # Create operation
            existing = Task.objects.filter(
                title__iexact=data['title'].strip()
            ).exists()
            if existing:
                raise serializers.ValidationError({
                    'title': ['A task with this title already exists.']
                })
        
        return data

    def create(self, validated_data):
        """Create task using service layer"""
        try:
            task = TaskService.create_task(
                title=validated_data['title'],
                description=validated_data.get('description', '')
            )
            return task
        except ValueError as e:
            raise serializers.ValidationError(str(e))

    def update(self, instance, validated_data):
        """Update task using service layer"""
        try:
            task = TaskService.update_task(
                task=instance,
                title=validated_data.get('title'),
                description=validated_data.get('description'),
                completed=validated_data.get('completed')
            )
            return task
        except ValueError as e:
            raise serializers.ValidationError(str(e))
