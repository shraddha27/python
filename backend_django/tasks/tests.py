from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Task


class TaskApiTests(APITestCase):
    def setUp(self):
        # Create test data
        self.task1 = Task.objects.create(title="Test Task 1", description="Description 1", completed=False)
        self.task2 = Task.objects.create(title="Test Task 2", description="Description 2", completed=True)
        self.url = reverse('task-list')

    def test_create_and_list_tasks(self):
        # Test creating a task
        response = self.client.post(self.url, {'title': 'New task', 'description': 'New description'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Task.objects.count(), 3)
        self.assertEqual(response.data['title'], 'New task')
        self.assertEqual(response.data['description'], 'New description')
        self.assertFalse(response.data['completed'])

        # Test listing tasks
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        # Check ordering by created_at descending
        self.assertEqual(response.data[0]['title'], 'New task')

    def test_get_single_task(self):
        # Test retrieving a single task
        url = reverse('task-detail', kwargs={'pk': self.task1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Test Task 1')
        self.assertEqual(response.data['description'], 'Description 1')
        self.assertFalse(response.data['completed'])

    def test_update_task(self):
        # Test updating a task
        url = reverse('task-detail', kwargs={'pk': self.task1.pk})
        data = {'title': 'Updated Task', 'description': 'Updated description', 'completed': True}
        response = self.client.put(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.task1.refresh_from_db()
        self.assertEqual(self.task1.title, 'Updated Task')
        self.assertEqual(self.task1.description, 'Updated description')
        self.assertTrue(self.task1.completed)

    def test_partial_update_task(self):
        # Test partial update
        url = reverse('task-detail', kwargs={'pk': self.task1.pk})
        response = self.client.patch(url, {'completed': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.task1.refresh_from_db()
        self.assertTrue(self.task1.completed)
        self.assertEqual(self.task1.title, 'Test Task 1')  # Unchanged

    def test_delete_task(self):
        # Test deleting a task
        url = reverse('task-detail', kwargs={'pk': self.task1.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Task.objects.count(), 1)

    def test_create_task_without_description(self):
        # Test creating task with only title
        response = self.client.post(self.url, {'title': 'Task without desc'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task = Task.objects.get(title='Task without desc')
        self.assertEqual(task.description, '')

    def test_create_task_validation(self):
        # Test creating task without title (should fail)
        response = self.client.post(self.url, {'description': 'No title'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_duplicate_task_title(self):
        # Test creating a task with a duplicate title (should fail)
        response = self.client.post(self.url, {'title': 'Test Task 1', 'description': 'Duplicate title'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response.data['errors'])
        self.assertEqual(response.data['errors']['title'][0], 'A task with this title already exists.')

    def test_task_str_method(self):
        # Test model string representation
        self.assertEqual(str(self.task1), 'Test Task 1')
