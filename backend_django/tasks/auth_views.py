import json
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import connection, transaction
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

User = get_user_model()

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
AUTH_COOKIE_NAME = "auth_token"


def create_access_token(user_id: int, expires_delta: Optional[timedelta] = None):
    """Create JWT token"""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {"sub": str(user_id), "exp": expire}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_or_create_user_in_shared_table(django_user):
    """
    Get or create the user in the shared 'users' table.
    The FastAPI schema uses a 'users' table that is separate from Django's auth_user.
    """
    with connection.cursor() as cursor:
        # Check if user exists in the shared users table
        cursor.execute(
            """
            SELECT id FROM users WHERE email = %s LIMIT 1
            """,
            [django_user.email],
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        
        # Create user in the shared users table
        cursor.execute(
            """
            INSERT INTO users (email, name, google_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            [
                django_user.email,
                django_user.get_full_name() or django_user.username,
                django_user.email,  # Use email as google_id fallback
            ],
        )
        new_user_id = cursor.fetchone()[0]
        return new_user_id


def get_role_rows_for_user(user_id: int):
    """Get role rows for a user from roles/user_roles tables."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT r.id, r.name
            FROM roles r
            INNER JOIN user_roles ur ON ur.role_id = r.id
            WHERE ur.user_id = %s
            ORDER BY r.id
            """,
            [user_id],
        )
        return cursor.fetchall()


def get_role_id_by_name(role_name: str):
    """Look up a role id by name from the roles table."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM roles
            WHERE LOWER(name) = LOWER(%s)
            LIMIT 1
            """,
            [role_name],
        )
        row = cursor.fetchone()
        return row[0] if row else None


def ensure_user_role(user_id: int, role_name: str):
    """Create a user_roles mapping if it does not already exist."""
    role_id = get_role_id_by_name(role_name)
    if not role_id:
        return

    with connection.cursor() as cursor, transaction.atomic():
        cursor.execute(
            """
            INSERT INTO user_roles (user_id, role_id)
            SELECT %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM user_roles WHERE user_id = %s AND role_id = %s
            )
            """,
            [user_id, role_id, user_id, role_id],
        )


def get_user_roles_by_user_id(user_id: int):
    """Get user roles from the roles/user_roles tables by shared user id."""
    rows = get_role_rows_for_user(user_id)
    role_names = {name.strip().lower() for _, name in rows if name}

    if not role_names:
        role_names.add("employee")

    return [{"id": index + 1, "name": name} for index, name in enumerate(sorted(role_names))]


def get_user_roles(user):
    """Get user roles from the roles/user_roles tables."""
    rows = get_role_rows_for_user(user.id)
    role_names = {name.strip().lower() for _, name in rows if name}

    # Django admin/staff users should always be treated as admin in the app.
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        role_names.add("admin")

    if not role_names:
        role_names.add("employee")

    return [{"id": index + 1, "name": name} for index, name in enumerate(sorted(role_names))]


def user_to_dict(user):
    """Convert user to dict with roles"""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.get_full_name() or user.username,
        "roles": get_user_roles(user),
    }


def verify_google_token(id_token_str: str):
    """
    Verify Google ID token with Google's servers.
    Returns decoded token data if valid, raises exception if invalid.
    """
    try:
        # Get the Google Client ID from settings
        google_client_id = settings.GOOGLE_CLIENT_ID
        
        # Verify the token using google-auth library
        request = google_requests.Request()
        idinfo = id_token.verify_oauth2_token(id_token_str, request, google_client_id)
        
        # Verify the token is not expired (id_token library checks this automatically)
        # Verify the issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Invalid issuer')
        
        return idinfo
    except Exception as e:
        print(f"ERROR verifying Google token: {str(e)}")
        raise ValueError(f"Invalid Google token: {str(e)}")


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def google_login(request):
    """
    Login with Google ID token.
    Verifies the token with Google's servers.
    """
    try:
        id_token_str = request.data.get("id_token")
        if not id_token_str:
            return Response(
                {"errors": {"detail": "id_token is required"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Verify token with Google's servers
        print(f"DEBUG: Verifying Google token with Google's servers")
        decoded = verify_google_token(id_token_str)
        
        google_id = decoded.get("sub")
        email = decoded.get("email")
        name = decoded.get("name", email.split("@")[0] if email else "User")
        
        if not google_id or not email:
            return Response(
                {"errors": {"detail": "Invalid token data"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        print(f"DEBUG: Google token verified for user {email}")
        
        # Find or create user in Django auth
        user, _ = User.objects.get_or_create(
            email=email,
            defaults={"username": email, "first_name": name.split()[0] if name else ""}
        )

        # Get or create user in the shared 'users' table and get that user's id
        shared_user_id = get_or_create_user_in_shared_table(user)

        # Keep the DB role mapping as the source of truth.
        # If the user has no role mapping yet, assign a role
        if not get_role_rows_for_user(shared_user_id):
            # Check if this is the first user - if so, make them admin
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM users")
                user_count = cursor.fetchone()[0]
            
            role_name = "admin" if user_count == 1 else "employee"
            ensure_user_role(shared_user_id, role_name)
            print(f"DEBUG: New user {shared_user_id} assigned role: {role_name} (user_count={user_count})")
        
        # Create access token using the shared user id
        access_token = create_access_token(shared_user_id)

        response = Response(
            {
                "success": True,
                "token_type": "bearer",
                "user": {
                    "id": shared_user_id,
                    "email": user.email,
                    "name": user.get_full_name() or user.username,
                    "roles": get_user_roles_by_user_id(shared_user_id),
                },
            },
            status=status.HTTP_200_OK,
        )
        response.set_cookie(
            key=AUTH_COOKIE_NAME,
            value=access_token,
            httponly=True,
            secure=False,
            samesite="Lax",
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path="/",
        )
        return response
    except ValueError as e:
        # Token verification failed
        return Response(
            {"errors": {"detail": str(e)}, "success": False},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    except Exception as e:
        import traceback
        print(f"ERROR in google_login: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"errors": {"detail": str(e)}, "success": False},
            status=status.HTTP_400_BAD_REQUEST,
        )


def get_user_from_token(request):
    """Extract and verify user from Authorization header"""
    auth_header = request.META.get("HTTP_AUTHORIZATION")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        token = request.COOKIES.get(AUTH_COOKIE_NAME)

    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            return None
        
        # Query the shared users table (not Django's auth_user)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, email, name
                FROM users
                WHERE id = %s
                LIMIT 1
                """,
                [int(user_id)],
            )
            row = cursor.fetchone()
            if row:
                return {"id": row[0], "email": row[1], "name": row[2]}
        return None
    except (jwt.InvalidTokenError, ValueError):
        return None


@api_view(["GET"])
def get_current_user(request):
    """Get current authenticated user"""
    user_data = get_user_from_token(request)
    if not user_data:
        return Response(
            {"errors": {"detail": "Not authenticated"}, "success": False},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    
    # user_data is now a dict from the shared users table
    shared_user_id = user_data["id"]
    
    return Response(
        {
            "success": True,
            "id": shared_user_id,
            "email": user_data["email"],
            "name": user_data["name"],
            "roles": get_user_roles_by_user_id(shared_user_id),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def logout_view(request):
    """Logout endpoint (token invalidation handled client-side)"""
    response = Response(
        {"success": True, "message": "Logged out successfully"},
        status=status.HTTP_200_OK,
    )
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return response
