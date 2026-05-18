"""Authentication and magic link service."""


async def send_magic_link(email: str, role: str = None):
    """Generate and send a magic link email."""
    raise NotImplementedError


async def verify_token(token: str):
    """Verify a magic link token and return JWT session tokens."""
    raise NotImplementedError
