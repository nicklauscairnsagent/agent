"""Tests for the gamification/achievement system — service layer and endpoints.

Tests cover:
- Catalog listing (service + endpoint)
- Streak tracking (daily, consecutive, broken, same day)
- Milestone badge unlocks (Explorer, Scholar, Scientist)
- Streak badge unlocks (3, 7, 30 days)
- Perfectionist badge (90%+ on a task)
- Category mastery (Specialist)
- Time-based badges (Night Owl, Early Bird)
- Progress query
- Notification/dismiss flow
- No regressions from catalog endpoint calling
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import get_db
from app.main import app
from app.models import Base, SessionModel, Sim, TaskResult, User
from app.models.achievement import (
    AchievementDefinition,
    StudentAchievement,
)
from app.services.achievements import (
    check_and_unlock_achievements,
    dismiss_notifications,
    get_achievement_catalog,
    get_achievement_progress,
    get_completed_sim_count,
    get_mastered_categories,
    get_pending_notifications,
    get_student_achievement_codes,
    get_student_achievements,
    get_task_high_score,
    update_streak,
)
from app.services.auth_service import create_access_token

# ---------------------------------------------------------------------------
# Test DB fixture
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite://"


@pytest.fixture
async def db_session():
    """Create a clean in-memory SQLite DB for each test."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def override_get_db(db_session):
    """Override the FastAPI dependency so endpoints use our test DB."""

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Data seeders
# ---------------------------------------------------------------------------


async def _seed_achievement_definitions(db: AsyncSession) -> list[AchievementDefinition]:
    """Seed the standard achievement catalog."""
    definitions = [
        AchievementDefinition(
            code="explorer",
            display_name_en="Explorer",
            display_name_es="Explorador",
            description_en="Complete your first simulation",
            icon_name="compass",
            category="milestone",
            criteria_type="sim_count",
            criteria_value={"count": 1},
            sort_order=1,
        ),
        AchievementDefinition(
            code="scholar",
            display_name_en="Scholar",
            display_name_es="Erudito",
            description_en="Complete 10 simulations",
            icon_name="book",
            category="milestone",
            criteria_type="sim_count",
            criteria_value={"count": 10},
            sort_order=2,
        ),
        AchievementDefinition(
            code="scientist",
            display_name_en="Scientist",
            display_name_es="Científico",
            description_en="Complete 50 simulations",
            icon_name="flask",
            category="milestone",
            criteria_type="sim_count",
            criteria_value={"count": 50},
            sort_order=3,
        ),
        AchievementDefinition(
            code="explorer_100",
            display_name_en="Galactic Explorer",
            description_en="Complete 100 simulations",
            icon_name="rocket",
            category="milestone",
            criteria_type="sim_count",
            criteria_value={"count": 100},
            sort_order=4,
        ),
        AchievementDefinition(
            code="streak_3",
            display_name_en="Three-Day Streak",
            description_en="3 consecutive days",
            icon_name="fire",
            category="streak",
            criteria_type="streak_days",
            criteria_value={"days": 3},
            sort_order=5,
        ),
        AchievementDefinition(
            code="streak_7",
            display_name_en="Week Warrior",
            description_en="7 consecutive days",
            icon_name="fire",
            category="streak",
            criteria_type="streak_days",
            criteria_value={"days": 7},
            sort_order=6,
        ),
        AchievementDefinition(
            code="streak_30",
            display_name_en="Month Master",
            description_en="30 consecutive days",
            icon_name="crown",
            category="streak",
            criteria_type="streak_days",
            criteria_value={"days": 30},
            sort_order=7,
        ),
        AchievementDefinition(
            code="specialist",
            display_name_en="Specialist",
            description_en="Master all sims in one category",
            icon_name="star",
            category="mastery",
            criteria_type="category_mastery",
            criteria_value={},
            sort_order=8,
        ),
        AchievementDefinition(
            code="perfectionist",
            display_name_en="Perfectionist",
            description_en="Score 90%+ on a task",
            icon_name="target",
            category="special",
            criteria_type="task_score",
            criteria_value={"score": 90},
            sort_order=9,
        ),
        AchievementDefinition(
            code="night_owl",
            display_name_en="Night Owl",
            description_en="Complete a sim between 10 PM and 5 AM",
            icon_name="moon",
            category="time_based",
            criteria_type="time_based",
            criteria_value={"start_hour": 22, "end_hour": 5, "label": "night"},
            sort_order=10,
            is_secret=False,
        ),
        AchievementDefinition(
            code="early_bird",
            display_name_en="Early Bird",
            description_en="Complete a sim between 5 AM and 8 AM",
            icon_name="sun",
            category="time_based",
            criteria_type="time_based",
            criteria_value={"start_hour": 5, "end_hour": 8, "label": "morning"},
            sort_order=11,
            is_secret=False,
        ),
    ]
    for d in definitions:
        db.add(d)
    await db.flush()
    return definitions


