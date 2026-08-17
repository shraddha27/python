import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
try:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
except Exception:
    google_requests = None
    id_token = None
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from backend_fastapi.models import Role, SessionLocal, User, UserRole, get_db
from backend_fastapi.schemas import RoleSchema, TokenResponse, UserSchema, GoogleLoginRequest

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
AUTH_COOKIE_NAME = "auth_token"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


def create_access_token(user_id: int, expires_delta: Optional[int] = None) -> str:
    from datetime import datetime, timedelta

    if expires_delta:
        expire = datetime.utcnow() + timedelta(minutes=expires_delta)
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": str(user_id), "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return int(user_id)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def get_user_roles(user: User) -> List[str]:
    if hasattr(user, "_roles_cache"):
        return [role["name"] for role in user._roles_cache]
    return [ur.role.name for ur in user.roles]


async def get_current_user_dep(request: Request) -> User:
    db = SessionLocal()
    try:
        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        else:
            token = request.cookies.get(AUTH_COOKIE_NAME)

        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        user_id = verify_token(token)
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        result = db.execute(
            text(
                """
                SELECT r.id, r.name
                FROM roles r
                JOIN user_roles ur ON r.id = ur.role_id
                WHERE ur.user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        rows = result.fetchall()

        roles_data = [{"id": row[0], "name": row[1]} for row in rows] if rows else []
        if not roles_data:
            employee_role = db.query(Role).filter(Role.name == "employee").first()
            if not employee_role:
                employee_role = Role(name="employee")
                db.add(employee_role)
                db.flush()
            user_role = UserRole(user_id=user_id, role_id=employee_role.id)
            db.add(user_role)
            db.commit()
            roles_data = [{"id": employee_role.id, "name": "employee"}]

        db.expunge(user)
        user._roles_cache = roles_data
        return user
    finally:
        db.close()


def verify_google_token(id_token_str: str) -> dict:
    if not google_requests or not id_token:
        raise ValueError("Google auth libraries not available in this environment")
    try:
        request = google_requests.Request()
        idinfo = id_token.verify_oauth2_token(id_token_str, request, GOOGLE_CLIENT_ID)
        if idinfo["iss"] not in ["accounts.google.com", "https://accounts.google.com"]:
            raise ValueError("Invalid issuer")
        return idinfo
    except Exception as exc:
        raise ValueError(f"Invalid Google token: {exc}")


@auth_router.post("/google/", response_model=TokenResponse)
def google_login(request: GoogleLoginRequest, response: Response, db: Session = Depends(get_db)):
    try:
        decoded = verify_google_token(request.id_token)
        google_id = decoded.get("sub")
        email = decoded.get("email")
        name = decoded.get("name", email.split("@")[0] if email else "User")

        if not google_id or not email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token data")

        user = db.query(User).filter(User.google_id == google_id).first()
        if not user:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                user = User(email=email, name=name, google_id=google_id)
                db.add(user)
                db.flush()
            else:
                user.google_id = google_id
            existing_role = db.query(UserRole).filter(UserRole.user_id == user.id).first()
            if not existing_role:
                user_count = db.query(User).count()
                role_name = "admin" if user_count == 1 else "employee"
                target_role = db.query(Role).filter(Role.name == role_name).first()
                if not target_role:
                    target_role = Role(name=role_name)
                    db.add(target_role)
                    db.flush()
                db.add(UserRole(user_id=user.id, role_id=target_role.id))

        db.commit()
        user = db.query(User).options(joinedload(User.roles).joinedload(UserRole.role)).filter(User.id == user.id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load user after creation")

        roles_list = [RoleSchema(id=ur.role.id, name=ur.role.name) for ur in user.roles] if user.roles else []
        access_token = create_access_token(user.id)
        response.set_cookie(
            key=AUTH_COOKIE_NAME,
            value=access_token,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path="/",
        )
        return TokenResponse(
            access_token="",
            token_type="bearer",
            user=UserSchema(id=user.id, email=user.email, name=user.name, roles=roles_list),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@auth_router.get("/me/", response_model=UserSchema)
async def get_me(request: Request):
    user = await get_current_user_dep(request)
    roles_list = [RoleSchema(id=role["id"], name=role["name"]) for role in getattr(user, "_roles_cache", [])]
    if not roles_list:
        roles_list = [RoleSchema(id=ur.role.id, name=ur.role.name) for ur in user.roles]
    return UserSchema(id=user.id, email=user.email, name=user.name, roles=roles_list)


@auth_router.post("/logout/")
async def logout(response: Response):
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return {"message": "Logged out successfully"}
