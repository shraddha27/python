from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet, csrf_token
from .auth_views import google_login, get_current_user, logout_view

router = DefaultRouter()
router.register(r"tasks", TaskViewSet, basename="task")

urlpatterns = [
    path("", include(router.urls)),
    # CSRF endpoint
    path("csrf-token/", csrf_token, name="csrf-token"),
    # Auth endpoints
    path("auth/google/", google_login, name="google-login"),
    path("auth/me/", get_current_user, name="get-current-user"),
    path("auth/logout/", logout_view, name="logout"),
]
