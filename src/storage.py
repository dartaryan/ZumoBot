"""GitHub storage — save transcripts and analyses to a single repo with per-user folders."""

from pathlib import Path

from github import Github, GithubException

from .config import GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH, DASHBOARD_BASE_URL


def _get_repo(token: str | None = None, repo_name: str | None = None):
    """Get PyGithub repo object."""
    t = token or GITHUB_TOKEN
    r = repo_name or GITHUB_REPO
    return Github(t).get_repo(r)


def save_file_to_github(
    filepath: str,
    content: str,
    commit_message: str,
    token: str | None = None,
    repo_name: str | None = None,
    branch: str | None = None,
) -> str:
    """Create or update a file in the GitHub repo. Returns file URL."""
    repo = _get_repo(token, repo_name)
    b = branch or GITHUB_BRANCH

    try:
        existing = repo.get_contents(filepath, ref=b)
        repo.update_file(filepath, commit_message, content, existing.sha, branch=b)
    except GithubException as e:
        if e.status == 404:
            repo.create_file(filepath, commit_message, content, branch=b)
        else:
            raise

    return f"https://github.com/{repo.full_name}/blob/{b}/{filepath}"


def save_session(
    user_folder: str,
    folder_name: str,
    transcript_md: str,
    analysis_md: str | None,
    summary: str,
    user_name: str = "",
    pw_hash: str | None = None,
) -> str:
    """Save a complete session to GitHub, update index, and regenerate dashboard.

    Returns dashboard URL with anchor.
    """
    base_path = f"{user_folder}/{folder_name}"
    commit_prefix = f"Add: {folder_name}"

    save_file_to_github(
        f"{base_path}/transcript.md",
        transcript_md,
        f"{commit_prefix} — transcript",
    )

    if analysis_md:
        save_file_to_github(
            f"{base_path}/analysis.md",
            analysis_md,
            f"{commit_prefix} — analysis",
        )

    update_user_index(user_folder)

    # Regenerate dashboard HTML on GitHub (best-effort)
    try:
        save_dashboard_to_github(user_folder, user_name, pw_hash)
    except Exception:
        pass

    if DASHBOARD_BASE_URL:
        return f"{DASHBOARD_BASE_URL}/{user_folder}#{folder_name}"
    return f"https://github.com/{GITHUB_REPO}/tree/{GITHUB_BRANCH}/{base_path}"


def update_user_index(user_folder: str) -> None:
    """Regenerate {user_folder}/index.md by scanning all session folders."""
    repo = _get_repo()

    try:
        contents = repo.get_contents(user_folder, ref=GITHUB_BRANCH)
    except GithubException as e:
        if e.status == 404:
            return
        raise

    # Collect session folders (directories matching date pattern)
    sessions = []
    for item in contents:
        if item.type == "dir" and len(item.name) >= 16 and item.name[4] == "-":
            # Try to read transcript.md first line for title
            title = item.name
            try:
                transcript = repo.get_contents(f"{item.path}/transcript.md", ref=GITHUB_BRANCH)
                first_line = transcript.decoded_content.decode("utf-8").split("\n")[0]
                if first_line.startswith("# "):
                    title = first_line[2:].strip()
            except GithubException:
                pass

            has_analysis = False
            try:
                repo.get_contents(f"{item.path}/analysis.md", ref=GITHUB_BRANCH)
                has_analysis = True
            except GithubException:
                pass

            sessions.append({
                "folder": item.name,
                "title": title,
                "date": item.name[:10],
                "has_analysis": has_analysis,
            })

    # Sort newest first
    sessions.sort(key=lambda s: s["folder"], reverse=True)

    # Build index markdown
    lines = [f"# Transcriptions — {user_folder}\n"]
    lines.append(f"Total sessions: {len(sessions)}\n")
    lines.append("| Date | Title | Analysis |")
    lines.append("|------|-------|----------|")

    for s in sessions:
        analysis_mark = "V" if s["has_analysis"] else "—"
        lines.append(
            f"| {s['date']} "
            f"| [{s['title']}]({s['folder']}/transcript.md) "
            f"| {analysis_mark} |"
        )

    index_content = "\n".join(lines) + "\n"

    save_file_to_github(
        f"{user_folder}/index.md",
        index_content,
        f"Update index for {user_folder}",
    )


def ensure_repo_structure(user_folder: str) -> None:
    """Ensure the user's folder exists in the repo."""
    repo = _get_repo()
    try:
        repo.get_contents(user_folder, ref=GITHUB_BRANCH)
    except GithubException as e:
        if e.status == 404:
            repo.create_file(
                f"{user_folder}/.gitkeep",
                f"Initialize folder for {user_folder}",
                "",
                branch=GITHUB_BRANCH,
            )
        else:
            raise


def save_dashboard_to_github(
    slug: str, name: str = "", pw_hash: str | None = None,
) -> str:
    """Generate dashboard HTML from GitHub sessions and push index.html."""
    from .dashboard import generate_dashboard_from_github

    html = generate_dashboard_from_github(slug, name, pw_hash)
    return save_file_to_github(
        f"{slug}/index.html",
        html,
        f"Update dashboard for {slug}",
    )


def save_session_local(
    output_dir: Path,
    user_folder: str,
    folder_name: str,
    transcript_md: str,
    analysis_md: str | None,
) -> Path:
    """Save session to local filesystem (--local mode)."""
    session_dir = output_dir / user_folder / folder_name
    session_dir.mkdir(parents=True, exist_ok=True)

    (session_dir / "transcript.md").write_text(transcript_md, encoding="utf-8")

    if analysis_md:
        (session_dir / "analysis.md").write_text(analysis_md, encoding="utf-8")

    return session_dir
