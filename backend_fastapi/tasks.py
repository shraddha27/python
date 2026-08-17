from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend_fastapi.auth import get_current_user_dep, get_user_roles
from backend_fastapi.models import DocumentModel, TaskModel, get_db
from backend_fastapi.schemas import ApiResponse, BulkCreateRequest, BulkUpdateRequest, TaskCreate, TaskUpdate
from backend_fastapi.search import sync_task_document

tasks_router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def task_to_dict(task: TaskModel) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "completed": task.completed,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def get_task_or_404(db: Session, task_id: int) -> TaskModel:
    task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return task


def assert_unique_title(db: Session, title: str, task_id: Optional[int] = None):
    query = db.query(TaskModel).filter(func.lower(TaskModel.title) == title.lower().strip())
    if task_id is not None:
        query = query.filter(TaskModel.id != task_id)
    if query.first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A task with this title already exists.")


@tasks_router.get("/")
async def list_tasks(
    search: Optional[str] = Query(None, description="Search in title and description"),
    completed: Optional[bool] = Query(None, description="Filter by completion status"),
    skip: int = Query(0, ge=0, description="Number of tasks to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of tasks to return (max 100)"),
    db: Session = Depends(get_db),
):
    query = db.query(TaskModel)
    if search:
        like_value = f"%{search}%"
        query = query.filter(or_(TaskModel.title.ilike(like_value), TaskModel.description.ilike(like_value)))
    if completed is not None:
        query = query.filter(TaskModel.completed == completed)

    total = query.count()
    tasks = query.order_by(TaskModel.created_at.desc()).offset(skip).limit(limit).all()

    return ApiResponse(
        success=True,
        data=[task_to_dict(t) for t in tasks],
        pagination={
            "skip": skip,
            "limit": limit,
            "total": total,
            "has_more": (skip + limit) < total,
        },
    )


@tasks_router.post("/", status_code=status.HTTP_201_CREATED)
async def create_task(task_in: TaskCreate, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_dep(request)
    user_roles = get_user_roles(user)
    if "admin" not in user_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can create tasks")

    assert_unique_title(db, task_in.title)
    task = TaskModel(title=task_in.title, description=task_in.description, completed=False)
    db.add(task)
    try:
        db.commit()
        db.refresh(task)
        sync_task_document(db, task)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return ApiResponse(success=True, data=task_to_dict(task), message="Task created successfully")


@tasks_router.post("/bulk_create/", status_code=status.HTTP_201_CREATED)
async def bulk_create_tasks(payload: BulkCreateRequest, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_dep(request)
    user_roles = get_user_roles(user)
    if "admin" not in user_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can create tasks")

    if not payload.tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No tasks provided.")

    seen_titles = set()
    for task_in in payload.tasks:
        normalized_title = task_in.title.strip().lower()
        if normalized_title in seen_titles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Duplicate task title in request: '{task_in.title}'")
        seen_titles.add(normalized_title)
        assert_unique_title(db, task_in.title)

    created_tasks = []
    try:
        for task_in in payload.tasks:
            task = TaskModel(title=task_in.title, description=task_in.description, completed=False)
            db.add(task)
            created_tasks.append(task)
        db.commit()
        for task in created_tasks:
            db.refresh(task)
            sync_task_document(db, task)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return ApiResponse(success=True, data=[task_to_dict(t) for t in created_tasks], message=f"Created {len(created_tasks)} tasks successfully")


@tasks_router.get("/stats/")
async def task_stats(db: Session = Depends(get_db)):
    total = int(db.query(TaskModel).count())
    completed = int(db.query(TaskModel).filter(TaskModel.completed.is_(True)).count())
    pending = total - completed
    return ApiResponse(
        success=True,
        data={
            "total": total,
            "completed": completed,
            "pending": pending,
            "completion_percentage": float((completed / total * 100) if total else 0.0),
        },
    )


@tasks_router.get("/{task_id}/")
async def get_task(task_id: int, db: Session = Depends(get_db)):
    task = get_task_or_404(db, task_id)
    return ApiResponse(success=True, data=task_to_dict(task))


@tasks_router.put("/{task_id}/")
async def update_task(task_id: int, payload: TaskUpdate, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_dep(request)
    user_roles = get_user_roles(user)
    is_admin = "admin" in user_roles

    task = get_task_or_404(db, task_id)
    if not is_admin and (payload.title is not None or payload.description is not None):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employees can only change task status")

    if payload.title is not None:
        assert_unique_title(db, payload.title, task_id=task_id)
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.completed is not None:
        task.completed = payload.completed
        task.completed_at = datetime.utcnow() if payload.completed else None

    try:
        db.commit()
        db.refresh(task)
        sync_task_document(db, task)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return ApiResponse(success=True, data=task_to_dict(task), message="Task updated successfully")


@tasks_router.delete("/{task_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_dep(request)
    user_roles = get_user_roles(user)
    if "admin" not in user_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can delete tasks")

    task = get_task_or_404(db, task_id)
    db.query(DocumentModel).filter(DocumentModel.task_id == task.id).delete()
    db.delete(task)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@tasks_router.post("/bulk_update/")
async def bulk_update_tasks(payload: BulkUpdateRequest, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_dep(request)
    user_roles = get_user_roles(user)
    if not payload.task_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No task IDs provided.")

    tasks = db.query(TaskModel).filter(TaskModel.id.in_(payload.task_ids)).all()
    if not tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No tasks found with provided IDs.")

    for task in tasks:
        task.completed = payload.completed
    try:
        db.commit()
        for task in tasks:
            db.refresh(task)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return ApiResponse(success=True, data=[task_to_dict(t) for t in tasks], message=f"Updated {len(tasks)} tasks")
