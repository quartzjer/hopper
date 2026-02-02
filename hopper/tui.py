"""TUI for managing coding agents."""

from dataclasses import dataclass, field

from blessed import Terminal

from hopper.claude import spawn_claude, switch_to_window
from hopper.projects import Project, find_project, get_active_projects
from hopper.sessions import (
    Session,
    archive_session,
    create_session,
    format_age,
    load_sessions,
    save_sessions,
)

# Box-drawing characters (Unicode, no emoji)
BOX_H = "─"  # horizontal line
BOX_H_BOLD = "━"  # bold horizontal line

# Status indicators (Unicode symbols, no emoji)
STATUS_RUNNING = "●"  # filled circle
STATUS_IDLE = "○"  # empty circle
STATUS_ERROR = "✗"  # x mark
STATUS_ACTION = "+"  # plus for action rows

# Column widths for table formatting
COL_ID = 8  # short_id length
COL_AGE = 3  # "now", "3m", "4h", "2d", "1w"


@dataclass
class Row:
    """A row in a table."""

    id: str
    short_id: str
    age: str  # formatted age string
    updated: str  # formatted updated string
    status: str  # STATUS_RUNNING, STATUS_IDLE, STATUS_ERROR, or STATUS_ACTION
    project: str = ""  # Project name
    message: str = ""  # Human-readable status message
    is_action: bool = False  # True for action rows like "new session"


def session_to_row(session: Session) -> Row:
    """Convert a session to a display row."""
    if session.state == "error":
        status = STATUS_ERROR
    elif session.state == "running":
        status = STATUS_RUNNING
    else:
        status = STATUS_IDLE

    return Row(
        id=session.id,
        short_id=session.short_id,
        age=format_age(session.created_at),
        updated=format_age(session.effective_updated_at),
        status=status,
        project=session.project,
        message=session.message,
    )


def new_shovel_row(project_name: str = "") -> Row:
    """Create the 'new session' action row."""
    return Row(
        id="new",
        short_id="new",
        age="",
        updated="",
        status=STATUS_ACTION,
        project=project_name,
        is_action=True,
    )


@dataclass
class TUIState:
    """State for the TUI."""

    sessions: list[Session] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    ore_rows: list[Row] = field(default_factory=list)
    processing_rows: list[Row] = field(default_factory=list)
    cursor_index: int = 0
    selected_project_index: int = 0

    @property
    def total_rows(self) -> int:
        return len(self.ore_rows) + len(self.processing_rows)

    @property
    def selected_project(self) -> Project | None:
        """Get the currently selected project for new sessions."""
        if self.projects and 0 <= self.selected_project_index < len(self.projects):
            return self.projects[self.selected_project_index]
        return None

    @property
    def is_add_project_selected(self) -> bool:
        """True when 'add...' option is selected (past last project)."""
        return self.selected_project_index >= len(self.projects)

    def cursor_up(self) -> "TUIState":
        new_index = (self.cursor_index - 1) % self.total_rows
        return TUIState(
            self.sessions,
            self.projects,
            self.ore_rows,
            self.processing_rows,
            new_index,
            self.selected_project_index,
        )

    def cursor_down(self) -> "TUIState":
        new_index = (self.cursor_index + 1) % self.total_rows
        return TUIState(
            self.sessions,
            self.projects,
            self.ore_rows,
            self.processing_rows,
            new_index,
            self.selected_project_index,
        )

    def project_left(self) -> "TUIState":
        """Cycle to previous project (includes 'add...' option at end)."""
        # Cycle through: project0, project1, ..., projectN, add...
        # Total options = len(projects) + 1
        total_options = len(self.projects) + 1
        new_index = (self.selected_project_index - 1) % total_options
        new_state = TUIState(
            self.sessions,
            self.projects,
            self.ore_rows,
            self.processing_rows,
            self.cursor_index,
            new_index,
        )
        return new_state.rebuild_rows()

    def project_right(self) -> "TUIState":
        """Cycle to next project (includes 'add...' option at end)."""
        # Cycle through: project0, project1, ..., projectN, add...
        # Total options = len(projects) + 1
        total_options = len(self.projects) + 1
        new_index = (self.selected_project_index + 1) % total_options
        new_state = TUIState(
            self.sessions,
            self.projects,
            self.ore_rows,
            self.processing_rows,
            self.cursor_index,
            new_index,
        )
        return new_state.rebuild_rows()

    def get_selected_row(self) -> Row | None:
        """Get the currently selected row."""
        if self.cursor_index < len(self.ore_rows):
            return self.ore_rows[self.cursor_index]
        processing_index = self.cursor_index - len(self.ore_rows)
        if processing_index < len(self.processing_rows):
            return self.processing_rows[processing_index]
        return None

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        for session in self.sessions:
            if session.id == session_id:
                return session
        return None

    def rebuild_rows(self) -> "TUIState":
        """Rebuild row lists from sessions."""
        # New session row shows currently selected project or "add..."
        if self.selected_project_index >= len(self.projects):
            project_name = "add..."
        elif self.projects:
            project_name = self.projects[self.selected_project_index].name
        else:
            project_name = "add..."

        ore_rows = [new_shovel_row(project_name)]
        processing_rows = []

        for session in self.sessions:
            row = session_to_row(session)
            if session.stage == "ore":
                ore_rows.append(row)
            else:
                processing_rows.append(row)

        # Clamp cursor to valid range
        total = len(ore_rows) + len(processing_rows)
        cursor = min(self.cursor_index, total - 1) if total > 0 else 0

        return TUIState(
            self.sessions,
            self.projects,
            ore_rows,
            processing_rows,
            cursor,
            self.selected_project_index,
        )


