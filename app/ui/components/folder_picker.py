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
        levels = state["levels"]

        st.markdown(f"**{self.config.label} path**")
        breadcrumb = " › ".join(self._display_label(path) for path in levels) if levels else "root"
        st.caption(f"Current selection: `{breadcrumb}`")

        dropdown_specs = []
        for index, current_path in enumerate(levels):
            parent_path = levels[index - 1] if index > 0 else ""
            options = self._load_options(parent_path)
            if current_path and current_path not in options:
                logger.warning(
                    "FolderPicker: previously selected path '%s' missing under '%s', resetting",
                    current_path,
                    parent_path,
                )
                self._update_levels(levels[:index])
                self._trigger_rerun()
            dropdown_specs.append((index, parent_path, options, current_path))

        parent_path = levels[-1] if levels else ""
        next_options = self._load_options(parent_path)
        if next_options:
            dropdown_specs.append((len(levels), parent_path, next_options, ""))

        if not dropdown_specs:
            dropdown_specs.append((0, "", self._load_options(""), ""))

        columns = st.columns(len(dropdown_specs))
        for column, (level_idx, parent, options, current_value) in zip(columns, dropdown_specs):
            with column:
                options_with_current = options[:]
                if current_value and current_value not in options_with_current:
                    options_with_current.append(current_value)
                options_with_current = sorted(set(options_with_current))
                choices = [""] + options_with_current

                try:
                    index = choices.index(current_value)
                except ValueError:
                    index = 0

                selection = st.selectbox(
                    f"Level {level_idx + 1}",
                    choices,
                    index=index,
                    format_func=self._display_label,
                    key=f"{self.state_key}_level_{level_idx}",
                )

                if selection != current_value:
                    new_levels = levels[:level_idx]
                    if selection:
                        new_levels.append(selection)
                    self._update_levels(new_levels)
                    self._trigger_rerun()

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

        return "/".join(self._ensure_state()["levels"])

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
                if entry:
                    options.append(entry)
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
                "levels": [],
                "children_cache": {},
            }
            picker_state[self.state_key] = state
            st.session_state[f"{self.state_key}_manual_override"] = ""
        return state

    def _update_levels(self, levels: List[str]) -> None:
        st.session_state.setdefault("breadcrumb_picker_state", {})[self.state_key]["levels"] = levels

    @staticmethod
    def _display_label(path: str) -> str:
        if not path:
            return "—"
        parts = path.split("/")
        if len(parts) == 1:
            return parts[0]
        return f"{parts[-1]} ({'/'.join(parts[:-1])})"

    @staticmethod
    def _trigger_rerun() -> None:
        rerun_fn = getattr(st, "experimental_rerun", None) or getattr(st, "rerun", None)
        if rerun_fn:
            rerun_fn()
