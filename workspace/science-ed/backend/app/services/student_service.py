"""Student progress and analytics service."""


async def get_student_progress(student_id: str):
    """Get overall student progress across all sims."""
    raise NotImplementedError


async def get_skill_state(student_id: str, skill_id: str):
    """Get BKT state for a specific skill."""
    raise NotImplementedError


async def claim_anonymous_data(anon_token: str, student_id: str):
    """Merge anonymous session data into a student account."""
    raise NotImplementedError
