# web_ui/server.py
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import streamlit as st


# -----------------------------
# Native folder picker (LOCAL)
# -----------------------------
def pick_folder_native(title: str = "Select repo folder") -> str:
    """
    Opens a native OS folder picker (Windows/macOS/Linux) via Tkinter.
    Works only when Streamlit is running locally on the same machine.
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    folder = filedialog.askdirectory(title=title)
    root.destroy()
    return folder


def read_repo_from_disk(folder: str) -> dict[str, bytes]:
    """
    Reads all files under folder into memory.
    Returns dict: relative_posix_path -> bytes
    """
    repo = {}
    base = Path(folder)

    # basic ignore list (tweak as you want)
    ignore_dirs = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules", ".idea", ".vscode"}
    ignore_files = {".DS_Store"}

    for p in base.rglob("*"):
        if p.is_dir():
            continue

        # skip ignored dirs
        if any(part in ignore_dirs for part in p.parts):
            continue

        if p.name in ignore_files:
            continue

        rel = p.relative_to(base).as_posix()
        try:
            repo[rel] = p.read_bytes()
        except Exception:
            # if a file can't be read (permission etc.), skip it
            continue

    return repo


# -----------------------------
# Tree helpers
# -----------------------------
def build_tree(paths: list[str]) -> dict:
    root: dict = {}
    for p in paths:
        parts = list(PurePosixPath(p).parts)
        cur = root
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            if is_last:
                cur.setdefault(part, None)
            else:
                cur = cur.setdefault(part, {})
    return root


def get_node(tree: dict, dir_path: PurePosixPath) -> dict:
    cur = tree
    if str(dir_path) in ("", "."):
        return cur
    for part in dir_path.parts:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            return {}
        cur = nxt
    return cur


def list_dir(tree: dict, dir_path: PurePosixPath):
    node = get_node(tree, dir_path)
    dirs = sorted([k for k, v in node.items() if isinstance(v, dict)])
    files = sorted([k for k, v in node.items() if v is None])
    return dirs, files


def join_path(dir_path: PurePosixPath, name: str) -> str:
    if str(dir_path) in ("", "."):
        return name
    return str(dir_path / name)


# -----------------------------
# Stepper state + UI
# -----------------------------
@dataclass(frozen=True)
class Step:
    key: str
    label: str


STEPS = [
    Step("repo", "Select repo"),
    Step("code", "Select code file"),
    Step("test", "Select test file"),
    Step("config", "Configure workflow"),
]


def init_state():
    st.session_state.setdefault("step_idx", 0)

    st.session_state.setdefault("repo_folder", None)  # absolute folder path on disk
    st.session_state.setdefault("repo_files", {})     # dict[path -> bytes]
    st.session_state.setdefault("repo_tree", {})      # nested dict

    st.session_state.setdefault("code_dir", PurePosixPath("."))
    st.session_state.setdefault("test_dir", PurePosixPath("."))

    st.session_state.setdefault("selected_code_path", None)
    st.session_state.setdefault("selected_test_path", None)

    st.session_state.setdefault("chunk_strategy", "AST")
    st.session_state.setdefault("workflow_strategy", "oracle")
    st.session_state.setdefault("workers", 3)
    st.session_state.setdefault("concern", "Correctness")


def goto_step(idx: int):
    st.session_state.step_idx = max(0, min(idx, len(STEPS) - 1))


def can_advance():
    step = STEPS[st.session_state.step_idx].key
    if step == "repo":
        return bool(st.session_state.repo_files)
    if step == "code":
        return st.session_state.selected_code_path is not None
    if step == "test":
        return st.session_state.selected_test_path is not None
    return True


def stepper_header():
    idx = st.session_state.step_idx
    total = len(STEPS)
    st.progress((idx + 1) / total)

    cols = st.columns(total)
    for i, s in enumerate(STEPS):
        done = i < idx
        active = i == idx
        prefix = "✅" if done else ("➡️" if active else "○")
        with cols[i]:
            st.markdown(f"**{prefix} {s.label}**")

    st.divider()


# -----------------------------
# Pages
# -----------------------------
def page_select_repo():
    st.subheader("Select repo (directory only)")

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("Pick repo folder", type="primary"):
            folder = pick_folder_native()
            if folder:
                st.session_state.repo_folder = folder

                repo_files = read_repo_from_disk(folder)
                st.session_state.repo_files = repo_files
                st.session_state.repo_tree = build_tree(list(repo_files.keys()))

                # Reset downstream selections
                st.session_state.code_dir = PurePosixPath(".")
                st.session_state.test_dir = PurePosixPath(".")
                st.session_state.selected_code_path = None
                st.session_state.selected_test_path = None

    with c2:
        if st.session_state.repo_folder:
            st.write(f"Selected folder: `{st.session_state.repo_folder}`")

    if st.session_state.repo_files:
        st.success(f"Loaded {len(st.session_state.repo_files)} files.")
        with st.expander("Preview file list"):
            preview = "\n".join(sorted(st.session_state.repo_files.keys())[:200])
            st.code(preview if preview else "(none)")
            if len(st.session_state.repo_files) > 200:
                st.caption("Showing first 200 files.")
    else:
        st.info("No folder selected yet.")


def file_picker(title: str, dir_state_key: str, selected_state_key: str, file_filter_fn):
    st.subheader(title)

    tree = st.session_state.repo_tree
    if not tree:
        st.warning("Pick a repo folder first.")
        return

    cur_dir: PurePosixPath = st.session_state[dir_state_key]

    parts = cur_dir.parts if str(cur_dir) not in ("", ".") else ()
    breadcrumb = " / ".join(parts) if parts else "(root)"
    st.caption(f"Current folder: **{breadcrumb}**")

    if st.button("⬅️ Up", disabled=(str(cur_dir) in ("", ".")), key=f"up_{dir_state_key}"):
        parent = cur_dir.parent
        st.session_state[dir_state_key] = parent if str(parent) not in ("",) else PurePosixPath(".")
        return

    dirs, files = list_dir(tree, cur_dir)
    left, right = st.columns(2)

    with left:
        st.markdown("**Folders**")
        if not dirs:
            st.caption("No subfolders here.")
        for d in dirs:
            if st.button(f"📁 {d}", key=f"dir_{dir_state_key}_{breadcrumb}_{d}"):
                st.session_state[dir_state_key] = (cur_dir / d) if str(cur_dir) not in ("", ".") else PurePosixPath(d)
                return

    with right:
        st.markdown("**Files**")
        eligible = [f for f in files if file_filter_fn(f)]
        if not eligible:
            st.caption("No matching files in this folder.")
        else:
            selected = st.session_state[selected_state_key]
            for f in eligible:
                full_path = join_path(cur_dir, f)
                checked = (selected == full_path)
                label = f"✅ {f}" if checked else f"📄 {f}"
                if st.button(label, key=f"file_{selected_state_key}_{breadcrumb}_{f}"):
                    st.session_state[selected_state_key] = full_path
                    return

    chosen = st.session_state[selected_state_key]
    if chosen:
        st.success(f"Selected: {chosen}")


def page_select_code_file():
    def is_code(name: str) -> bool:
        exts = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rs"}
        return PurePosixPath(name).suffix.lower() in exts

    file_picker(
        "Select a code file",
        dir_state_key="code_dir",
        selected_state_key="selected_code_path",
        file_filter_fn=is_code,
    )


def page_select_test_file():
    def is_test(name: str) -> bool:
        p = PurePosixPath(name)
        if p.suffix.lower() == ".py" and ("test" in p.stem.lower() or p.name.lower().startswith("test_")):
            return True
        if p.suffix.lower() in {".js", ".ts"} and ("test" in p.stem.lower() or p.stem.lower().endswith(".spec")):
            return True
        return p.suffix.lower() in {".py", ".js", ".ts"}

    file_picker(
        "Select a test file",
        dir_state_key="test_dir",
        selected_state_key="selected_test_path",
        file_filter_fn=is_test,
    )


def page_configure():
    st.subheader("Configure workflow")

    # Chunking strategy (segmented control)
    st.markdown("**Chunking strategy**")
    st.session_state.chunk_strategy = st.segmented_control(
        label="Chunking strategy",
        options=["AST", "LLM"],
        default=st.session_state.chunk_strategy,
        key="chunk_strategy_seg",
        label_visibility="collapsed",
    )

    # Workflow strategy (segmented control)
    st.markdown("**Workflow strategy**")
    st.session_state.workflow_strategy = st.segmented_control(
        label="Workflow strategy",
        options=["oracle", "mutation"],
        default=st.session_state.workflow_strategy,
        key="workflow_strategy_seg",
        label_visibility="collapsed",
    )

    st.markdown("**Workers**")
    c1, c2, c3 = st.columns([1, 2, 6])
    with c1:
        if st.button("−", key="workers_minus") and st.session_state.workers > 1:
            st.session_state.workers -= 1
    with c2:
        st.session_state.workers = st.number_input(
            "Workers",
            min_value=1,
            max_value=128,
            value=int(st.session_state.workers),
            step=1,
            label_visibility="collapsed",
        )
    with c3:
        if st.button("+", key="workers_plus") and st.session_state.workers < 128:
            st.session_state.workers += 1

    st.markdown("**Primary concern**")
    concerns = ["Privacy", "Security", "Correctness", "Performance", "Cost", "Maintainability"]
    st.session_state.concern = st.radio(
        "Concerns",
        concerns,
        index=concerns.index(st.session_state.concern) if st.session_state.concern in concerns else 2,
        label_visibility="collapsed",
    )

    st.divider()
    run = st.button("Run workflow", type="primary", use_container_width=True)

    if run:
        if not st.session_state.selected_code_path or not st.session_state.selected_test_path:
            st.error("Pick both a code file and a test file first.")
            return

        st.success("Workflow started (stub).")
        st.json(
            {
                "code_file": st.session_state.selected_code_path,
                "test_file": st.session_state.selected_test_path,
                "chunking": st.session_state.chunk_strategy,
                "workflow": st.session_state.workflow_strategy,
                "workers": int(st.session_state.workers),
                "concern": st.session_state.concern,
            }
        )

# -----------------------------
# App shell
# -----------------------------
def main():
    st.set_page_config(page_title="Repo Workflow Stepper", page_icon="🧩", layout="wide")
    init_state()

    stepper_header()

    step_key = STEPS[st.session_state.step_idx].key
    if step_key == "repo":
        page_select_repo()
    elif step_key == "code":
        page_select_code_file()
    elif step_key == "test":
        page_select_test_file()
    elif step_key == "config":
        page_configure()

    st.divider()

    back_col, _, next_col = st.columns([1, 6, 1])

    with back_col:
        st.button(
            "Back",
            on_click=goto_step,
            args=(st.session_state.step_idx - 1,),
            disabled=(st.session_state.step_idx == 0),
            use_container_width=True,
        )

    with next_col:
        st.button(
            "Next",
            on_click=goto_step,
            args=(st.session_state.step_idx + 1,),
            disabled=(st.session_state.step_idx == len(STEPS) - 1 or not can_advance()),
            use_container_width=True,
        )

    with st.sidebar:
        st.markdown("### Steps")
        for i, s in enumerate(STEPS):
            locked = False
            if s.key in ("code", "test", "config") and not st.session_state.repo_files:
                locked = True
            if s.key in ("test", "config") and not st.session_state.selected_code_path:
                locked = True
            if s.key == "config" and not st.session_state.selected_test_path:
                locked = True

            label = s.label
            if i < st.session_state.step_idx:
                label = f"✅ {label}"
            elif i == st.session_state.step_idx:
                label = f"➡️ {label}"

            st.button(label, disabled=locked, on_click=goto_step, args=(i,), use_container_width=True)


if __name__ == "__main__":
    main()