async def _create_user(
    db: AsyncSession, email: str = "student@test.com", role: str = "student"
) -> User:
    user = User(email=email, display_name=email.split("@")[0], role=role, auth_provider="password")
    db.add(user)
    await db.flush()
    return user


async def _create_sim(
    db: AsyncSession,
    slug: str = "test-sim",
    category: str = "physical-sciences",
) -> Sim:
    sim = Sim(
        slug=slug,
        title_en="Test Sim",
        category_slug=category,
        category_en="Physical Sciences",
        ngss_standards=["HS-PS3-2"],
        url_en=f"/en/simulations/{slug}/",
    )
    db.add(sim)
    await db.flush()
    return sim


async def _create_session(
    db: AsyncSession,
    student: User,
    sim: Sim,
    completed: bool = True,
) -> SessionModel:
    now = datetime.now(timezone.utc)
    sess = SessionModel(
        student_id=student.id,
        sim_id=sim.id,
        started_at=now - timedelta(minutes=10),
        ended_at=now if completed else None,
        duration_seconds=600 if completed else None,
        is_completed=completed,
        expires_at=now + timedelta(hours=24),
    )
    db.add(sess)
    await db.flush()
    return sess


async def _create_task_result(
    db: AsyncSession,
    student: User,
    sim: Sim,
    session: SessionModel,
    score: float = 95.0,
    correct: int = 9,
    total: int = 10,
) -> TaskResult:
    tr = TaskResult(
        session_id=session.id,
        student_id=student.id,
        sim_id=sim.id,
        task_slug="test-task",
        task_type="multiple_choice",
        answers={},
        score=score,
        correct_count=correct,
        total_count=total,
    )
    db.add(tr)
    await db.flush()
    return tr


def _token_for(user: User) -> str:
    return create_access_token(subject=str(user.id), role=user.role)


# ███████████████████████████████████████████████████████████████████████████████
# Service-layer tests
# ███████████████████████████████████████████████████████████████████████████████


class TestCatalog:
    """Achievement definition catalog."""

    async def test_get_catalog_returns_all(self, db_session):
        defs = await _seed_achievement_definitions(db_session)
        catalog = await get_achievement_catalog(db_session)
        assert len(catalog) == len(defs)
        codes = [a.code for a in catalog]
        assert "explorer" in codes
        assert "scholar" in codes
        assert "scientist" in codes

    async def test_catalog_ordered_by_sort_order(self, db_session):
        await _seed_achievement_definitions(db_session)
        catalog = await get_achievement_catalog(db_session)
        orders = [a.sort_order for a in catalog]
        assert orders == sorted(orders)


