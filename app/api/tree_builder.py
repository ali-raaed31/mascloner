"""
File Tree Builder for MasCloner

Builds hierarchical file tree structures from file events.
"""

import os
from pathlib import Path
from typing import Dict, List, Set, Any, Optional
from collections import defaultdict
from datetime import datetime

from .models import FileEvent


class TreeNode:
    """Tree node representing a file or folder."""
    
    def __init__(self, name: str, path: str, node_type: str = "folder"):
        self.name = name
        self.path = path
        self.type = node_type  # "file" or "folder"
        self.size = 0
        self.last_sync: Optional[str] = None
        self.status = "unknown"  # synced, pending, error, conflict
        self.children: List["TreeNode"] = []
        self.latest_event: Optional[FileEvent] = None
    
    def add_child(self, child: "TreeNode"):
        """Add a child node."""
        self.children.append(child)
        self.children.sort(key=lambda x: (x.type == "file", x.name.lower()))
    
    def find_child(self, name: str) -> Optional["TreeNode"]:
        """Find a child node by name."""
        for child in self.children:
            if child.name == name:
                return child
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary for API response."""
        return {
            "name": self.name,
            "path": self.path,
            "type": self.type,
            "size": self.size,
            "last_sync": self.last_sync,
            "status": self.status,
            "children": [child.to_dict() for child in self.children]
        }


class FileTreeBuilder:
    """Builds file tree from sync events."""
    
    def __init__(self):
        self.status_priority = {
            "error": 4,
            "conflict": 3,
            "pending": 2,
            "synced": 1,
            "unknown": 0
        }
    
    def build_tree(self, events: List[FileEvent], base_path: str = "") -> TreeNode:
        """Build tree structure from file events."""
        
        # Create root node
        root = TreeNode(
            name="root" if not base_path else os.path.basename(base_path) or "root",
            path=base_path,
            node_type="folder"
        )
        
        # Group events by file path
        path_events = self._group_events_by_path(events, base_path)
        
        # Build tree structure
        for file_path, event_list in path_events.items():
            self._add_path_to_tree(root, file_path, event_list, base_path)
        
        # Update folder statuses
        self._update_folder_status(root)
        
        return root
    
    def _group_events_by_path(self, events: List[FileEvent], base_path: str) -> Dict[str, List[FileEvent]]:
        """Group events by file path, filtering by base path if specified."""
        path_events = defaultdict(list)
        
        for event in events:
            file_path = event.file_path
            
            # Filter by base path if specified
            if base_path:
                if not file_path.startswith(base_path):
                    continue
                # Remove base path prefix
                file_path = file_path[len(base_path):].lstrip("/")
                if not file_path:  # Skip if this is the base path itself
                    continue
            
            path_events[file_path].append(event)
        
        return path_events
    
    def _add_path_to_tree(self, root: TreeNode, file_path: str, events: List[FileEvent], base_path: str):
        """Add a file path to the tree structure."""
        if not file_path:
            return
        
        # Split path into components
        path_parts = file_path.split("/")
        current_node = root
        
        # Build intermediate directories
        current_path = base_path
        for i, part in enumerate(path_parts):
            if not part:  # Skip empty parts
                continue
                
            current_path = os.path.join(current_path, part) if current_path else part
            
            # Check if this part already exists as a child
            existing_child = current_node.find_child(part)
            
            if existing_child:
                current_node = existing_child
            else:
                # Determine if this is a file or folder
                is_file = (i == len(path_parts) - 1)  # Last component is a file
                node_type = "file" if is_file else "folder"
                
                # Create new node
                new_node = TreeNode(
                    name=part,
                    path=current_path,
                    node_type=node_type
                )
                
                # If this is a file, update with event data
                if is_file and events:
                    self._update_file_node(new_node, events)
                
                current_node.add_child(new_node)
                current_node = new_node
    
    def _update_file_node(self, node: TreeNode, events: List[FileEvent]):
        """Update file node with data from events."""
        if not events:
            return
        
        # Sort events by timestamp (newest first)
        sorted_events = sorted(events, key=lambda e: e.timestamp, reverse=True)
        latest_event = sorted_events[0]
        
        # Update node properties
        node.latest_event = latest_event
        node.size = latest_event.file_size
        node.last_sync = latest_event.timestamp.isoformat()
        
        # Determine status based on latest event
        action = latest_event.action.lower()
        if action == "error":
            node.status = "error"
        elif action == "conflict":
            node.status = "conflict"
        elif action in ["added", "updated"]:
            node.status = "synced"
        elif action == "skipped":
            node.status = "pending"
        else:
            node.status = "unknown"
    
    def _update_folder_status(self, node: TreeNode):
        """Update folder status based on children (recursive)."""
        if node.type == "file":
            return
        
        # First, update all children
        for child in node.children:
            self._update_folder_status(child)
        
        if not node.children:
            # Empty folder
            node.status = "unknown"
            return
        
        # Determine folder status based on children
        child_statuses = [child.status for child in node.children]
        
        # Priority: error > conflict > pending > synced > unknown
        if "error" in child_statuses:
            node.status = "error"
        elif "conflict" in child_statuses:
            node.status = "conflict"
        elif "pending" in child_statuses:
            node.status = "pending"
        elif "synced" in child_statuses:
            node.status = "synced"
        else:
            node.status = "unknown"
        
        # Update folder metadata
        total_size = sum(child.size for child in node.children if child.type == "file")
        node.size = total_size
        
        # Latest sync time from children
        child_sync_times = [
            child.last_sync for child in node.children 
            if child.last_sync and child.type == "file"
        ]
        if child_sync_times:
            # Get the most recent sync time
            node.last_sync = max(child_sync_times)
    
    def get_statistics(self, root: TreeNode) -> Dict[str, int]:
        """Get statistics about the tree."""
        stats = {"files": 0, "folders": 0, "total_size": 0}
        
        def count_recursive(node: TreeNode):
            if node.type == "file":
                stats["files"] += 1
                stats["total_size"] += node.size
            else:
                stats["folders"] += 1
            
            for child in node.children:
                count_recursive(child)
        
        count_recursive(root)
        return stats
    
    def filter_tree(self, root: TreeNode, filter_func) -> TreeNode:
        """Filter tree nodes based on a function."""
        if not filter_func(root):
            return None
        
        filtered_root = TreeNode(root.name, root.path, root.type)
        filtered_root.size = root.size
        filtered_root.last_sync = root.last_sync
        filtered_root.status = root.status
        filtered_root.latest_event = root.latest_event
        
        for child in root.children:
            filtered_child = self.filter_tree(child, filter_func)
            if filtered_child:
                filtered_root.add_child(filtered_child)
        
        return filtered_root
    
    def search_tree(self, root: TreeNode, search_term: str) -> List[TreeNode]:
        """Search for nodes matching a term."""
        results = []
        
        def search_recursive(node: TreeNode):
            if search_term.lower() in node.name.lower():
                results.append(node)
            
            for child in node.children:
                search_recursive(child)
        
        search_recursive(root)
        return results
    
    def get_path_node(self, root: TreeNode, target_path: str) -> Optional[TreeNode]:
        """Get a specific node by path."""
        if root.path == target_path:
            return root
        
        for child in root.children:
            result = self.get_path_node(child, target_path)
            if result:
                return result
        
        return None
