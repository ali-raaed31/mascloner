"""
MasCloner File Tree Page

Interactive file tree visualization with sync status.
"""

import streamlit as st
import httpx
from typing import Dict, Any, Optional, List
import json

# Page config
st.set_page_config(
    page_title="File Tree - MasCloner",
    page_icon="🌳",
    layout="wide"
)

# Import API client
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import APIClient

# Initialize API client
api = APIClient()

st.title("🌳 File Tree Viewer")
st.markdown("Explore your synced files with real-time status indicators")

# Check API connection
status = api.get("/status")
if not status:
    st.error("Cannot connect to MasCloner API")
    st.stop()

# Sidebar controls
with st.sidebar:
    st.header("🎛️ Tree Controls")
    
    # Base path filter
    base_path = st.text_input(
        "🔍 Base Path Filter",
        value="",
        placeholder="folder/subfolder",
        help="Filter tree to show only files under this path"
    )
    
    # Status filter
    status_filter = st.multiselect(
        "📊 Status Filter",
        ["synced", "pending", "error", "conflict", "unknown"],
        default=["synced", "pending", "error", "conflict"],
        help="Show only items with selected statuses"
    )
    
    # Size filter
    st.subheader("📏 Size Filter")
    size_filter_enabled = st.checkbox("Enable size filtering")
    
    if size_filter_enabled:
        size_min = st.number_input("Min size (bytes)", min_value=0, value=0)
        size_max = st.number_input("Max size (bytes)", min_value=0, value=1000000000)  # 1GB default
    else:
        size_min, size_max = 0, float('inf')
    
    # Search
    st.subheader("🔍 Search")
    search_term = st.text_input(
        "Search files/folders",
        placeholder="Enter filename or pattern"
    )
    
    # Refresh button
    if st.button("🔄 Refresh Tree", type="primary", use_container_width=True):
        st.rerun()

# Status indicator helper functions
def get_status_emoji(status: str) -> str:
    """Get emoji for status."""
    return {
        "synced": "✅",
        "pending": "⏳",
        "error": "❌",
        "conflict": "⚠️",
        "unknown": "❓"
    }.get(status, "❓")

def get_status_color(status: str) -> str:
    """Get color for status."""
    return {
        "synced": "green",
        "pending": "orange", 
        "error": "red",
        "conflict": "yellow",
        "unknown": "gray"
    }.get(status, "gray")

def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    if size_bytes == 0:
        return "0 B"
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"

def should_show_node(node: Dict[str, Any], status_filter: List[str], size_min: int, size_max: int, search_term: str) -> bool:
    """Check if a node should be displayed based on filters."""
    
    # Status filter
    if node["status"] not in status_filter:
        return False
    
    # Size filter (only for files)
    if node["type"] == "file":
        if not (size_min <= node["size"] <= size_max):
            return False
    
    # Search filter
    if search_term and search_term.lower() not in node["name"].lower():
        # Check if any child matches (for folders)
        if node["type"] == "folder":
            return any(should_show_node(child, status_filter, size_min, size_max, search_term) 
                      for child in node.get("children", []))
        return False
    
    return True

def render_tree_node(node: Dict[str, Any], level: int = 0, status_filter: List[str] = None, 
                    size_min: int = 0, size_max: int = float('inf'), search_term: str = "") -> bool:
    """Render a tree node recursively. Returns True if node was displayed."""
    
    if status_filter is None:
        status_filter = ["synced", "pending", "error", "conflict", "unknown"]
    
    # Check if this node should be shown
    if not should_show_node(node, status_filter, size_min, size_max, search_term):
        # For folders, check if any children should be shown
        if node["type"] == "folder":
            children_shown = []
            for child in node.get("children", []):
                if render_tree_node(child, level + 1, status_filter, size_min, size_max, search_term):
                    children_shown.append(child)
            
            if children_shown:
                # Show folder header if children are visible
                _render_node_header(node, level)
                return True
        return False
    
    # Render this node
    _render_node_header(node, level)
    
    # Render children for folders
    if node["type"] == "folder":
        children_shown = 0
        for child in node.get("children", []):
            if render_tree_node(child, level + 1, status_filter, size_min, size_max, search_term):
                children_shown += 1
        
        # Show empty folder message if no children shown but folder matches filter
        if children_shown == 0 and should_show_node(node, status_filter, size_min, size_max, search_term):
            st.write("  " * (level + 1) + "📂 *Empty folder*")
    
    return True