class TestStreak:
    """Daily streak tracking."""

    async def test_streak_starts_at_one(self, db_session):
        student = await _create_user(db_session)
        result = await update_streak(db_session, student.id)
        assert result["current_streak"] == 1
        assert result["last_active_date"] == date.today()

    async def test_streak_increments_consecutive_day(self, db_session):
        student = await _create_user(db_session)
        yesterday = date.today() - timedelta(days=1)

        # Simulate yesterday's activity
        student.streak_count = 1
        student.last_streak_date = yesterday
        await db_session.flush()

        result = await update_streak(db_session, student.id)
        assert result["current_streak"] == 2

    async def test_streak_same_day_no_increment(self, db_session):
        student = await _create_user(db_session)
        today = date.today()

        student.streak_count = 5
        student.last_streak_date = today
        await db_session.flush()

        result = await update_streak(db_session, student.id)
        assert result["current_streak"] == 5  # still 5

    async def test_streak_resets_after_gap(self, db_session):
        student = await _create_user(db_session)
        three_days_ago = date.today() - timedelta(days=3)

        student.streak_count = 5
        student.last_streak_date = three_days_ago
        await db_session.flush()

        result = await update_streak(db_session, student.id)
        assert result["current_streak"] == 1  # reset

    async def test_streak_allows_specific_date(self, db_session):
        student = await _create_user(db_session)
        specific = date(2026, 1, 1)
        result = await update_streak(db_session, student.id, activity_date=specific)
        assert result["last_active_date"] == specific


