"""AI feedback service."""


async def generate_feedback(
    session_id: str,
    sim_slug: str,
    student_id: str = None,
    sim_state: dict = None,
    student_action: dict = None,
    hint_level: int = 1,
):
    """Generate contextual AI feedback for a student action."""
    raise NotImplementedError


async def rate_feedback(feedback_id: str, helpful: bool, comment: str = None):
    """Record student rating of feedback helpfulness."""
    raise NotImplementedError
