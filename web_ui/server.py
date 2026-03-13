"""
MORT Web UI — Streamlit interface for Mutation-Guided Oracle Refinement Testing.
Designed for local use only; has full access to all MORT modules.
"""

import concurrent.futures
import io
import json
import logging
import math
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import streamlit as st

# ─── Bootstrap: add MORT root to sys.path ─────────────────────────────────────
_MORT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _MORT_ROOT not in sys.path:
    sys.path.insert(0, _MORT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_MORT_ROOT, ".env"))

from constants import MAX_WORKERS, MODEL, MODEL_PROVIDER, ORACLE_OUTPUT_DIR, OUTPUT_DIR

# ─── Thread-local log routing ─────────────────────────────────────────────────
# Concurrent WorkflowRunner daemon threads can collide if they all patch the
# *global* sys.stdout (the second redirect overwrites the first, mixing logs
# and causing the first run's output to appear in the second run's log while
# the second run's result comes back as None).
#
# Fix: install a single GlobalLogRouter as sys.stdout once.  Each WorkflowRunner
# registers its LogCapture for its own thread via _log_thread_local.  We also
# monkey-patch ThreadPoolExecutor.submit so worker threads spawned by MORT's
# parallel processor inherit the same LogCapture automatically.

_log_thread_local = threading.local()
_orig_stdout = sys.stdout


class GlobalLogRouter:
    """Routes sys.stdout writes to per-thread LogCapture instances."""

    def write(self, text: str) -> int:
        cap = getattr(_log_thread_local, "capture", None)
        if cap is not None:
            return cap.write(text)
        return _orig_stdout.write(text)

    def flush(self) -> None:
        cap = getattr(_log_thread_local, "capture", None)
        if cap is not None and hasattr(cap, "flush"):
            cap.flush()
        else:
            _orig_stdout.flush()

    def __getattr__(self, name: str):
        return getattr(_orig_stdout, name)


_log_router = GlobalLogRouter()
sys.stdout = _log_router

# Patch ThreadPoolExecutor.submit so that MORT's worker threads inherit the
# caller thread's log capture (otherwise they'd fall through to _orig_stdout).
_orig_tpe_submit = concurrent.futures.ThreadPoolExecutor.submit


def _patched_tpe_submit(self_tpe, fn, *args, **kwargs):
    capture = getattr(_log_thread_local, "capture", None)
    if capture is None:
        return _orig_tpe_submit(self_tpe, fn, *args, **kwargs)

    def _wrapped(*a, **kw):
        _log_thread_local.capture = capture
        try:
            return fn(*a, **kw)
        finally:
            _log_thread_local.capture = None

    return _orig_tpe_submit(self_tpe, _wrapped, *args, **kwargs)


if concurrent.futures.ThreadPoolExecutor.submit is not _patched_tpe_submit:
    concurrent.futures.ThreadPoolExecutor.submit = _patched_tpe_submit

# ─── Domain constants ─────────────────────────────────────────────────────────
CONCERNS = ["Privacy", "Security", "Correctness", "Performance"]
CONCERN_LOWER = {c: c.lower() for c in CONCERNS}
CONCERN_ICONS = {
    "Privacy": "🔒",
    "Security": "🛡️",
    "Correctness": "✓",
    "Performance": "⚡",
}
CONCERN_DESCS = {
    "Privacy": "PII logging, data exposure, missing authorization",
    "Security": "SQL injection, XSS, auth bypass, input validation",
    "Correctness": "Off-by-one errors, null pointers, logic errors",
    "Performance": "Inefficient algorithms, memory leaks, N+1 queries",
}

CODE_EXTS = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rs"}
IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
    "node_modules", ".idea", ".vscode", ".chunk_cache", "outputs",
    "oracle_outputs", ".temp_testing", "htmlcov", ".tox",
}

# ─── Step definitions ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Step:
    key: str
    label: str
    icon: str


STEPS = [
    Step("repo",   "Repository", "📁"),
    Step("code",   "Code File",  "📄"),
    Step("test",   "Test File",  "🧪"),
    Step("config", "Configure",  "⚙️"),
]

# ─── CSS ──────────────────────────────────────────────────────────────────────
_CSS = """
<style>
[data-testid="stSidebar"] .stButton > button {
    border-radius: 6px;
    text-align: left;
    justify-content: flex-start;
    font-size: 0.9rem;
}
div[data-testid="metric-container"] {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(128, 128, 128, 0.18);
    border-radius: 10px;
    padding: 14px 18px;
}
.stTabs [data-baseweb="tab"] {
    font-weight: 600;
}
section.main .stButton > button {
    text-align: left;
    justify-content: flex-start;
}
</style>
"""


