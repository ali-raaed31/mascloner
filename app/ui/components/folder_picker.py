"""Streamlit folder picker with modal tree explorer for MasCloner."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import streamlit as st

logger = logging.getLogger(__name__)


@dataclass
class PickerConfig:
    remote_name: str
    label: str
    placeholder: str


class FolderPicker:
    """Reusable folder picker with modal tree explorer."""

    _instances: Dict[str, "FolderPicker"] = {}
    _style_injected: bool = False

    def __init__(
        self,
        api_client,
        state_key: str,
        config: PickerConfig,
    ):
        self.api = api_client
        self.state_key = state_key
        self.config = config
        FolderPicker._instances[state_key] = self

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def render(self) -> str:
        """Render input row and return current selection."""
        state = self._ensure_picker_state()
        manual_key = f"{self.state_key}_manual"

        col_path, col_browse, col_clear = st.columns([0.65, 0.23, 0.12])
        with col_path:
            st.text_input(
                f"{self.config.label} path",
                key=manual_key,
                placeholder=self.config.placeholder,
            )
        with col_browse:
            st.button(
                f"🌲 Browse {self.config.label}",
                key=f"{self.state_key}_open_modal",
                use_container_width=True,
                on_click=self._open_modal,
            )
        with col_clear:
            st.button(
                "Clear",
                key=f"{self.state_key}_clear",
                use_container_width=True,
                on_click=self._clear_selection,
            )

        selected_value = st.session_state.get(manual_key, "").strip()
        state["selected_path"] = selected_value

        if selected_value:
            st.caption(f"Selected {self.config.label} path: `{selected_value}`")

        return selected_value

    # ------------------------------------------------------------------
    # Modal lifecycle
    # ------------------------------------------------------------------
    @classmethod
    def render_active_modal(cls):
        """Render modal for whichever picker is open."""
        modal_state = st.session_state.get("folder_modal")
        if not modal_state or not modal_state.get("open"):
            return

        state_key = modal_state.get("state_key")
        picker = cls._instances.get(state_key)
        if not picker:
            return

        picker._render_modal()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_picker_state(self) -> Dict[str, str]:
        if "folder_picker_states" not in st.session_state:
            st.session_state["folder_picker_states"] = {}
        picker_state = st.session_state["folder_picker_states"].get(self.state_key)
        if not picker_state or picker_state.get("remote") != self.config.remote_name:
            picker_state = {
                "remote": self.config.remote_name,
                "selected_path": "",
            }
            st.session_state["folder_picker_states"][self.state_key] = picker_state
            manual_key = f"{self.state_key}_manual"
            st.session_state[manual_key] = ""
        return picker_state

    def _get_tree_state(self) -> Dict[str, any]:

        tree_states = st.session_state.setdefault("folder_tree_states", {})
        state = tree_states.get(self.state_key)
        if not state or state.get("remote") != self.config.remote_name:
            state = {
                "remote": self.config.remote_name,
                "nodes": {},
                "expanded": set(),
                "selected_temp": "",
                "last_error": None,
            }
            tree_states[self.state_key] = state
        return state

    def _open_modal(self):
        st.session_state["folder_modal"] = {
            "open": True,
            "state_key": self.state_key,
        }

    def _clear_selection(self):
        manual_key = f"{self.state_key}_manual"
        st.session_state[manual_key] = ""
        picker_state = self._ensure_picker_state()
        picker_state["selected_path"] = ""
        tree_state = self._get_tree_state()
        tree_state["selected_temp"] = ""

    # Modal rendering ---------------------------------------------------
    def _render_modal(self):
        self._inject_modal_style()
        picker_state = self._ensure_picker_state()
        tree_state = self._get_tree_state()

        if not tree_state.get("selected_temp"):
            tree_state["selected_temp"] = picker_state.get("selected_path", "")

        self._ensure_children_loaded("")

        st.markdown("<div class='mc-modal-overlay'>", unsafe_allow_html=True)
        container = st.container()
        with container:
            st.markdown("<div class='mc-modal-box'>", unsafe_allow_html=True)
            st.subheader(f"{self.config.label} Folder Explorer")
            st.caption("Expand folders, select one, then confirm below.")

            st.markdown("<div class='mc-modal-scroll'>", unsafe_allow_html=True)
            self._render_tree_nodes("")
            st.markdown("</div>", unsafe_allow_html=True)

            current = tree_state.get("selected_temp", "")
            st.markdown(
                f"<div class='mc-modal-selected'>Current selection: "
                f"{'`' + current + '`' if current else 'None selected'}</div>",
                unsafe_allow_html=True,
            )

            col_close, col_clear, col_use = st.columns([0.3, 0.35, 0.35])
            with col_close:
                if st.button("Close", key=f"{self.state_key}_modal_close"):
                    self._close_modal()
                    st.experimental_rerun()
            with col_clear:
                if st.button("Clear selection", key=f"{self.state_key}_modal_clear"):
                    tree_state["selected_temp"] = ""
                    picker_state["selected_path"] = ""
                    manual_key = f"{self.state_key}_manual"
                    st.session_state[manual_key] = ""
            with col_use:
                if st.button(
                    "Use folder",
                    key=f"{self.state_key}_modal_use",
                    type="primary",
                    disabled=not current,
                ):
                    picker_state["selected_path"] = current
                    manual_key = f"{self.state_key}_manual"
                    st.session_state[manual_key] = current
                    self._close_modal()
                    st.experimental_rerun()

            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    def _close_modal(self):
        modal_state = st.session_state.setdefault("folder_modal", {})
        modal_state["open"] = False

    # Tree rendering ----------------------------------------------------
    def _render_tree_nodes(self, path: str, level: int = 0):
        children = self._ensure_children_loaded(path)
        tree_state = self._get_tree_state()

        if not children:
            if path and tree_state.get("last_error"):
                st.warning(f"Could not load subfolders for `{path}`")
            return

        indent = "\u2003" * level
        for child in children:
            child_path = f"{path}/{child}".strip("/")
            child_key = f"{self.state_key}_{child_path}".replace(" ", "_").replace("/", "_")
            child_state = tree_state["nodes"].get(child_path, {"children": [], "fetched": False})
            expanded = child_path in tree_state["expanded"]
            has_children = bool(child_state.get("children")) if child_state.get("fetched") else True

            cols = st.columns([0.12, 0.68, 0.2], gap="small")
            toggle_label = f"{indent}{'▾' if expanded else '▸'}"
            select_label = f"{indent}{'📂' if expanded else '📁'} {child}"

            with cols[0]:
                if st.button(
                    toggle_label,
                    key=f"{child_key}_toggle",
                    disabled=not has_children,
                ):
                    if expanded:
                        tree_state["expanded"].discard(child_path)
                    else:
                        tree_state["expanded"].add(child_path)
                        self._ensure_children_loaded(child_path)

            with cols[1]:
                if st.button(
                    select_label,
                    key=f"{child_key}_select",
                ):
                    tree_state["selected_temp"] = child_path

            with cols[2]:
                if child_path == tree_state.get("selected_temp"):
                    st.success("Selected", icon="✅")
                elif not has_children and child_state.get("fetched"):
                    st.caption("Empty")
                else:
                    st.write("")

            if expanded:
                self._render_tree_nodes(child_path, level + 1)

    # Data loading ------------------------------------------------------
    def _ensure_children_loaded(self, path: str) -> List[str]:
        tree_state = self._get_tree_state()
        node = tree_state["nodes"].get(path)
        if node and node.get("fetched"):
            return node["children"]

        try:
            response = self.api.browse_folders(self.config.remote_name, path=path) if path else self.api.browse_folders(self.config.remote_name)
            if response and (response.get("success") or response.get("status") == "success"):
                children = sorted(response.get("folders", []))
                tree_state["nodes"][path] = {"children": children, "fetched": True}
                tree_state["last_error"] = None
                logger.info(
                    "UI: loaded %d children for remote=%s path='%s'",
                    len(children),
                    self.config.remote_name,
                    path or "/",
                )
                return children
            tree_state["nodes"][path] = {"children": [], "fetched": True}
            tree_state["last_error"] = response
            logger.warning(
                "UI: failed to load children remote=%s path='%s' response=%s",
                self.config.remote_name,
                path or "/",
                response,
            )
            return []
        except Exception as exc:  # pragma: no cover - defensive logging
            tree_state["nodes"][path] = {"children": [], "fetched": True}
            tree_state["last_error"] = str(exc)
            logger.exception(
                "UI: error loading children remote=%s path='%s'",
                self.config.remote_name,
                path or "/",
            )
            return []

    # Styling -----------------------------------------------------------
    @classmethod
    def _inject_modal_style(cls):
        if cls._style_injected:
            return
        st.markdown(
            """
            <style>
            .mc-modal-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(10, 13, 23, 0.72);
                z-index: 1000;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .mc-modal-box {
                width: min(92vw, 720px);
                max-height: 85vh;
                background: #0f172a;
                border-radius: 18px;
                padding: 24px;
                box-shadow: 0 24px 60px rgba(15, 23, 42, 0.45);
                border: 1px solid rgba(148, 163, 184, 0.18);
                display: flex;
                flex-direction: column;
            }
            .mc-modal-scroll {
                margin-top: 16px;
                padding: 8px 12px;
                border-radius: 12px;
                border: 1px solid rgba(148, 163, 184, 0.18);
                background: rgba(15, 23, 42, 0.6);
                overflow-y: auto;
                flex: 1;
            }
            .mc-modal-selected {
                margin-top: 12px;
                font-size: 0.9rem;
                color: rgba(226, 232, 240, 0.85);
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        cls._style_injected = True