def format_status(term: Terminal, status: str) -> str:
    """Format a status indicator with color."""
    if status == STATUS_RUNNING:
        return term.green(status)
    elif status == STATUS_ERROR:
        return term.red(status)
    elif status == STATUS_ACTION:
        return term.cyan(status)
    else:  # STATUS_IDLE
        return term.dim + status + term.normal


def compute_project_col_width(state: TUIState) -> int:
    """Compute dynamic project column width based on visible projects."""
    max_len = 0
    # Check all rows in both tables
    for row in state.ore_rows + state.processing_rows:
        if row.project:
            max_len = max(max_len, len(row.project))
    # Minimum width of 4 to show truncated names
    return max(4, max_len)


def format_row(term: Terminal, row: Row, width: int, project_col_width: int) -> str:
    """Format a row for display.

    Args:
        term: Terminal for color formatting
        row: Row data to format
        width: Available width for the row content (excluding cursor prefix)
        project_col_width: Width for the project column

    Returns a string like:
      "● abcd1234  proj   now   now  Claude running"
      "+ new       proj"
    """
    status_str = format_status(term, row.status)

    if row.is_action:
        # Action row: "+ new       proj"
        label = row.short_id.ljust(COL_ID)
        proj_part = row.project[:project_col_width].ljust(project_col_width)
        return f"{status_str} {label}  {proj_part}"

    # Build columns: status, id, project, age, updated, message
    id_part = row.short_id.ljust(COL_ID)
    proj_part = row.project[:project_col_width].ljust(project_col_width)
    age_part = row.age.rjust(COL_AGE) if row.age else "".rjust(COL_AGE)
    updated_part = row.updated.rjust(COL_AGE) if row.updated else "".rjust(COL_AGE)

    # Calculate space for message (width minus fixed columns and spacing)
    # Fixed: "● " + id + "  " + proj + "  " + age + "  " + upd + "  "
    fixed_width = 2 + COL_ID + 2 + project_col_width + 2 + COL_AGE + 2 + COL_AGE + 2
    msg_width = max(0, width - fixed_width)
    # Strip newlines for single-line display, then clip to width
    msg_text = row.message.replace("\n", " ") if row.message else ""
    msg_part = msg_text[:msg_width]

    return f"{status_str} {id_part}  {proj_part}  {age_part}  {updated_part}  {msg_part}"


def render_line(term: Terminal, width: int, char: str = BOX_H) -> str:
    """Render a horizontal line of the given width."""
    return char * width


def render_header(term: Terminal, width: int) -> None:
    """Render the title header."""
    title = " HOPPER "
    # Center the title in the line
    line_len = width - len(title)
    left = line_len // 2
    right = line_len - left
    print(term.bold(BOX_H_BOLD * left + title + BOX_H_BOLD * right))
    print()


def render_table_header(term: Terminal, title: str, width: int, project_col_width: int) -> None:
    """Render a table section header with column labels."""
    # Table title
    print(term.bold(title))
    # Column headers: aligned with data columns
    proj_header = "PROJ".ljust(project_col_width)
    id_header = "ID".ljust(COL_ID)
    age_header = "AGE".rjust(COL_AGE)
    upd_header = "UPD".rjust(COL_AGE)
    header = f"    {id_header}  {proj_header}  {age_header}  {upd_header}  MESSAGE"
    print(term.dim + header + term.normal)


def render_footer(term: Terminal, width: int, state: "TUIState") -> None:
    """Render the footer with keybindings."""
    print()
    print(render_line(term, width))

    # Determine context-sensitive Enter action
    row = state.get_selected_row()
    if row and row.is_action:
        if state.is_add_project_selected:
            # Show CLI hint instead of New action
            enter_hint = "hop project add <path>"
            archive_hint = ""
            project_hint = "  ←→ Project"
        else:
            enter_hint = "⏎ New"
            archive_hint = ""
            project_hint = "  ←→ Project" if len(state.projects) > 0 else ""
    elif row:
        session = state.get_session(row.id)
        if session and session.state == "running":
            enter_hint = "⏎ Switch"
        else:
            enter_hint = "⏎ Resume"
        archive_hint = "  a Archive"
        project_hint = ""
    else:
        enter_hint = "⏎ Select"
        archive_hint = ""
        project_hint = ""

    hints = f" ↑↓/jk Navigate{project_hint}  {enter_hint}{archive_hint}  q Quit"
    print(term.dim + hints + term.normal)


