"""File tree endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FileEvent
from ..schemas import TreeNodeResponse, TreeResponse
from ..tree_builder import FileTreeBuilder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tree", tags=["tree"])


def _convert_tree_node(node) -> TreeNodeResponse:
    """Convert internal TreeNode to response model."""
    return TreeNodeResponse(
        name=node.name,
        path=node.path,
        type=node.type,
        size=node.size,
        children=[_convert_tree_node(child) for child in node.children],
    )


@router.get("", response_model=TreeResponse)
async def get_file_tree(path: str = "", db: Session = Depends(get_db)):
    """Get file tree structure with sync status."""
    try:
        events = (
            db.execute(select(FileEvent).order_by(desc(FileEvent.timestamp)))
            .scalars()
            .all()
        )

        tree_builder = FileTreeBuilder()
        root_node = tree_builder.build_tree(events, path)
        stats = tree_builder.get_statistics(root_node)
        root_response = _convert_tree_node(root_node)

        return TreeResponse(
            root=root_response,
            total_files=stats["files"],
            total_folders=stats["folders"],
        )
    except Exception as exc:
        logger.error("Failed to get file tree: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file tree: {exc}",
        ) from exc


@router.get("/status/{path:path}", response_model=Dict[str, Any])
async def get_path_status(path: str, db: Session = Depends(get_db)):
    """Get sync status for a specific path."""
    try:
        latest_event = (
            db.execute(
                select(FileEvent)
                .where(FileEvent.file_path == path)
                .order_by(desc(FileEvent.timestamp))
            )
            .scalars()
            .first()
        )

        if latest_event:
            return {
                "path": path,
                "status": latest_event.action,
                "last_sync": latest_event.timestamp.isoformat(),
                "size": latest_event.file_size,
                "message": latest_event.message,
            }

        return {
            "path": path,
            "status": "unknown",
            "last_sync": None,
            "size": 0,
            "message": "No sync history",
        }
    except Exception as exc:
        logger.error("Failed to get path status: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get path status: {exc}",
        ) from exc

