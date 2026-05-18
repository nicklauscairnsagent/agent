"""Session management service."""


async def create_session(
    sim_slug: str,
    student_id=None,
    task_slug=None,
    page_type="sim",
    anon_token=None,
    device_info=None,
    referrer=None,
):
    """Create a new learning session and return session_id + anon_token."""
    raise NotImplementedError


async def end_session(session_id: str, duration_seconds: int = None, completed: bool = False):
    """End a learning session and calculate duration."""
    raise NotImplementedError