def render(term: Terminal, state: TUIState) -> None:
    """Render the TUI to the terminal."""
    width = term.width or 40  # Fallback for tests

    print(term.home + term.clear, end="")

    # Header
    render_header(term, width)

    # Compute dynamic project column width
    project_col_width = compute_project_col_width(state)

    row_num = 0

    # ORE table
    render_table_header(term, "ORE", width, project_col_width)
    for row in state.ore_rows:
        line = format_row(term, row, width - 2, project_col_width)  # -2 for cursor prefix
        if row_num == state.cursor_index:
            print(term.reverse(f"> {line}"))
        else:
            print(f"  {line}")
        row_num += 1

    # Spacing between tables
    print()

    # PROCESSING table
    render_table_header(term, "PROCESSING", width, project_col_width)
    if state.processing_rows:
        for row in state.processing_rows:
            line = format_row(term, row, width - 2, project_col_width)
            if row_num == state.cursor_index:
                print(term.reverse(f"> {line}"))
            else:
                print(f"  {line}")
            row_num += 1
    else:
        print(term.dim + "    (empty)" + term.normal)

    # Footer
    render_footer(term, width, state)


def handle_enter(state: TUIState) -> TUIState:
    """Handle Enter key press on the selected row."""
    row = state.get_selected_row()
    if not row:
        return state

    if row.id == "new":
        # Get the selected project
        project = state.selected_project
        if not project:
            return state  # No project selected, can't create session

        # Create a new session with the project
        session = create_session(state.sessions, project.name)

        # Spawn hopper ore in the project directory
        window_id = spawn_claude(session.id, project.path)
        if window_id:
            session.tmux_window = window_id
            save_sessions(state.sessions)
        # Note: state will be updated by ore process via server broadcast

        return state.rebuild_rows()

    # Existing session - try to switch or respawn
    session = state.get_session(row.id)
    if not session:
        return state

    # Get project path for respawn
    project = find_project(session.project) if session.project else None
    project_path = project.path if project else None

    # Try to switch to existing window
    if session.tmux_window and switch_to_window(session.tmux_window):
        # Successfully switched - ore process manages state
        pass
    else:
        # Window doesn't exist or switch failed - respawn
        window_id = spawn_claude(session.id, project_path)
        if window_id:
            session.tmux_window = window_id
            save_sessions(state.sessions)
        # Note: state will be updated by ore process via server broadcast

    return state.rebuild_rows()


def handle_archive(state: TUIState) -> TUIState:
    """Handle 'a' key press to archive the selected session."""
    row = state.get_selected_row()
    if not row or row.is_action:
        # Can't archive action rows
        return state

    # Archive the session (removes from list and persists)
    archive_session(state.sessions, row.id)
    return state.rebuild_rows()


def run_tui(term: Terminal, server=None) -> int:
    """Run the TUI main loop.

    Args:
        term: blessed Terminal instance
        server: Optional Server instance. If provided, uses server's session list
                for shared state. Otherwise loads from disk.
    """
    # Use server's session list if available, otherwise load from disk
    if server is not None:
        sessions = server.sessions
    else:
        sessions = load_sessions()

    # Load active projects
    projects = get_active_projects()

    # Build initial state
    state = TUIState(sessions=sessions, projects=projects)
    state = state.rebuild_rows()

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        render(term, state)

        while True:
            key = term.inkey(timeout=1.0)

            if key.name == "KEY_UP" or key == "k":
                state = state.cursor_up()
            elif key.name == "KEY_DOWN" or key == "j":
                state = state.cursor_down()
            elif key.name == "KEY_LEFT" or key == "h":
                # Only cycle project on action row
                row = state.get_selected_row()
                if row and row.is_action:
                    state = state.project_left()
            elif key.name == "KEY_RIGHT" or key == "l":
                # Only cycle project on action row
                row = state.get_selected_row()
                if row and row.is_action:
                    state = state.project_right()
            elif key.name == "KEY_ENTER" or key == "\n" or key == "\r":
                state = handle_enter(state)
            elif key == "a":
                state = handle_archive(state)
            elif key == "q" or key.name == "KEY_ESCAPE":
                break

            # Rebuild rows from shared session list (may be updated by server)
            state = state.rebuild_rows()
            render(term, state)

    return 0
