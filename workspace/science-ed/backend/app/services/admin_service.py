"""Admin operations service."""


async def get_admin_stats():
    """Get platform-wide statistics."""
    raise NotImplementedError


async def refresh_sim_catalog():
    """Re-sync sim catalog from GitHub Pages catalog.json."""
    raise NotImplementedError