# ─── Live log capture (thread-safe) ───────────────────────────────────────────
class LogCapture:
    """Thread-safe stdout capture. Background thread writes; main thread reads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buf: list[str] = []

    def write(self, text: str) -> int:
        if text:
            with self._lock:
                self._buf.append(text)
        return len(text)

    def flush(self):
        pass

    def get_text(self) -> str:
        with self._lock:
            return "".join(self._buf)

    def get_recent_lines(self, n: int = 30) -> str:
        text = self.get_text()
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines[-n:])


# ─── Background workflow runner ────────────────────────────────────────────────
class WorkflowRunner:
    """Runs MORTWorkflow in a daemon thread. Poll `.done` / `.paused` to check state."""

    def __init__(self):
        self.log = LogCapture()
        self.result = None
        # Structured error info (set on exception)
        self.error_type: str | None = None
        self.error_msg: str | None = None
        self.error_tb: str | None = None
        self.done = False
        self._thread: threading.Thread | None = None
        # Oracle interactive-pause state
        self.paused = False                           # True while waiting for UI input
        self.pause_spec_path: str | None = None      # oracle spec file on disk
        self.pause_validated_path: str | None = None # where to write the edited version
        self._resume_event = threading.Event()

    def resume(self, validated_text: str | None = None):
        """
        Called from the UI thread. Optionally writes the user-edited oracle spec,
        then unblocks the background thread.
        """
        if validated_text is not None and self.pause_validated_path:
            os.makedirs(os.path.dirname(self.pause_validated_path), exist_ok=True)
            with open(self.pause_validated_path, "w", encoding="utf-8") as f:
                f.write(validated_text)
        self._resume_event.set()

    def _make_input_hook(self):
        """Return an input() replacement that pauses the thread and signals the UI."""
        runner = self

        def _hook(prompt=""):
            # Parse the spec path that the oracle validator just printed
            spec = _parse_oracle_spec_path(runner.log.get_text())
            if spec and not os.path.isabs(spec):
                spec = os.path.normpath(os.path.join(_MORT_ROOT, spec))
            validated = (
                spec.replace("_oracle.txt", "_oracle_validated.txt")
                if spec else None
            )
            runner.pause_spec_path = spec
            runner.pause_validated_path = validated
            runner.paused = True
            runner._resume_event.wait()   # block until UI calls resume()
            runner._resume_event.clear()
            runner.paused = False
            return ""                     # simulate pressing Enter

        return _hook

    def start(
        self,
        repo: str,
        mode: str,
        chunk: str,
        workers: int,
        concern: str,
        code_abs: str,
        test_abs: str,
        model: str,
        provider: str,
        test_type: str = "unit",
    ):
        self._thread = threading.Thread(
            target=self._run,
            kwargs=dict(
                repo=repo, mode=mode, chunk=chunk, workers=workers,
                concern=concern, code_abs=code_abs, test_abs=test_abs,
                model=model, provider=provider, test_type=test_type,
            ),
            daemon=True,
        )
        self._thread.start()

    def _run(self, repo, mode, chunk, workers, concern, code_abs, test_abs, model, provider, test_type="unit"):
        import builtins
        from src.mort_workflow import MORTWorkflow

        # Route this thread's stdout to our log capture (thread-local so
        # concurrent runners never collide on the global sys.stdout).
        _log_thread_local.capture = self.log

        # Patch input() so oracle validation pauses the thread instead of
        # blocking forever on a stdin that has no user attached
        _orig_input = builtins.input
        builtins.input = self._make_input_hook()

        try:
            mort = MORTWorkflow(
                repo, model, provider,
                max_workers=workers,
                chunker_mode=chunk,
                mode=mode,
                concern=concern,
                test_type=test_type,
            )
            if mode == "mutation":
                self.result = mort.run_workflow(code_abs, test_abs)
            else:
                self.result = mort.run_oracle_workflow(code_abs, test_abs)
        except Exception as exc:
            import traceback as _tb
            self.error_type = type(exc).__name__
            self.error_msg = str(exc)
            self.error_tb = _tb.format_exc()
        finally:
            _log_thread_local.capture = None
            builtins.input = _orig_input
            self.done = True


def _parse_oracle_spec_path(log_text: str) -> str | None:
    """Extract the oracle spec file path printed by OracleValidator."""
    m = re.search(r"Oracle specification saved to:\s*\n\s*(.+)", log_text)
    return m.group(1).strip() if m else None


# ─── Log capture handler for Python logging ────────────────────────────────────
class _LogCaptureHandler(logging.Handler):
    """Routes Python logging records to a LogCapture instance."""

    def __init__(self, capture: LogCapture):
        super().__init__()
        self._capture = capture

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record) + "\n"
            self._capture.write(msg)
        except Exception:
            pass


# ─── Background knowledge-graph builder ────────────────────────────────────────
class KGRunner:
    """Runs build_graph() in a daemon thread with log capture."""

    def __init__(self):
        self.log = LogCapture()
        self.done = False
        self.success = False
        self.error_type: str | None = None
        self.error_msg: str | None = None
        self.error_tb: str | None = None
        self._thread: threading.Thread | None = None

    def start(self, repo_folder: str, neo4j_uri: str, neo4j_user: str, neo4j_pass: str):
        self._thread = threading.Thread(
            target=self._run,
            kwargs=dict(
                repo_folder=repo_folder,
                neo4j_uri=neo4j_uri,
                neo4j_user=neo4j_user,
                neo4j_pass=neo4j_pass,
            ),
            daemon=True,
        )
        self._thread.start()

    def _run(self, repo_folder: str, neo4j_uri: str, neo4j_user: str, neo4j_pass: str):
        from src.neo4j_script import build_graph

        # Route stdout to our log capture
        _log_thread_local.capture = self.log

        # Capture logging output from neo4j_script
        handler = _LogCaptureHandler(self.log)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        neo4j_logger = logging.getLogger("src.neo4j_script")
        neo4j_logger.addHandler(handler)
        neo4j_logger.setLevel(logging.INFO)

        try:
            build_graph(repo_folder, neo4j_uri, neo4j_user, neo4j_pass)
            self.success = True
        except Exception as exc:
            import traceback as _tb
            self.error_type = type(exc).__name__
            self.error_msg = str(exc)
            self.error_tb = _tb.format_exc()
        finally:
            neo4j_logger.removeHandler(handler)
            _log_thread_local.capture = None
            self.done = True


# ─── Folder picker (native OS dialog) ─────────────────────────────────────────
def pick_folder_native(title: str = "Select repository folder") -> str:
    """Open a native folder picker.

    On macOS, AppleScript (osascript) is tried first — it is always available,
    runs on the correct thread, and has a native Finder look-and-feel.
    On all platforms a tkinter subprocess is used as a fallback.

    Returns the chosen absolute path, or '' if the user cancelled / no picker
    is available.
    """
    import subprocess
    import sys

    def _try_tkinter(dialog_title: str) -> str | None:
        """Run a tkinter folder-picker in a subprocess.

        Returns the chosen path on success, '' if the user cancelled
        (subprocess exited cleanly with no output), or None if the
        subprocess itself crashed (e.g. tkinter not installed).
        """
        script = (
            "import os\n"
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "title = os.environ.get('MORT_FOLDER_DIALOG_TITLE', 'Select folder')\n"
            "root = tk.Tk()\n"
            "try:\n"
            "    root.wm_attributes('-topmost', 1)\n"
            "except Exception:\n"
            "    pass\n"
            "root.withdraw()\n"
            "folder = filedialog.askdirectory(title=title)\n"
            "try:\n"
            "    root.destroy()\n"
            "except Exception:\n"
            "    pass\n"
            "print(folder or '')\n"
        )
        env = os.environ.copy()
        env["MORT_FOLDER_DIALOG_TITLE"] = dialog_title
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env=env,
                timeout=300,
            )
            if result.returncode == 0:
                # Clean exit: empty stdout means user cancelled (not a crash)
                return (result.stdout or "").strip()
            # Non-zero exit: subprocess crashed (missing tkinter, TclError, …)
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return None

    def _try_osascript(dialog_title: str) -> str | None:
        """Show a Finder folder-picker via AppleScript.

        Returns the POSIX path on success, '' if the user cancelled,
        or None if osascript itself is unavailable.
        """
        escaped = dialog_title.replace('"', '\\"')
        try:
            result = subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'set chosenFolder to choose folder with prompt "{escaped}"',
                    "-e",
                    "POSIX path of chosenFolder",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            # returncode 0  → folder chosen; stdout contains the POSIX path
            # returncode 1  → user cancelled (AppleScript error -128); stdout empty
            # Either way, returning stdout gives the right answer.
            return (result.stdout or "").strip()
        except FileNotFoundError:
            # osascript not found (non-macOS system or unusual setup)
            return None
        except (subprocess.TimeoutExpired, Exception):
            return None

    # ── macOS: prefer AppleScript (no tkinter dependency, always reliable) ──
    if sys.platform == "darwin":
        out = _try_osascript(title)
        if out is not None:
            return out
        # osascript unavailable — fall back to tkinter subprocess
        out = _try_tkinter(title)
        return out if out is not None else ""

    # ── Windows / Linux: use tkinter subprocess ──────────────────────────────
    out = _try_tkinter(title)
    return out if out is not None else ""


# ─── Repository / tree helpers ────────────────────────────────────────────────
def read_repo_from_disk(folder: str) -> dict:
    repo: dict = {}
    base = Path(folder)
    for p in base.rglob("*"):
        if p.is_dir():
            continue
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.name.startswith("."):
            continue
        rel = p.relative_to(base).as_posix()
        try:
            repo[rel] = p.read_bytes()
        except Exception:
            continue
    return repo


def build_tree(paths: list) -> dict:
    root: dict = {}
    for p in paths:
        parts = list(PurePosixPath(p).parts)
        cur = root
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
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
    dirs = sorted(k for k, v in node.items() if isinstance(v, dict))
    files = sorted(k for k, v in node.items() if v is None)
    return dirs, files


def join_posix(cur: PurePosixPath, name: str) -> str:
    if str(cur) in ("", "."):
        return name
    return str(cur / name)


def abs_path(repo_folder: str, rel_posix: str) -> str:
    return os.path.normpath(os.path.join(repo_folder, rel_posix.replace("/", os.sep)))


def normalize_existing_dir(folder: str) -> str:
    cleaned = (folder or "").strip().strip("'").strip('"')
    if not cleaned:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(cleaned))
    absolute = os.path.abspath(expanded)
    return absolute if os.path.isdir(absolute) else ""


def set_repo_folder(folder: str):
    st.session_state.repo_folder = folder
    files = read_repo_from_disk(folder)
    st.session_state.repo_files = files
    st.session_state.repo_tree = build_tree(list(files.keys()))
    st.session_state.code_dir = PurePosixPath(".")
    st.session_state.test_dir = PurePosixPath(".")
    st.session_state.selected_code_path = None
    st.session_state.selected_test_path = None


# ─── Session state init ───────────────────────────────────────────────────────
def init_state():
    defaults = {
        "page": "workflow",       # "workflow" | "knowledge_graph"
        "step_idx": 0,
        "repo_folder": None,
        "repo_folder_input": "",
        "repo_files": {},
        "repo_tree": {},
        "code_dir": PurePosixPath("."),
        "test_dir": PurePosixPath("."),
        "selected_code_path": None,
        "selected_test_path": None,
        # workflow config
        "workflow_mode": "mutation",
        "chunk_strategy": "AST",
        "workers": MAX_WORKERS,
        "concern": "Privacy",
        "test_type": "unit",
        # run state
        "run_status": None,       # None | "running" | "complete" | "error"
        "run_result": None,
        "run_logs": "",
        "run_error_type": None,   # exception class name
        "run_error_msg": None,    # str(exc)
        "run_error_tb": None,     # full traceback
        "run_elapsed": 0.0,
        "run_start": None,
        "runner": None,           # WorkflowRunner instance
        "oracle_continuing": False,  # True while waiting for thread to resume after Continue
        # knowledge graph state
        "kg_status": None,        # None | "running" | "success" | "error"
        "kg_logs": "",
        "kg_error_type": None,
        "kg_error_msg": None,
        "kg_error_tb": None,
        "kg_repo_folder": None,
        "kg_repo_folder_input": "",
        "kg_runner": None,
        "kg_start": None,
        "kg_elapsed": 0.0,
        "graph_status_cache": {},  # repo_folder -> (status, label)
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def goto(idx: int):
    st.session_state.step_idx = max(0, min(idx, len(STEPS) - 1))
    st.session_state.page = "workflow"


def can_advance() -> bool:
    key = STEPS[st.session_state.step_idx].key
    if key == "repo":
        return bool(st.session_state.repo_files)
    if key == "code":
        return st.session_state.selected_code_path is not None
    if key == "test":
        return st.session_state.selected_test_path is not None
    return False  # "config" is the last step


# ─── Stepper header ───────────────────────────────────────────────────────────
def render_stepper():
    idx = st.session_state.step_idx
    cols = st.columns(len(STEPS))
    for i, step in enumerate(STEPS):
        with cols[i]:
            if i < idx:
                st.markdown(
                    f"<p style='text-align:center;color:#22c55e;font-weight:600;margin:0'>✅ {step.label}</p>",
                    unsafe_allow_html=True,
                )
            elif i == idx:
                st.markdown(
                    f"<p style='text-align:center;color:#3b82f6;font-weight:700;"
                    f"border-bottom:3px solid #3b82f6;padding-bottom:3px;margin:0'>"
                    f"{step.icon} {step.label}</p>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<p style='text-align:center;color:#94a3b8;margin:0'>○ {step.label}</p>",
                    unsafe_allow_html=True,
                )
    st.progress((idx + 1) / len(STEPS))
    st.divider()


# ─── Page: Repository ─────────────────────────────────────────────────────────
def page_repo():
    st.subheader("📁 Select Repository")
    st.caption("Choose the root folder of the project you want to analyse.")

    btn_col, info_col = st.columns([1, 3])
    with btn_col:
        if st.button("Browse…", type="primary", use_container_width=True):
            folder = normalize_existing_dir(pick_folder_native())
            if folder:
                with st.spinner("Indexing repository…"):
                    set_repo_folder(folder)
                st.session_state.repo_folder_input = folder
                st.rerun()
            else:
                st.warning(
                    "Could not open the native picker. Paste a path below and click **Use path**.",
                    icon="ℹ️",
                )

    with info_col:
        if st.session_state.repo_folder:
            st.info(f"**{st.session_state.repo_folder}**", icon="📁")

    input_col, use_col = st.columns([5, 1])
    with input_col:
        st.text_input(
            "Or paste repository path",
            key="repo_folder_input",
            placeholder="~/projects/my-repo",
            label_visibility="collapsed",
        )
    with use_col:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("Use path", key="repo_use_path", use_container_width=True):
            folder = normalize_existing_dir(st.session_state.repo_folder_input)
            if folder:
                with st.spinner("Indexing repository…"):
                    set_repo_folder(folder)
                st.session_state.repo_folder_input = folder
                st.rerun()
            else:
                st.error("Path does not exist or is not a folder.")

    if st.session_state.repo_files:
        st.metric("Files indexed", len(st.session_state.repo_files))
        with st.expander("Browse file tree", expanded=False):
            preview = "\n".join(sorted(st.session_state.repo_files.keys())[:300])
            st.code(preview or "(empty)", language=None)
            if len(st.session_state.repo_files) > 300:
                st.caption("Showing first 300 files.")
    elif st.session_state.repo_folder:
        st.warning("Repository appears empty or all files were excluded by the ignore list.")
    else:
        st.info("Click **Browse…** to pick a repository folder.", icon="ℹ️")


# ─── Generic file picker ──────────────────────────────────────────────────────
def page_file_picker(
    title: str,
    caption: str,
    dir_key: str,
    sel_key: str,
    filter_fn,
):
    st.subheader(title)
    st.caption(caption)

    tree = st.session_state.repo_tree
    if not tree:
        st.warning("Select a repository first (step 1).")
        return

    cur: PurePosixPath = st.session_state[dir_key]
    parts = list(cur.parts) if str(cur) not in ("", ".") else []
    crumbs = " / ".join(["(root)"] + parts)

    nav_l, nav_r = st.columns([5, 1])
    with nav_l:
        st.caption(f"📂 {crumbs}")
    with nav_r:
        if st.button(
            "⬆ Up",
            disabled=(str(cur) in ("", ".")),
            key=f"up_{dir_key}",
            use_container_width=True,
        ):
            parent = cur.parent
            st.session_state[dir_key] = PurePosixPath(".") if str(parent) == "" else parent
            st.rerun()

    dirs, files = list_dir(tree, cur)
    left, right = st.columns(2)

    with left:
        st.markdown("**Folders**")
        if not dirs:
            st.caption("No subfolders here.")
        for d in dirs:
            if st.button(
                f"📁 {d}",
                key=f"dir_{dir_key}_{crumbs}_{d}",
                use_container_width=True,
            ):
                st.session_state[dir_key] = (
                    PurePosixPath(d) if str(cur) in ("", ".") else cur / d
                )
                st.rerun()

    with right:
        st.markdown("**Files**")
        eligible = [f for f in files if filter_fn(f)]
        if not eligible:
            st.caption("No matching files in this folder.")
        else:
            chosen = st.session_state[sel_key]
            for f in eligible:
                full = join_posix(cur, f)
                is_sel = chosen == full
                label = f"✅ {f}" if is_sel else f"📄 {f}"
                btn_type = "primary" if is_sel else "secondary"
                if st.button(
                    label,
                    key=f"file_{sel_key}_{crumbs}_{f}",
                    use_container_width=True,
                    type=btn_type,
                ):
                    st.session_state[sel_key] = full
                    st.rerun()

    if st.session_state[sel_key]:
        st.success(f"**Selected:** `{st.session_state[sel_key]}`")
    else:
        st.info("Click a file above to select it.", icon="👆")


def page_code():
    page_file_picker(
        "📄 Select Code File",
        "Pick the source file you want to mutate or analyse.",
        "code_dir",
        "selected_code_path",
        lambda name: PurePosixPath(name).suffix.lower() in CODE_EXTS,
    )


def page_test():
    def is_test(name: str) -> bool:
        p = PurePosixPath(name)
        stem = p.stem.lower()
        sfx = p.suffix.lower()
        if sfx == ".py":
            return "test" in stem
        if sfx in {".js", ".ts"}:
            return "test" in stem or stem.endswith(".spec")
        return False

    page_file_picker(
        "🧪 Select Test File",
        "Pick the test suite that exercises the selected code file.",
        "test_dir",
        "selected_test_path",
        is_test,
    )


# ─── Knowledge graph status helpers ───────────────────────────────────────────
def _get_graph_status(repo_folder: str) -> tuple[str, str]:
    """
    Check if a Neo4j knowledge graph exists for the given repo.

    Returns (status, label):
      - ("unconfigured", "…") — NEO4J_URI / NEO4J_PASSWORD not set
      - ("ok",           "…") — Repo node found in graph
      - ("missing",      "…") — Connected but no graph for this repo
      - ("error",        "…") — Connection / query error
    """
    neo4j_uri = os.environ.get("NEO4J_URI")
    neo4j_pass = os.environ.get("NEO4J_PASSWORD")
    if not neo4j_uri or not neo4j_pass:
        return "unconfigured", "Neo4j not configured"
    try:
        from neo4j import GraphDatabase
        neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
        repo_id = os.path.abspath(repo_folder).replace("\\", "/")
        with driver.session() as session:
            result = session.run(
                "MATCH (r:Repo {id: $id}) RETURN r.name AS name",
                id=repo_id,
            )
            record = result.single()
        driver.close()
        if record:
            return "ok", f"Graph ready — {record['name']}"
        return "missing", "No graph for this repo"
    except Exception as exc:
        return "error", f"Neo4j: {str(exc)[:80]}"


def _show_graph_badge(repo_folder: str | None):
    """Render a small inline graph-status indicator."""
    if not repo_folder:
        return
    cache = st.session_state.graph_status_cache
    if repo_folder not in cache:
        cache[repo_folder] = _get_graph_status(repo_folder)
    status, label = cache[repo_folder]
    color = {"ok": "#16a34a", "missing": "#d97706", "unconfigured": "#64748b", "error": "#dc2626"}.get(status, "#64748b")
    icon  = {"ok": "✅", "missing": "⚠️", "unconfigured": "ℹ️", "error": "❌"}.get(status, "ℹ️")
    st.markdown(
        f"<span style='font-size:0.82rem;color:{color}'>"
        f"{icon} <strong>Knowledge Graph:</strong> {label}</span>",
        unsafe_allow_html=True,
    )


# ─── Running page (live progress) ─────────────────────────────────────────────
def _show_running_page():
    """Displayed while the workflow thread is running. Polls every second."""
    runner: WorkflowRunner | None = st.session_state.runner
    elapsed = time.time() - (st.session_state.run_start or time.time())

    # ── Check if thread has finished ──────────────────────────────────────
    if runner and runner.done:
        st.session_state.run_elapsed = elapsed
        st.session_state.run_logs = runner.log.get_text()
        st.session_state.oracle_continuing = False
        if runner.error_type is not None:
            st.session_state.run_status = "error"
            st.session_state.run_error_type = runner.error_type
            st.session_state.run_error_msg = runner.error_msg
            st.session_state.run_error_tb = runner.error_tb
        else:
            st.session_state.run_status = "complete"
            st.session_state.run_result = runner.result
        st.rerun()
        return

    # ── Oracle validation pause ────────────────────────────────────────────
    if runner and runner.paused:
        if st.session_state.oracle_continuing:
            # We've already clicked Continue — wait for thread to actually resume
            st.subheader("⏳ Resuming workflow…")
            st.info("Applying your edits and continuing the oracle workflow.", icon="🔄")
            if not runner.paused:
                st.session_state.oracle_continuing = False
            time.sleep(0.5)
            st.rerun()
        else:
            _show_oracle_pause_ui(runner, elapsed)
        return

    # ── Still running — live progress ──────────────────────────────────────
    mode = st.session_state.workflow_mode
    concern = st.session_state.concern
    icon = CONCERN_ICONS[concern]

    st.subheader(f"⏳ Running {mode} workflow…")

    m1, m2, m3 = st.columns(3)
    m1.metric("Elapsed", f"{int(elapsed)}s")
    m2.metric("Mode", mode.capitalize())
    m3.metric("Concern", f"{icon} {concern}")

    # Progress bar: monotonically increasing, asymptotes toward 95%
    # Uses 1 - e^(-t/τ) with τ=50s so it feels responsive early but doesn't
    # misleadingly hit 100% before the workflow actually finishes.
    progress = min(0.95, 1.0 - math.exp(-elapsed / 50))
    st.progress(progress)

    st.markdown("---")

    # ── Live log output ────────────────────────────────────────────────────
    recent = runner.log.get_recent_lines(35) if runner else ""

    if recent:
        st.markdown("**Recent output** *(last 35 lines)*")
        st.code(recent, language=None)
    else:
        st.info(
            "Initializing… importing model libraries and preparing the repository. "
            "This can take 15–30 seconds before output appears.",
            icon="⏳",
        )

    # Poll every second
    time.sleep(1)
    st.rerun()


# ─── Oracle validation UI (interactive pause) ─────────────────────────────────
def _show_oracle_pause_ui(runner: WorkflowRunner, elapsed: float):
    """Shown when the oracle workflow pauses for human review of the spec."""
    st.markdown(
        "<div style='background:linear-gradient(135deg,#1e3a5f22,#3b82f611);"
        "border:2px solid #3b82f6;border-radius:14px;padding:20px 26px;margin-bottom:18px'>"
        "<h2 style='color:#3b82f6;margin:0 0 6px'>📋 Oracle Validation Pause</h2>"
        "<p style='color:#1e40af;margin:0'>The workflow has generated an oracle specification "
        "and is waiting for your review. Edit the text below if needed, then click "
        "<strong>Continue</strong> to resume.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    m1, m2 = st.columns(2)
    m1.metric("Elapsed so far", f"{int(elapsed)}s")
    m2.metric("Concern", f"{CONCERN_ICONS[st.session_state.concern]} {st.session_state.concern}")

    st.markdown("---")

    # ── Load the oracle spec from disk ────────────────────────────────────
    spec_path = runner.pause_spec_path
    spec_text = ""
    if spec_path and os.path.exists(spec_path):
        with open(spec_path, encoding="utf-8") as f:
            spec_text = f.read()
        st.caption(f"Spec file: `{spec_path}`")
    else:
        st.warning(
            "Oracle spec file not found on disk yet — the workflow may still be writing it. "
            "Wait a moment and the page will refresh.",
            icon="⚠️",
        )
        time.sleep(1)
        st.rerun()
        return

    # ── Editor ────────────────────────────────────────────────────────────
    st.markdown(
        "**Oracle specification** — review and edit as needed. "
        "Your edits define the correctness contract the oracle will enforce."
    )
    edited = st.text_area(
        "Oracle spec",
        value=spec_text,
        height=420,
        label_visibility="collapsed",
        key="oracle_editor",
    )

    st.markdown("---")

    btn_col, info_col = st.columns([1, 4])
    with btn_col:
        if st.button("▶  Continue", type="primary", use_container_width=True):
            runner.resume(validated_text=edited)
            st.session_state.oracle_continuing = True
            st.rerun()
    with info_col:
        validated_path = runner.pause_validated_path
        st.caption(
            f"Your edits will be saved to `{validated_path}` "
            "before the workflow continues."
            if validated_path else
            "Click Continue to resume the workflow with the spec as-is."
        )


# ─── Workflow launch ──────────────────────────────────────────────────────────
def _launch_workflow():
    # Clear all state from any previous run before starting fresh
    st.session_state.run_result = None
    st.session_state.run_logs = ""
    st.session_state.run_error_type = None
    st.session_state.run_error_msg = None
    st.session_state.run_error_tb = None
    st.session_state.run_elapsed = 0.0
    st.session_state.oracle_continuing = False

    runner = WorkflowRunner()
    runner.start(
        repo=st.session_state.repo_folder,
        mode=st.session_state.workflow_mode,
        chunk=st.session_state.chunk_strategy.lower(),
        workers=int(st.session_state.workers),
        concern=CONCERN_LOWER[st.session_state.concern],
        code_abs=abs_path(st.session_state.repo_folder, st.session_state.selected_code_path),
        test_abs=abs_path(st.session_state.repo_folder, st.session_state.selected_test_path),
        model=os.getenv("MODEL", MODEL),
        provider=os.getenv("MODEL_PROVIDER", MODEL_PROVIDER),
        test_type=st.session_state.get("test_type", "unit"),
    )
    st.session_state.runner = runner
    st.session_state.run_status = "running"
    st.session_state.run_start = time.time()
    st.rerun()


# ─── Error helpers ────────────────────────────────────────────────────────────
def _get_error_suggestion(error_type: str, error_msg: str) -> str | None:
    """Return a human-friendly hint based on the exception type/message."""
    m = error_msg.lower()

    # API key / authentication
    if any(k in m for k in ("api_key", "apikey", "api key", "authentication", "unauthorized", "403", "invalid_api_key")):
        return (
            "Your API key may be missing or invalid. "
            "Check that `GEMINI_API_KEY` (and `GOOGLE_API_KEY`) are set correctly in your `.env` file."
        )

    # Quota / rate limits
    if "quota" in m or ("rate" in m and "limit" in m) or "429" in m or "resource_exhausted" in m:
        return (
            "The API rate limit or quota has been exceeded. "
            "Wait a moment and retry, or reduce **Parallel workers** to lower request volume."
        )

    # Network / connectivity
    if any(k in m for k in ("connection", "timeout", "timed out", "network", "ssl", "certificate")):
        return "A network error occurred. Check your internet connection and try again."

    # Missing module / bad install
    if error_type in ("ModuleNotFoundError", "ImportError"):
        module = ""
        if "No module named" in error_msg:
            module = error_msg.split("No module named")[-1].strip(" '\"")
        hint = f" (`{module}`)" if module else ""
        return (
            f"A required dependency{hint} is missing. "
            "Run `pip install -r requirements.txt` in the MORT root directory."
        )

    # File not found
    if error_type == "FileNotFoundError" or "no such file" in m:
        return (
            "A file expected by the workflow could not be found. "
            "Verify that the selected code and test file paths are correct."
        )

    # Chunker / parse errors
    if "chunk" in m or "parse" in m or "syntax" in m:
        return (
            "The code file could not be parsed. "
            "Try switching the **Chunking strategy** from AST to LLM (or vice versa)."
        )

    return None


def _show_error_state():
    """Rich error display with type, message, suggestion, traceback, and logs."""
    error_type = st.session_state.get("run_error_type") or "Error"
    error_msg  = st.session_state.get("run_error_msg")  or "(no message)"
    error_tb   = st.session_state.get("run_error_tb")   or ""
    logs       = st.session_state.run_logs or ""
    elapsed    = st.session_state.run_elapsed

    # ── Header ────────────────────────────────────────────────────────────
    st.error(
        f"**Workflow failed** after {elapsed:.1f}s\n\n"
        f"**{error_type}:** {error_msg}",
        icon="❌",
    )

    # ── Suggestion ────────────────────────────────────────────────────────
    suggestion = _get_error_suggestion(error_type, error_msg)
    if suggestion:
        st.warning(suggestion, icon="💡")

    # ── Details ───────────────────────────────────────────────────────────
    col_tb, col_log = st.columns(2)
    with col_tb:
        with st.expander("Full traceback", expanded=True):
            st.code(error_tb or "(none)", language="python")
    with col_log:
        with st.expander("Captured logs before error", expanded=True):
            st.code(logs or "(no output was captured before the error)", language=None)


# ─── Page: Knowledge Graph ────────────────────────────────────────────────────
def page_knowledge_graph():
    """Full-page knowledge-graph builder."""
    runner: KGRunner | None = st.session_state.kg_runner
    status = st.session_state.kg_status

    neo4j_uri  = os.environ.get("NEO4J_URI")
    neo4j_pass = os.environ.get("NEO4J_PASSWORD")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")

    # ── Live progress view ────────────────────────────────────────────────
    if status == "running":
        elapsed = time.time() - (st.session_state.kg_start or time.time())

        if runner and runner.done:
            st.session_state.kg_elapsed = elapsed
            st.session_state.kg_logs = runner.log.get_text()
            if runner.error_type is not None:
                st.session_state.kg_status = "error"
                st.session_state.kg_error_type = runner.error_type
                st.session_state.kg_error_msg  = runner.error_msg
                st.session_state.kg_error_tb   = runner.error_tb
            else:
                st.session_state.kg_status = "success"
            # Invalidate cached graph status for this repo
            st.session_state.graph_status_cache.pop(
                st.session_state.kg_repo_folder or "", None
            )
            st.rerun()
            return

        st.subheader("⏳ Building knowledge graph…")
        m1, m2 = st.columns(2)
        m1.metric("Elapsed", f"{int(elapsed)}s")
        m2.metric("Repository", Path(st.session_state.kg_repo_folder or "").name or "—")
        st.progress(min(0.95, 1.0 - math.exp(-elapsed / 30)))
        st.markdown("---")

        recent = runner.log.get_recent_lines(30) if runner else ""
        if recent:
            st.markdown("**Progress log** *(last 30 lines)*")
            st.code(recent, language=None)
        else:
            st.info("Initialising — scanning repository files…", icon="⏳")

        time.sleep(1)
        st.rerun()
        return

    # ── Static page ────────────────────────────────────────────────────────
    st.subheader("🕸️ Knowledge Graph")
    st.caption(
        "Index a repository into Neo4j so MORT can use structural context "
        "when generating functional tests."
    )

    # ── Neo4j config status / setup instructions ──────────────────────────
    if not neo4j_uri or not neo4j_pass:
        st.warning(
            "**NEO4J_URI** and **NEO4J_PASSWORD** are not configured.\n\n"
            "Add the following to your `.env` file (in the MORT root) and "
            "**restart the server**:\n\n"
            "```\n"
            'NEO4J_URI="bolt://localhost:7687"\n'
            'NEO4J_USER="neo4j"\n'
            'NEO4J_PASSWORD="your_password_here"\n'
            "```",
            icon="⚠️",
        )
    else:
        st.success(f"Neo4j configured — `{neo4j_uri}`", icon="✅")

    st.markdown("---")

    # ── Repository picker ─────────────────────────────────────────────────
    st.markdown("**Repository to index**")
    btn_col, info_col = st.columns([1, 3])
    with btn_col:
        if st.button("Browse…", key="kg_browse", use_container_width=True):
            folder = normalize_existing_dir(pick_folder_native())
            if folder:
                st.session_state.kg_repo_folder = folder
                st.session_state.kg_repo_folder_input = folder
                st.session_state.graph_status_cache.pop(folder, None)
                st.rerun()
            else:
                st.warning(
                    "Could not open the native picker. Paste a path below and click **Use path**.",
                    icon="ℹ️",
                )
    with info_col:
        if st.session_state.kg_repo_folder:
            st.info(f"**{st.session_state.kg_repo_folder}**", icon="📁")
        else:
            st.caption("No repository selected.")

    input_col, use_col = st.columns([5, 1])
    with input_col:
        st.text_input(
            "Or paste repository path",
            key="kg_repo_folder_input",
            placeholder="~/projects/my-repo",
            label_visibility="collapsed",
        )
    with use_col:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("Use path", key="kg_repo_use_path", use_container_width=True):
            folder = normalize_existing_dir(st.session_state.kg_repo_folder_input)
            if folder:
                st.session_state.kg_repo_folder = folder
                st.session_state.kg_repo_folder_input = folder
                st.session_state.graph_status_cache.pop(folder, None)
                st.rerun()
            else:
                st.error("Path does not exist or is not a folder.")

    # ── Result from last run ──────────────────────────────────────────────
    if status == "success":
        st.success(
            f"Knowledge graph built successfully in {st.session_state.kg_elapsed:.1f}s.",
            icon="✅",
        )
        with st.expander("Build logs", expanded=False):
            st.code(st.session_state.kg_logs or "(no output)", language=None)
    elif status == "error":
        st.error(
            f"**{st.session_state.kg_error_type}:** {st.session_state.kg_error_msg}",
            icon="❌",
        )
        col_tb, col_log = st.columns(2)
        with col_tb:
            with st.expander("Traceback", expanded=True):
                st.code(st.session_state.kg_error_tb or "(none)", language="python")
        with col_log:
            with st.expander("Build logs", expanded=True):
                st.code(st.session_state.kg_logs or "(no output)", language=None)

    # ── Build button ──────────────────────────────────────────────────────
    st.markdown("---")
    can_build = bool(st.session_state.kg_repo_folder and neo4j_uri and neo4j_pass)
    already_built = status in ("success", "error")
    btn_label = "🔨  Rebuild Knowledge Graph" if already_built else "🔨  Build Knowledge Graph"

    if st.button(btn_label, type="primary", disabled=not can_build, use_container_width=False):
        kg_runner = KGRunner()
        kg_runner.start(
            repo_folder=st.session_state.kg_repo_folder,
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_pass=neo4j_pass,
        )
        st.session_state.kg_runner  = kg_runner
        st.session_state.kg_status  = "running"
        st.session_state.kg_start   = time.time()
        st.session_state.kg_logs    = ""
        st.session_state.kg_error_type = None
        st.session_state.kg_error_msg  = None
        st.session_state.kg_error_tb   = None
        st.rerun()

    if not can_build and st.session_state.kg_repo_folder:
        st.caption(
            "Configure NEO4J_URI and NEO4J_PASSWORD in `.env` and restart the server to enable building."
        )


# ─── Page: Configure & Run ────────────────────────────────────────────────────
def page_configure():
    # Delegate to live progress view while running
    if st.session_state.run_status == "running":
        _show_running_page()
        return

    st.subheader("⚙️ Configure & Run")

    # ── Selection summary ──────────────────────────────────────────────────
    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Code file:**  `{st.session_state.selected_code_path}`")
        with c2:
            st.markdown(f"**Test file:** `{st.session_state.selected_test_path}`")
        repo_col, badge_col = st.columns([3, 2])
        with repo_col:
            st.caption(f"Repository: `{st.session_state.repo_folder}`")
        with badge_col:
            _show_graph_badge(st.session_state.repo_folder)

    st.markdown("&nbsp;", unsafe_allow_html=True)

    # ── Configuration options ──────────────────────────────────────────────
    left, right = st.columns(2)

    with left:
        st.markdown("**Workflow mode**")
        wf_mode = st.segmented_control(
            "Workflow mode",
            options=["mutation", "oracle"],
            default=st.session_state.workflow_mode,
            label_visibility="collapsed",
        )
        if wf_mode:
            st.session_state.workflow_mode = wf_mode

        st.markdown("**Chunking strategy**")
        chunk = st.segmented_control(
            "Chunking strategy",
            options=["AST", "LLM"],
            default=st.session_state.chunk_strategy,
            label_visibility="collapsed",
        )
        if chunk:
            st.session_state.chunk_strategy = chunk

        if st.session_state.workflow_mode == "mutation":
            st.markdown("**Test type**")
            test_type = st.segmented_control(
                "Test type",
                options=["unit", "functional", "both"],
                format_func=lambda x: x.capitalize(),
                default=st.session_state.test_type,
                label_visibility="collapsed",
            )
            if test_type:
                st.session_state.test_type = test_type

            st.markdown("**Parallel workers**")
            workers_val = st.number_input(
                "Workers",
                min_value=1,
                max_value=32,
                value=int(st.session_state.workers),
                step=1,
                label_visibility="collapsed",
            )
            st.session_state.workers = workers_val

    with right:
        st.markdown("**Concern**")
        concern_options = [f"{CONCERN_ICONS[c]} {c}" for c in CONCERNS]
        concern_map = {f"{CONCERN_ICONS[c]} {c}": c for c in CONCERNS}
        curr_display = f"{CONCERN_ICONS[st.session_state.concern]} {st.session_state.concern}"
        chosen_display = st.radio(
            "Concern",
            concern_options,
            index=concern_options.index(curr_display) if curr_display in concern_options else 0,
            label_visibility="collapsed",
        )
        if chosen_display:
            st.session_state.concern = concern_map[chosen_display]
            st.caption(f"↳ {CONCERN_DESCS[st.session_state.concern]}")

    st.markdown("---")

    # ── Neo4j warning for functional test types ────────────────────────────
    if (
        st.session_state.workflow_mode == "mutation"
        and st.session_state.get("test_type", "unit") in ("functional", "both")
        and not (os.environ.get("NEO4J_URI") and os.environ.get("NEO4J_PASSWORD"))
    ):
        st.warning(
            "**Functional tests require a Neo4j knowledge graph.** "
            "Set `NEO4J_URI` and `NEO4J_PASSWORD` in your `.env` file and restart the server, "
            "then build the graph via the **Knowledge Graph** page before running.",
            icon="⚠️",
        )

    # ── Run / Clear buttons ────────────────────────────────────────────────
    already_ran = st.session_state.run_status in ("complete", "error")
    run_col, reset_col = st.columns([4, 1])

    with run_col:
        label = "▶  Re-run Workflow" if already_ran else "▶  Run Workflow"
        run_clicked = st.button(label, type="primary", use_container_width=True)

    with reset_col:
        if already_ran and st.button("Clear", use_container_width=True):
            st.session_state.run_status = None
            st.session_state.run_result = None
            st.session_state.run_logs = ""
            st.session_state.run_error_type = None
            st.session_state.run_error_msg = None
            st.session_state.run_error_tb = None
            st.session_state.run_elapsed = 0.0
            st.session_state.runner = None
            st.rerun()

    if run_clicked:
        _launch_workflow()

    # ── Results ────────────────────────────────────────────────────────────
    if st.session_state.run_status == "error":
        _show_error_state()

    elif st.session_state.run_status == "complete":
        _render_results()


# ─── Result rendering ─────────────────────────────────────────────────────────
def _render_results():
    result = st.session_state.run_result
    mode = st.session_state.workflow_mode
    concern = CONCERN_LOWER[st.session_state.concern]
    repo = st.session_state.repo_folder

    if not result:
        st.warning("Workflow completed but returned no results.")
        with st.expander("Logs"):
            st.code(st.session_state.run_logs or "(none)", language=None)
        return

    if mode == "mutation":
        _render_mutation(result, concern, repo)
    else:
        _render_oracle(result, concern, repo)


def _save_mutation_results(result: dict, concern: str, code_file_abs: str, test_type: str = "unit") -> tuple:
    """Persist mutants to disk (mirrors main.py logic). Returns (output_folder, metadata)."""
    file_name = Path(code_file_abs).stem
    out_dir = os.path.join(_MORT_ROOT, OUTPUT_DIR, file_name, concern, test_type)
    os.makedirs(out_dir, exist_ok=True)

    meta_path = os.path.join(out_dir, "metadata.json")
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    else:
        meta = {
            "code_file": code_file_abs,
            "total_chunks": result.get("total_chunks", 0),
            "mutants": [],
        }

    existing_hashes = {m["hash"] for m in meta["mutants"]}

    for m in result.get("mutants", []):
        h = m["hash"]
        cid = m["chunk_id"].replace(".", "_")
        mf_name = f"mutant_{cid}_{h}.py"

        with open(os.path.join(out_dir, mf_name), "w", encoding="utf-8") as f:
            f.write(m["mutated_file"])

        files_dict = {"mutant": mf_name}

        if m.get("test"):
            tf_name = f"test_{cid}_{h}.py"
            with open(os.path.join(out_dir, tf_name), "w", encoding="utf-8") as f:
                f.write(m["test"])
            files_dict["test"] = tf_name

        if m.get("functional_test"):
            ftf_name = f"functional_test_{cid}_{h}.py"
            with open(os.path.join(out_dir, ftf_name), "w", encoding="utf-8") as f:
                f.write(m["functional_test"])
            files_dict["functional_test"] = ftf_name

        if h not in existing_hashes:
            meta["mutants"].append(
                {
                    "hash": h,
                    "chunk_id": m["chunk_id"],
                    "chunk_type": m["chunk_type"],
                    "files": files_dict,
                    "scores": m.get("scores", {}),
                    "functional_scores": m.get("functional_scores", {}),
                }
            )
            existing_hashes.add(h)

    meta["total_chunks"] = result.get("total_chunks", 0)
    meta["successful_count"] = len(meta["mutants"])

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return out_dir, meta


# ─── Mutation log/result parsing helpers ──────────────────────────────────────
def _parse_chunk_outcomes(logs: str) -> list:
    """Parse workflow logs to extract per-chunk status and failure reasons."""
    outcomes: dict = {}
    for line in logs.splitlines():
        m = re.match(r"\[([^\]]+)\]\s+(.*)", line)
        if not m:
            continue
        chunk_id, msg = m.group(1), m.group(2).strip()
        if chunk_id not in outcomes:
            outcomes[chunk_id] = {"chunk_id": chunk_id, "status": "unknown", "reason": ""}
        if "DISCARD" in msg:
            outcomes[chunk_id]["status"] = "discarded"
            outcomes[chunk_id]["reason"] = re.sub(r"\s*-\s*DISCARD", "", msg).strip()
        elif "duplicate" in msg.lower() and "skipping" in msg.lower():
            outcomes[chunk_id]["status"] = "duplicate"
            outcomes[chunk_id]["reason"] = "Identical to a previously generated mutant"
        elif "failed to generate" in msg.lower() and outcomes[chunk_id]["status"] == "unknown":
            outcomes[chunk_id]["status"] = "failed"
            outcomes[chunk_id]["reason"] = msg
    return list(outcomes.values())


def _humanize_failure_reason(reason: str) -> str:
    r = reason.lower()
    if "fails existing tests" in r:
        return "The mutant broke existing tests — it introduced too obvious a bug."
    if "syntactically identical" in r or "syntactic identity" in r:
        return "The LLM returned code identical to the original (no mutation was made)."
    if "duplicate" in r:
        return "An identical mutant was already generated in a previous run."
    if "passes original tests" in r:
        return "The mutant passed all existing tests — the test suite didn't detect the bug."
    if "failed to generate" in r:
        return "Could not produce a valid mutant after all attempts."
    return reason


def _extract_mutation_description(mutated_code: str) -> str:
    """Pull the human-readable comment from inside the MUTANT START/END block."""
    match = re.search(r"# MUTANT START\s*(.*?)# MUTANT END", mutated_code, re.DOTALL)
    if not match:
        return ""
    lines = [
        ln.strip().lstrip("# ").strip()
        for ln in match.group(1).splitlines()
        if ln.strip().startswith("#")
    ]
    return " ".join(lines)


def _extract_mutation_snippet(mutated_code: str) -> str:
    """Pull the actual code lines from inside the MUTANT START/END block."""
    match = re.search(r"# MUTANT START\s*(.*?)# MUTANT END", mutated_code, re.DOTALL)
    if not match:
        return ""
    code_lines = [
        ln for ln in match.group(1).splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    return "\n".join(code_lines)


# ─── No-mutants result view ────────────────────────────────────────────────────
def _render_no_mutants(result: dict, out_dir: str):
    elapsed = st.session_state.run_elapsed
    logs = st.session_state.run_logs or ""

    # ── Banner ────────────────────────────────────────────────────────────
    st.markdown(
        f"<div style='background:linear-gradient(135deg,#7c290022,#d9770611);"
        f"border:2px solid #d97706;border-radius:14px;padding:22px 28px;margin-bottom:20px'>"
        f"<h2 style='color:#d97706;margin:0 0 6px'>⚠️ No Valid Mutants Generated</h2>"
        f"<p style='color:#92400e;margin:0'>The workflow ran for {elapsed:.1f}s "
        f"but could not produce any valid mutants from your code.</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Metrics ───────────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric("Mutants generated", 0)
    m2.metric("Chunks processed", result.get("total_chunks", 0))
    m3.metric("Duplicates skipped", result.get("skipped_count", 0))

    st.markdown("---")

    # ── Per-chunk breakdown ───────────────────────────────────────────────
    outcomes = _parse_chunk_outcomes(logs)
    if outcomes:
        st.markdown("#### What happened to each chunk")
        for o in outcomes:
            status = o["status"]
            reason = o["reason"]
            if status == "discarded":
                icon, color, label = "🔴", "#dc2626", "Discarded"
            elif status == "duplicate":
                icon, color, label = "🟡", "#d97706", "Duplicate"
            else:
                icon, color, label = "🔴", "#dc2626", "Failed"

            with st.container(border=True):
                col_a, col_b = st.columns([2, 5])
                with col_a:
                    st.markdown(
                        f"<span style='font-size:1.05rem;font-weight:700'>{o['chunk_id']}</span> "
                        f"<span style='color:{color};font-weight:600'>{icon} {label}</span>",
                        unsafe_allow_html=True,
                    )
                with col_b:
                    if reason:
                        st.caption(_humanize_failure_reason(reason))

    # ── Suggestions ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### What to try")
    c1, c2 = st.columns(2)
    with c1:
        st.info(
            "**Run again** — LLM output is non-deterministic; a fresh attempt often produces a different (valid) mutation.",
            icon="🔄",
        )
        st.info(
            "**Switch chunking strategy** — AST and LLM chunkers produce different chunk boundaries, which affects what the LLM targets.",
            icon="✂️",
        )
    with c2:
        st.info(
            "**Try a different concern** — the concern steers the LLM toward different bug types; some may be easier to inject for your code.",
            icon="🎯",
        )
        st.info(
            "**Check your test coverage** — if existing tests cover every path, any mutation that introduces a real bug will always be caught and discarded.",
            icon="🧪",
        )

    # ── Full logs ─────────────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("📜 Full workflow logs", expanded=False):
        st.code(logs or "(no output captured)", language=None)


# ─── Mutant card ───────────────────────────────────────────────────────────────
def _render_mutant_card(m: dict, idx: int):
    chunk_id = m.get("chunk_id", "unknown")
    chunk_type = m.get("chunk_type", "")
    mutated_code = m.get("mutated_file") or ""
    test_code = m.get("test") or ""
    functional_test_code = m.get("functional_test") or ""
    scores = m.get("scores", {})

    description = _extract_mutation_description(mutated_code)
    snippet = _extract_mutation_snippet(mutated_code)

    score_str = "  ·  ".join(f"**{k}:** {v}" for k, v in scores.items()) if scores else ""
    type_badge = f"  ·  `{chunk_type}`" if chunk_type else ""

    with st.container(border=True):
        # ── Header row ────────────────────────────────────────────────────
        head_l, head_r = st.columns([3, 2])
        with head_l:
            st.markdown(
                f"<h3 style='margin:0 0 2px'>Mutant {idx + 1} — <code>{chunk_id}</code></h3>"
                f"<p style='color:#6b7280;margin:0;font-size:0.88rem'>{score_str}{type_badge}</p>",
                unsafe_allow_html=True,
            )
        with head_r:
            dl_cols = st.columns(2 if not functional_test_code else 3)
            with dl_cols[0]:
                st.download_button(
                    "⬇ Mutant",
                    data=mutated_code,
                    file_name=f"mutant_{chunk_id.replace('.', '_')}_{m['hash']}.py",
                    mime="text/x-python",
                    key=f"dl_mutant_{idx}",
                    use_container_width=True,
                )
            if test_code:
                with dl_cols[1]:
                    st.download_button(
                        "⬇ Kill test",
                        data=test_code,
                        file_name=f"test_{chunk_id.replace('.', '_')}_{m['hash']}.py",
                        mime="text/x-python",
                        key=f"dl_test_{idx}",
                        use_container_width=True,
                    )
            if functional_test_code:
                with dl_cols[-1]:
                    st.download_button(
                        "⬇ Functional test",
                        data=functional_test_code,
                        file_name=f"functional_test_{chunk_id.replace('.', '_')}_{m['hash']}.py",
                        mime="text/x-python",
                        key=f"dl_func_{idx}",
                        use_container_width=True,
                    )

        st.markdown("---")

        # ── Bug description ────────────────────────────────────────────────
        if description:
            st.markdown(
                f"<div style='background:rgba(59,130,246,0.08);border-left:3px solid #3b82f6;"
                f"border-radius:0 6px 6px 0;padding:10px 14px;margin-bottom:12px'>"
                f"<strong>🐛 Bug injected:</strong> {description}"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ── Mutation snippet ───────────────────────────────────────────────
        if snippet:
            st.markdown("**Changed code (injected lines):**")
            st.code(snippet, language="python")

        # ── Full code in tabs ──────────────────────────────────────────────
        tab_labels = ["Full mutated file"]
        if test_code:
            tab_labels.append("Kill test")
        if functional_test_code:
            tab_labels.append("Functional test")

        tabs = st.tabs(tab_labels)
        tab_idx = 0
        with tabs[tab_idx]:
            st.code(mutated_code, language="python")
        tab_idx += 1
        if test_code:
            with tabs[tab_idx]:
                st.code(test_code, language="python")
            tab_idx += 1
        if functional_test_code:
            with tabs[tab_idx]:
                st.code(functional_test_code, language="python")


# ─── Main mutation result view ─────────────────────────────────────────────────
def _render_mutation(result: dict, concern: str, repo: str):
    code_abs = abs_path(repo, st.session_state.selected_code_path)
    out_dir, meta = _save_mutation_results(result, concern, code_abs, st.session_state.get("test_type", "unit"))

    mutants = result.get("mutants", [])
    count = len(mutants)

    # ── Zero mutants — detailed "why" view ────────────────────────────────
    if count == 0:
        _render_no_mutants(result, out_dir)
        return

    # ── Success banner ────────────────────────────────────────────────────
    plural = "s" if count != 1 else ""
    st.markdown(
        f"<div style='background:linear-gradient(135deg,#14532d22,#16a34a11);"
        f"border:2px solid #16a34a;border-radius:14px;padding:22px 28px;margin-bottom:20px'>"
        f"<h2 style='color:#16a34a;margin:0 0 6px'>✅ {count} Mutant{plural} Generated</h2>"
        f"<p style='color:#166534;margin:0'>Completed in {st.session_state.run_elapsed:.1f}s "
        f"— results saved to <code style='background:rgba(0,0,0,0.08);padding:2px 6px;border-radius:4px'>"
        f"{out_dir}</code></p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Metrics ───────────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric("Mutants generated", count)
    m2.metric("Chunks processed", result.get("total_chunks", "?"))
    m3.metric("Duplicates skipped", result.get("skipped_count", 0))

    st.markdown("---")

    # ── Mutant cards ──────────────────────────────────────────────────────
    for i, m in enumerate(mutants):
        _render_mutant_card(m, i)
        if i < count - 1:
            st.markdown("&nbsp;", unsafe_allow_html=True)

    # ── Logs + metadata ───────────────────────────────────────────────────
    st.markdown("---")
    tab_l, tab_meta = st.tabs(["📜 Full Logs", "🗂 Metadata"])
    with tab_l:
        st.code(st.session_state.run_logs or "(no output captured)", language=None)
    with tab_meta:
        st.json(meta)
        st.caption(f"Saved to `{out_dir}`")


def _render_oracle(result: dict, concern: str, repo: str):
    code_abs = abs_path(repo, st.session_state.selected_code_path)
    file_name = Path(code_abs).stem
    out_dir = os.path.join(_MORT_ROOT, ORACLE_OUTPUT_DIR, file_name)

    m1, m2 = st.columns(2)
    m1.metric("Functions processed", result.get("functions_processed", 0))
    m2.metric("Bugs detected", result.get("bugs_found", 0))

    tab_r, tab_l, tab_meta = st.tabs(["🐛 Bug Report", "📜 Full Logs", "🗂 Metadata"])

    with tab_r:
        report_path = os.path.join(out_dir, "bug_report.txt")
        if os.path.exists(report_path):
            with open(report_path, encoding="utf-8") as f:
                report = f.read()
            st.text_area("Bug report", report, height=450, label_visibility="collapsed")
            st.download_button(
                "⬇ Download report",
                data=report,
                file_name="bug_report.txt",
                mime="text/plain",
            )
        else:
            st.info(
                "Bug report file not found on disk. "
                "Check the **Full Logs** tab for details."
            )

    with tab_l:
        st.code(st.session_state.run_logs or "(no output captured)", language=None)

    with tab_meta:
        meta_path = os.path.join(out_dir, "metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                st.json(json.load(f))
        else:
            st.json(result)
        st.caption(f"Output folder: `{out_dir}`")


# ─── Sidebar ──────────────────────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.markdown("## 🔬 MORT")
        st.markdown("Mutation-Guided Oracle Refinement Testing")
        st.divider()

        # ── Top-level page navigation ──────────────────────────────────────
        on_kg = st.session_state.page == "knowledge_graph"
        st.button(
            "🕸️ Knowledge Graph",
            key="nav_kg",
            use_container_width=True,
            type="primary" if on_kg else "secondary",
            on_click=lambda: st.session_state.update(page="knowledge_graph"),
        )
        st.divider()

        st.markdown("### Steps")
        for i, step in enumerate(STEPS):
            is_locked = (
                (step.key in ("code", "test", "config") and not st.session_state.repo_files)
                or (step.key in ("test", "config") and not st.session_state.selected_code_path)
                or (step.key == "config" and not st.session_state.selected_test_path)
            )
            curr = i == st.session_state.step_idx
            done = i < st.session_state.step_idx

            if done:
                label = f"✅ {step.label}"
            elif curr:
                label = f"➡ {step.icon} {step.label}"
            else:
                label = f"  {step.icon} {step.label}"

            st.button(
                label,
                disabled=is_locked,
                on_click=goto,
                args=(i,),
                use_container_width=True,
                key=f"nav_{step.key}",
            )

        st.divider()
        st.markdown("### Previous Runs")
        _sidebar_runs()

        st.divider()
        model = os.getenv("MODEL", MODEL)
        provider = os.getenv("MODEL_PROVIDER", MODEL_PROVIDER)
        st.caption(f"Model: `{model}`\nProvider: `{provider}`")


def _sidebar_runs():
    any_found = False
    sections = [
        ("Mutation", os.path.join(_MORT_ROOT, OUTPUT_DIR)),
        ("Oracle", os.path.join(_MORT_ROOT, ORACLE_OUTPUT_DIR)),
    ]
    for mode_label, base in sections:
        if not os.path.isdir(base):
            continue
        entries = [
            d for d in sorted(os.listdir(base))
            if os.path.isdir(os.path.join(base, d))
        ]
        if not entries:
            continue
        any_found = True
        with st.expander(mode_label, expanded=False):
            for entry in entries:
                entry_path = os.path.join(base, entry)
                if mode_label == "Mutation":
                    concern_dirs = [
                        c for c in sorted(os.listdir(entry_path))
                        if os.path.isdir(os.path.join(entry_path, c))
                    ]
                    for cdir in concern_dirs:
                        mp = os.path.join(entry_path, cdir, "metadata.json")
                        count = 0
                        if os.path.exists(mp):
                            try:
                                count = json.load(open(mp)).get("successful_count", 0)
                            except Exception:
                                pass
                        st.caption(f"📄 {entry} / {cdir}: **{count}** mutants")
                else:
                    mp = os.path.join(entry_path, "metadata.json")
                    bugs = 0
                    if os.path.exists(mp):
                        try:
                            bugs = json.load(open(mp)).get("bugs_found", 0)
                        except Exception:
                            pass
                    st.caption(f"📄 {entry}: **{bugs}** bugs")

    if not any_found:
        st.caption("No previous runs yet.")


# ─── App shell ────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="MORT — Mutation-Guided Oracle Refinement Testing",
        page_icon="🔬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    init_state()
    render_sidebar()

    # ── Top-level routing ─────────────────────────────────────────────────
    if st.session_state.page == "knowledge_graph":
        page_knowledge_graph()
        return

    render_stepper()

    key = STEPS[st.session_state.step_idx].key
    if key == "repo":
        page_repo()
    elif key == "code":
        page_code()
    elif key == "test":
        page_test()
    elif key == "config":
        page_configure()

    # Don't render Back/Next nav while the workflow is actively running
    if st.session_state.run_status == "running":
        return

    st.divider()

    back_col, _, next_col = st.columns([1, 6, 1])
    with back_col:
        st.button(
            "← Back",
            on_click=goto,
            args=(st.session_state.step_idx - 1,),
            disabled=(st.session_state.step_idx == 0),
            use_container_width=True,
        )
    with next_col:
        is_last = st.session_state.step_idx == len(STEPS) - 1
        st.button(
            "Next →",
            on_click=goto,
            args=(st.session_state.step_idx + 1,),
            disabled=(is_last or not can_advance()),
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