class TestMilestoneUnlocks:
    """Milestone badges triggered by sim completion count."""

    async def test_explorer_unlocks_at_1_completion(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "explorer" in codes

    async def test_explorer_does_not_unlock_at_0(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "explorer" not in codes

    async def test_scholar_unlocks_at_10_completions(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        for i in range(10):
            sim = await _create_sim(db_session, slug=f"sim-{i}")
            await _create_session(db_session, student, sim, completed=True)

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "explorer" in codes
        assert "scholar" in codes

    async def test_scientist_unlocks_at_50_completions(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        for i in range(50):
            sim = await _create_sim(db_session, slug=f"sim-{i}")
            await _create_session(db_session, student, sim, completed=True)

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "explorer" in codes
        assert "scholar" in codes
        assert "scientist" in codes

    async def test_already_unlocked_not_duplicated(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)

        # First check unlocks explorer + specialist (1 sim = all in one category)
        unlocked_1 = await check_and_unlock_achievements(db_session, student.id)
        codes_1 = {u.achievement_code for u in unlocked_1}
        assert "explorer" in codes_1
        explorer_count = sum(1 for u in unlocked_1 if u.achievement_code == "explorer")
        assert explorer_count == 1  # not duplicated

        # Second check should not re-unlock anything
        unlocked_2 = await check_and_unlock_achievements(db_session, student.id)
        assert len(unlocked_2) == 0

    async def test_get_completed_sim_count(self, db_session):
        student = await _create_user(db_session)
        count = await get_completed_sim_count(db_session, student.id)
        assert count == 0

        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)
        count = await get_completed_sim_count(db_session, student.id)
        assert count == 1


class TestStreakAchievements:
    """Streak badges triggered by consecutive days."""

    async def test_streak_3_unlocks(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        student.streak_count = 3
        student.last_streak_date = date.today()
        await db_session.flush()

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "streak_3" in codes

    async def test_streak_7_and_3_unlock_together(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        student.streak_count = 7
        await db_session.flush()

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "streak_3" in codes
        assert "streak_7" in codes

    async def test_streak_30_unlocks(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        student.streak_count = 30
        await db_session.flush()

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "streak_30" in codes

    async def test_streak_below_threshold_does_not_unlock(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        student.streak_count = 2
        await db_session.flush()

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "streak_3" not in codes

    async def test_streak_0_does_not_unlock(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "streak_3" not in codes

    async def test_streak_consecutive_days_model_updates(self, db_session):
        """Verify streak_count is persisted on the User model correctly."""
        student = await _create_user(db_session)

        # Day 1
        await update_streak(db_session, student.id, activity_date=date(2026, 1, 1))
        result = await db_session.execute(select(User).where(User.id == student.id))
        assert result.scalar_one().streak_count == 1

        # Day 2
        await update_streak(db_session, student.id, activity_date=date(2026, 1, 2))
        result = await db_session.execute(select(User).where(User.id == student.id))
        assert result.scalar_one().streak_count == 2


class TestPerfectionist:
    """Perfectionist badge — 90%+ on a task."""

    async def test_perfectionist_unlocks_at_90_percent(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        sess = await _create_session(db_session, student, sim)
        await _create_task_result(db_session, student, sim, sess, score=90.0, correct=9, total=10)

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "perfectionist" in codes

    async def test_perfectionist_does_not_unlock_below_90(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        sess = await _create_session(db_session, student, sim)
        await _create_task_result(db_session, student, sim, sess, score=80.0, correct=8, total=10)

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "perfectionist" not in codes

    async def test_get_task_high_score(self, db_session):
        student = await _create_user(db_session)
        score = await get_task_high_score(db_session, student.id)
        assert score == 0.0

        sim = await _create_sim(db_session)
        sess = await _create_session(db_session, student, sim)
        await _create_task_result(db_session, student, sim, sess, score=85.0)

        score = await get_task_high_score(db_session, student.id)
        assert score == 85.0


class TestNightOwlAndEarlyBird:
    """Time-based badges."""

    async def test_night_owl_unlocks_with_context_hint(self, db_session):
        """night_owl has label='night' → context key is is_night_hour."""
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        unlocked = await check_and_unlock_achievements(
            db_session, student.id,
            context={"is_night_hour": True, "sim_slug": "test"}
        )
        codes = {u.achievement_code for u in unlocked}
        assert "night_owl" in codes

    async def test_early_bird_wrong_key_does_not_unlock(self, db_session):
        """early_bird has label='morning' → key is is_morning_hour, not is_morning."""
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        unlocked = await check_and_unlock_achievements(
            db_session, student.id,
            context={"is_morning": True, "sim_slug": "test"}
        )
        codes = {u.achievement_code for u in unlocked}
        assert "early_bird" not in codes  # wrong key

    async def test_early_bird_unlocks_with_correct_key(self, db_session):
        """early_bird has label='morning' → context key is is_morning_hour."""
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        unlocked = await check_and_unlock_achievements(
            db_session, student.id,
            context={"is_morning_hour": True, "sim_slug": "test"}
        )
        codes = {u.achievement_code for u in unlocked}
        assert "early_bird" in codes

    async def test_time_badges_require_correct_context(self, db_session):
        """Only unlock when the matching time context is passed."""
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        # No context => no time badges
        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "night_owl" not in codes
        assert "early_bird" not in codes

    async def test_night_owl_unlocks_with_exact_label_match(self, db_session):
        """night_owl has criteria_value label='night', so key is is_night_hour."""
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        unlocked = await check_and_unlock_achievements(
            db_session, student.id,
            context={"is_night_hour": True, "sim_slug": "test"}
        )
        codes = {u.achievement_code for u in unlocked}
        assert "night_owl" in codes


class TestSpecialsit:
    """Specialist badge — all sims in a category mastered."""

    async def test_specialist_unlocks_when_all_category_sims_completed(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        # Create 2 sims in the same category
        sim1 = await _create_sim(db_session, slug="sim-a", category="physics")
        sim2 = await _create_sim(db_session, slug="sim-b", category="physics")

        await _create_session(db_session, student, sim1, completed=True)
        await _create_session(db_session, student, sim2, completed=True)

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "specialist" in codes

    async def test_specialist_does_not_unlock_without_all_done(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        sim1 = await _create_sim(db_session, slug="sim-a", category="physics")
        await _create_sim(db_session, slug="sim-b", category="physics")

        await _create_session(db_session, student, sim1, completed=True)
        # sim2 is not started

        unlocked = await check_and_unlock_achievements(db_session, student.id)
        codes = {u.achievement_code for u in unlocked}
        assert "specialist" not in codes


class TestNotifications:
    """Notification/dismiss flow."""

    async def test_pending_notifications(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)

        # Unlock explorer
        await check_and_unlock_achievements(db_session, student.id)

        pending = await get_pending_notifications(db_session, student.id)
        codes = {p.achievement_code for p in pending}
        assert "explorer" in codes
        assert all(p.notified is False for p in pending)

    async def test_dismiss_notifications(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)

        await check_and_unlock_achievements(db_session, student.id)

        dismissed = await dismiss_notifications(db_session, student.id)
        assert dismissed >= 1

        pending = await get_pending_notifications(db_session, student.id)
        assert len(pending) == 0

    async def test_already_dismissed_returns_zero(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)

        await check_and_unlock_achievements(db_session, student.id)
        await dismiss_notifications(db_session, student.id)

        dismissed_again = await dismiss_notifications(db_session, student.id)
        assert dismissed_again == 0


class TestStudentAchievements:
    """Student achievement query helpers."""

    async def test_get_student_achievements(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        result = await get_student_achievements(db_session, student.id)
        assert result == []

    async def test_get_student_achievement_codes(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        codes = await get_student_achievement_codes(db_session, student.id)
        assert codes == set()

    async def test_get_completed_sim_count_multiple_sims(self, db_session):
        student = await _create_user(db_session)
        sim1 = await _create_sim(db_session, slug="sim-1")
        sim2 = await _create_sim(db_session, slug="sim-2")
        sim3 = await _create_sim(db_session, slug="sim-3")

        await _create_session(db_session, student, sim1, completed=True)
        await _create_session(db_session, student, sim2, completed=True)
        await _create_session(db_session, student, sim3, completed=False)

        count = await get_completed_sim_count(db_session, student.id)
        assert count == 2  # sim3 is not completed

    async def test_distinct_sims_only_counted_once(self, db_session):
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)
        await _create_session(db_session, student, sim, completed=True)  # another session

        count = await get_completed_sim_count(db_session, student.id)
        assert count == 1  # same sim


class TestGetMasteredCategories:
    """Category mastery helper."""

    async def test_no_mastered_categories_initially(self, db_session):
        student = await _create_user(db_session)
        mastered = await get_mastered_categories(db_session, student.id)
        assert mastered == []

    async def test_mastered_when_all_completed(self, db_session):
        student = await _create_user(db_session)
        sim1 = await _create_sim(db_session, slug="s1", category="physics")
        sim2 = await _create_sim(db_session, slug="s2", category="physics")
        await _create_session(db_session, student, sim1, completed=True)
        await _create_session(db_session, student, sim2, completed=True)

        mastered = await get_mastered_categories(db_session, student.id)
        assert "physics" in mastered

    async def test_not_mastered_when_some_missing(self, db_session):
        student = await _create_user(db_session)
        sim1 = await _create_sim(db_session, slug="s1", category="physics")
        await _create_sim(db_session, slug="s2", category="physics")  # not completed
        await _create_session(db_session, student, sim1, completed=True)

        mastered = await get_mastered_categories(db_session, student.id)
        assert "physics" not in mastered


class TestAchievementProgress:
    """Progress query."""

    async def test_progress_all_zero_initially(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        items = await get_achievement_progress(db_session, student.id)
        assert len(items) == 11  # All 11 definitions
        for item in items:
            assert item["unlocked"] is False
            assert item["progress"] == 0.0

    async def test_progress_partial_sim_count(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        # Complete 5 sims — 50% toward Scholar (10)
        for i in range(5):
            sim = await _create_sim(db_session, slug=f"s-{i}")
            await _create_session(db_session, student, sim, completed=True)

        items = await get_achievement_progress(db_session, student.id)
        progress_map = {i["achievement"].code: i for i in items}

        assert progress_map["explorer"]["progress"] == 1.0  # 5 >= 1
        assert progress_map["scholar"]["progress"] == 0.5  # 5/10
        assert "5/10" in progress_map["scholar"]["progress_text"]

    async def test_progress_full_completion(self, db_session):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)

        for i in range(10):
            sim = await _create_sim(db_session, slug=f"s-{i}")
            await _create_session(db_session, student, sim, completed=True)

        # Unlock achievements first
        await check_and_unlock_achievements(db_session, student.id)

        items = await get_achievement_progress(db_session, student.id)
        progress_map = {i["achievement"].code: i for i in items}

        assert progress_map["explorer"]["progress"] == 1.0
        assert progress_map["scholar"]["progress"] == 1.0
        assert progress_map["explorer"]["unlocked"] is True
        assert progress_map["scholar"]["unlocked"] is True


# ███████████████████████████████████████████████████████████████████████████████
# Endpoint tests
# ███████████████████████████████████████████████████████████████████████████████


class TestAchievementsEndpoint:
    """GET /api/v1/achievements"""

    async def test_catalog_endpoint(self, db_session, override_get_db):
        await _seed_achievement_definitions(db_session)
        # Need to seed before starting client
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/achievements")
            assert resp.status_code == 200
            data = resp.json()
            assert "achievements" in data
            codes = [a["code"] for a in data["achievements"]]
            assert "explorer" in codes
            assert "scholar" in codes

    async def test_catalog_no_auth_required(self, db_session, override_get_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/achievements")
            assert resp.status_code == 200  # Public endpoint


class TestStudentAchievementsEndpoint:
    """GET /api/v1/achievements/student"""

    async def test_student_endpoint_requires_auth(self, db_session, override_get_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/achievements/student")
            assert resp.status_code == 401

    async def test_student_endpoint_returns_badges_and_streak(self, db_session, override_get_db):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)
        token = _token_for(student)

        # Unlock explorer
        await check_and_unlock_achievements(db_session, student.id)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/achievements/student",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "achievements" in data
            assert "streak" in data
            codes = [a["achievement"]["code"] for a in data["achievements"]]
            assert "explorer" in codes


class TestCheckEndpoint:
    """POST /api/v1/achievements/check"""

    async def test_check_endpoint_requires_auth(self, db_session, override_get_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/achievements/check")
            assert resp.status_code == 401

    async def test_check_unlocks_explorer(self, db_session, override_get_db):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)
        token = _token_for(student)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/achievements/check",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "newly_unlocked" in data
            assert "streak_info" in data
            codes = [a["achievement"]["code"] for a in data["newly_unlocked"]]
            assert "explorer" in codes

    async def test_check_returns_streak_info(self, db_session, override_get_db):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        token = _token_for(student)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/achievements/check",
                headers={"Authorization": f"Bearer {token}"},
            )
            data = resp.json()
            assert data["streak_info"]["current_streak"] == 1

    async def test_check_empty_when_no_new_unlocks(self, db_session, override_get_db):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        token = _token_for(student)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/achievements/check",
                headers={"Authorization": f"Bearer {token}"},
            )
            data = resp.json()
            assert data["newly_unlocked"] == []


class TestProgressEndpoint:
    """GET /api/v1/achievements/progress"""

    async def test_progress_endpoint_requires_auth(self, db_session, override_get_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/achievements/progress")
            assert resp.status_code == 401

    async def test_progress_endpoint_returns_items(self, db_session, override_get_db):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        token = _token_for(student)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/achievements/progress",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "items" in data
            assert "total_completed" in data
            assert "total_available" in data
            assert data["total_available"] == 11  # all definitions


class TestNotificationEndpoint:
    """GET/POST /api/v1/achievements/notifications"""

    async def test_notifications_require_auth(self, db_session, override_get_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/achievements/notifications")
            assert resp.status_code == 401

    async def test_dismiss_requires_auth(self, db_session, override_get_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/achievements/notifications/dismiss")
            assert resp.status_code == 401

    async def test_notifications_flow(self, db_session, override_get_db):
        await _seed_achievement_definitions(db_session)
        student = await _create_user(db_session)
        sim = await _create_sim(db_session)
        await _create_session(db_session, student, sim, completed=True)
        token = _token_for(student)

        await check_and_unlock_achievements(db_session, student.id)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Get pending
            resp = await client.get(
                "/api/v1/achievements/notifications",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["unlocks"]) >= 1

            # Dismiss
            resp = await client.post(
                "/api/v1/achievements/notifications/dismiss",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["dismissed"] >= 1

            # Should be empty now
            resp = await client.get(
                "/api/v1/achievements/notifications",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["unlocks"]) == 0
