"""Tests for the FileTreeBuilder class."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.api.tree_builder import FileTreeBuilder, TreeNode


class TestTreeNode:
    """Tests for TreeNode class."""

    def test_create_folder_node(self):
        """Should create a folder node."""
        node = TreeNode(name="Documents", path="Documents", node_type="folder")

        assert node.name == "Documents"
        assert node.path == "Documents"
        assert node.type == "folder"
        assert node.children == []

    def test_create_file_node(self):
        """Should create a file node."""
        node = TreeNode(name="report.pdf", path="Documents/report.pdf", node_type="file")

        assert node.name == "report.pdf"
        assert node.type == "file"

    def test_add_child(self):
        """Should add child nodes."""
        parent = TreeNode(name="root", path="", node_type="folder")
        child1 = TreeNode(name="folder1", path="folder1", node_type="folder")
        child2 = TreeNode(name="file.txt", path="file.txt", node_type="file")

        parent.add_child(child1)
        parent.add_child(child2)

        assert len(parent.children) == 2

    def test_add_child_sorted(self):
        """Should sort children (folders first, then alphabetically)."""
        parent = TreeNode(name="root", path="", node_type="folder")
        file1 = TreeNode(name="zebra.txt", path="zebra.txt", node_type="file")
        folder1 = TreeNode(name="alpha", path="alpha", node_type="folder")
        file2 = TreeNode(name="apple.txt", path="apple.txt", node_type="file")

        parent.add_child(file1)
        parent.add_child(folder1)
        parent.add_child(file2)

        # Folders should come first
        assert parent.children[0].type == "folder"
        assert parent.children[0].name == "alpha"
        # Files should be alphabetical
        assert parent.children[1].name == "apple.txt"
        assert parent.children[2].name == "zebra.txt"

    def test_find_child(self):
        """Should find child by name."""
        parent = TreeNode(name="root", path="", node_type="folder")
        child = TreeNode(name="docs", path="docs", node_type="folder")
        parent.add_child(child)

        found = parent.find_child("docs")
        assert found is not None
        assert found.name == "docs"

    def test_find_child_not_found(self):
        """Should return None when child not found."""
        parent = TreeNode(name="root", path="", node_type="folder")
        found = parent.find_child("nonexistent")
        assert found is None

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = TreeNode(name="test", path="test", node_type="file")
        node.size = 1024
        node.status = "synced"

        result = node.to_dict()

        assert result["name"] == "test"
        assert result["path"] == "test"
        assert result["type"] == "file"
        assert result["size"] == 1024
        assert result["status"] == "synced"


class TestFileTreeBuilder:
    """Tests for FileTreeBuilder class."""

    def _create_mock_event(
        self,
        file_path: str,
        action: str = "added",
        file_size: int = 1024,
    ) -> MagicMock:
        """Create a mock FileEvent."""
        event = MagicMock()
        event.file_path = file_path
        event.action = action
        event.file_size = file_size
        event.timestamp = datetime.now(timezone.utc)
        event.file_hash = None
        event.message = None
        return event

    def test_build_empty_tree(self):
        """Should build empty tree with no events."""
        builder = FileTreeBuilder()
        root = builder.build_tree([])

        assert root.name == "root"
        assert root.type == "folder"
        assert len(root.children) == 0

    def test_build_tree_single_file(self):
        """Should build tree with single file."""
        builder = FileTreeBuilder()
        events = [self._create_mock_event("document.pdf")]

        root = builder.build_tree(events)

        assert len(root.children) == 1
        assert root.children[0].name == "document.pdf"
        assert root.children[0].type == "file"

    def test_build_tree_nested_path(self):
        """Should build tree with nested folder structure."""
        builder = FileTreeBuilder()
        events = [self._create_mock_event("Documents/Reports/annual.pdf")]

        root = builder.build_tree(events)

        # Check Documents folder
        docs = root.find_child("Documents")
        assert docs is not None
        assert docs.type == "folder"

        # Check Reports folder
        reports = docs.find_child("Reports")
        assert reports is not None
        assert reports.type == "folder"

        # Check file
        file_node = reports.find_child("annual.pdf")
        assert file_node is not None
        assert file_node.type == "file"

    def test_build_tree_multiple_files(self):
        """Should build tree with multiple files."""
        builder = FileTreeBuilder()
        events = [
            self._create_mock_event("file1.txt"),
            self._create_mock_event("folder/file2.txt"),
            self._create_mock_event("folder/file3.txt"),
        ]

        root = builder.build_tree(events)

        assert len(root.children) == 2  # folder and file1.txt

        folder = root.find_child("folder")
        assert folder is not None
        assert len(folder.children) == 2

    def test_get_statistics(self):
        """Should calculate correct statistics."""
        builder = FileTreeBuilder()
        events = [
            self._create_mock_event("file1.txt", file_size=100),
            self._create_mock_event("folder/file2.txt", file_size=200),
            self._create_mock_event("folder/sub/file3.txt", file_size=300),
        ]

        root = builder.build_tree(events)
        stats = builder.get_statistics(root)

        assert stats["files"] == 3
        assert stats["folders"] == 3  # root, folder, sub
        assert stats["total_size"] == 600

    def test_file_status_from_action(self):
        """Should set file status based on event action."""
        builder = FileTreeBuilder()

        # Test "added" action
        events = [self._create_mock_event("file.txt", action="added")]
        root = builder.build_tree(events)
        assert root.children[0].status == "synced"

        # Test "error" action
        events = [self._create_mock_event("bad.txt", action="error")]
        root = builder.build_tree(events)
        assert root.children[0].status == "error"

    def test_folder_status_propagation(self):
        """Should propagate status from files to folders."""
        builder = FileTreeBuilder()
        events = [
            self._create_mock_event("folder/good.txt", action="added"),
            self._create_mock_event("folder/bad.txt", action="error"),
        ]

        root = builder.build_tree(events)
        folder = root.find_child("folder")

        # Folder should have "error" status (highest priority)
        assert folder.status == "error"

    def test_search_tree(self):
        """Should search for nodes by name."""
        builder = FileTreeBuilder()
        events = [
            self._create_mock_event("docs/report.pdf"),
            self._create_mock_event("docs/summary.pdf"),
            self._create_mock_event("images/photo.jpg"),
        ]

        root = builder.build_tree(events)
        results = builder.search_tree(root, "pdf")

        assert len(results) == 2
        names = [r.name for r in results]
        assert "report.pdf" in names
        assert "summary.pdf" in names

