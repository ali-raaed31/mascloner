"""Streamlit breadcrumb-style folder picker."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

import streamlit as st

logger = logging.getLogger(__name__)


@dataclass
class PickerConfig:
    remote_name: str
    label: str
    placeholder: str


class FolderPicker:
    """Progressive breadcrumb picker for remote folders."""

    def __init__(self, api_client, state_key: str, config: PickerConfig):
        self.api = api_client
        self.state_key = state_key
        self.config = config

    def render(self) -> str:
        state = self._ensure_state()
        segments = [segment for segment in state["segments"] if segment]

        st.markdown(f"**{self.config.label} path**")
        breadcrumb = " › ".join(segments) if segments else "root"
        st.caption(f"Current selection: `{breadcrumb}`")

        total_levels = len(state["segments"]) + 1
        columns = st.columns(total_levels if total_levels > 0 else 1)
        for level in range(total_levels):
            with columns[level]:
                self._render_dropdown(level)

        manual_key = f"{self.state_key}_manual_override"
        manual_value = st.text_input(
            "Manual override",
            key=manual_key,
            placeholder=self.config.placeholder,
            help="Optional: paste a full path if you already know it",
        ).strip()

        if manual_value:
            logger.info(
                "FolderPicker: manual override remote=%s value=%s",
                self.config.remote_name,
                manual_value,
            )
            return manual_value

        final_segments = [segment for segment in self._ensure_state()["segments"] if segment]
        return "/".join(final_segments)

    def _render_dropdown(self, level: int):
        state = self._ensure_state()
        segments = state["segments"]

        parent_segments = [segment for segment in segments[:level] if segment]
        parent_path = "/".join(parent_segments)
        options = self._load_options(parent_path)

        current_value = segments[level] if level < len(segments) else ""
        choices = [""] + options

        select_key = f"{self.state_key}_level_{level}"
        selection = st.selectbox(
            f"Level {level + 1}",
            choices,
            index=choices.index(current_value) if current_value in choices else 0,
            key=select_key,
        )

        new_segments = parent_segments + ([selection] if selection else [])
        st.session_state["breadcrumb_picker_state"][self.state_key]["segments"] = new_segments

    def _load_options(self, path: str) -> List[str]:
        state = self._ensure_state()
        cache = state["children_cache"]
        if path in cache:
            return cache[path]

        logger.info("FolderPicker: loading remote=%s path='%s'", self.config.remote_name, path)
        response = (
            self.api.browse_folders(self.config.remote_name, path=path)
            if path
            else self.api.browse_folders(self.config.remote_name)
        )

        options: List[str] = []
        if response and (response.get("success") or response.get("status") == "success"):
            for entry in response.get("folders", []):
                if not entry:
                    continue
                parts = entry.split("/")
                child = parts[-1]
                options.append(child)
        else:
            logger.warning(
                "FolderPicker: failed to load folders remote=%s path='%s' response=%s",
                self.config.remote_name,
                path,
                response,
            )
            st.warning(f"Could not load folders for `{path or 'root'}`")

        options = sorted(set(options))
        cache[path] = options
        return options

    def _ensure_state(self) -> Dict[str, List[str]]:
        picker_state = st.session_state.setdefault("breadcrumb_picker_state", {})
        state = picker_state.get(self.state_key)
        if not state or state.get("remote") != self.config.remote_name:
            state = {
                "remote": self.config.remote_name,
                "segments": [],
                "children_cache": {},
            }
            picker_state[self.state_key] = state
            st.session_state[f"{self.state_key}_manual_override"] = ""
        return state