def _render_node_header(node: Dict[str, Any], level: int):
    """Render the header for a tree node."""
    indent = "  " * level
    status_emoji = get_status_emoji(node["status"])
    
    if node["type"] == "file":
        # File node
        size_str = format_file_size(node["size"])
        last_sync = node.get("last_sync", "Never")
        if last_sync and last_sync != "Never":
            last_sync = last_sync[:19].replace("T", " ")  # Format datetime
        
        # Use columns for better layout
        col1, col2, col3, col4 = st.columns([6, 2, 2, 2])
        
        with col1:
            st.write(f"{indent}📄 **{node['name']}**")
        with col2:
            st.write(f"{status_emoji} {node['status']}")
        with col3:
            st.write(size_str)
        with col4:
            st.write(last_sync)
    
    else:
        # Folder node
        file_count = count_files_in_folder(node)
        folder_size = format_file_size(node["size"])
        
        # Use expander for folders
        with st.expander(f"{indent}📁 **{node['name']}** ({file_count} files, {folder_size}) {status_emoji}", expanded=level < 2):
            if node.get("last_sync"):
                st.caption(f"Last sync: {node['last_sync'][:19].replace('T', ' ')}")

def count_files_in_folder(folder_node: Dict[str, Any]) -> int:
    """Count total files in a folder recursively."""
    count = 0
    for child in folder_node.get("children", []):
        if child["type"] == "file":
            count += 1
        else:
            count += count_files_in_folder(child)
    return count

# Main content area
try:
    # Get tree data from API
    with st.spinner("Loading file tree..."):
        tree_response = api.get(f"/tree?path={base_path}")
    
    if not tree_response:
        st.error("Failed to load file tree data")
        st.stop()
    
    # Display tree statistics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📁 Total Folders", tree_response["total_folders"])
    with col2:
        st.metric("📄 Total Files", tree_response["total_files"])
    with col3:
        total_size = tree_response["root"]["size"]
        st.metric("💾 Total Size", format_file_size(total_size))
    with col4:
        root_status = tree_response["root"]["status"]
        st.metric("📊 Overall Status", f"{get_status_emoji(root_status)} {root_status}")
    
    st.markdown("---")
    
    # Tree view header
    st.subheader("📂 File Tree")
    
    # Table headers for file view
    if tree_response["total_files"] > 0:
        col1, col2, col3, col4 = st.columns([6, 2, 2, 2])
        with col1:
            st.write("**File/Folder**")
        with col2:
            st.write("**Status**")
        with col3:
            st.write("**Size**")
        with col4:
            st.write("**Last Sync**")
        
        st.markdown("---")
    
    # Render the tree
    root_node = tree_response["root"]
    
    if not root_node.get("children"):
        st.info("📂 No files found. Sync some files first to see them in the tree view.")
    else:
        # Apply filters and render tree
        nodes_shown = 0
        for child in root_node["children"]:
            if render_tree_node(child, 0, status_filter, size_min, size_max, search_term):
                nodes_shown += 1
        
        if nodes_shown == 0:
            st.info("🔍 No files match the current filters. Try adjusting your filter criteria.")

except Exception as e:
    st.error(f"Error loading file tree: {e}")
    st.info("Make sure the API server is running and try refreshing the page.")

# Footer with legend
st.markdown("---")
st.subheader("📖 Status Legend")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    **Sync Status:**
    - ✅ **Synced**: File successfully transferred
    - ⏳ **Pending**: File waiting to be synced
    - ❌ **Error**: Sync failed with error
    """)

with col2:
    st.markdown("""
    **Additional Status:**
    - ⚠️ **Conflict**: File conflict detected
    - ❓ **Unknown**: Status not determined
    """)

# Auto-refresh option
with st.sidebar:
    st.markdown("---")
    auto_refresh = st.checkbox("🔄 Auto-refresh every 30 seconds")

if auto_refresh:
    import time
    time.sleep(30)
    st.rerun()
