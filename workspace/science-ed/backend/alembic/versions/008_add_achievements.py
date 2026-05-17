"""add achievement tables and streak fields

Revision ID: 008_add_achievements
Revises: 007_update_severity_constraint
Create Date: 2026-05-17 18:05:00.000000

Adds:
- achievement_definitions table
- student_achievements table
- users.streak_count (Integer, default 0)
- users.last_streak_date (Date, nullable)
- Seeds the initial 10 achievement definitions
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "008_add_achievements"
down_revision: Union[str, None] = "007_update_severity_constraint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Create achievement_definitions table ──────────────────────────────────
    op.create_table(
        "achievement_definitions",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name_en", sa.String(), nullable=False),
        sa.Column("display_name_es", sa.String(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=False),
        sa.Column("description_es", sa.Text(), nullable=True),
        sa.Column("icon_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("criteria_type", sa.String(), nullable=False),
        sa.Column("criteria_value", JSONB, nullable=False, server_default="{}"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code"),
    )

    # ── Create student_achievements table ────────────────────────────────────
    op.create_table(
        "student_achievements",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("student_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("achievement_code", sa.String(), nullable=False),
        sa.Column(
            "unlocked_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("context_data", JSONB, nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["achievement_code"], ["achievement_definitions.code"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_student_achievements_student_code",
        "student_achievements",
        ["student_id", "achievement_code"],
        unique=True,
    )

    # ── Add streak columns to users ──────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column("streak_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("last_streak_date", sa.Date(), nullable=True),
    )

    # ── Seed achievement definitions ─────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    achievements = [
        # Milestone badges
        {
            "code": "explorer",
            "display_name_en": "Explorer",
            "display_name_es": "Explorador",
            "description_en": "Complete your first simulation",
            "description_es": "Completa tu primera simulación",
            "icon_name": "compass",
            "category": "milestone",
            "criteria_type": "sim_count",
            "criteria_value": '{"count": 1}',
            "sort_order": 1,
            "is_secret": "false",
        },
        {
            "code": "scholar",
            "display_name_en": "Scholar",
            "display_name_es": "Erudito",
            "description_en": "Complete 10 simulations",
            "description_es": "Completa 10 simulaciones",
            "icon_name": "book",
            "category": "milestone",
            "criteria_type": "sim_count",
            "criteria_value": '{"count": 10}',
            "sort_order": 2,
            "is_secret": "false",
        },
        {
            "code": "scientist",
            "display_name_en": "Scientist",
            "display_name_es": "Científico",
            "description_en": "Complete 50 simulations",
            "description_es": "Completa 50 simulaciones",
            "icon_name": "flask",
            "category": "milestone",
            "criteria_type": "sim_count",
            "criteria_value": '{"count": 50}',
            "sort_order": 3,
            "is_secret": "false",
        },
        {
            "code": "explorer_100",
            "display_name_en": "Galactic Explorer",
            "display_name_es": "Explorador Galáctico",
            "description_en": "Complete 100 simulations",
            "description_es": "Completa 100 simulaciones",
            "icon_name": "rocket",
            "category": "milestone",
            "criteria_type": "sim_count",
            "criteria_value": '{"count": 100}',
            "sort_order": 4,
            "is_secret": "false",
        },
        # Streak badges
        {
            "code": "streak_3",
            "display_name_en": "Three-Day Streak",
            "display_name_es": "Racha de 3 Días",
            "description_en": "Use the platform for 3 consecutive days",
            "description_es": "Usa la plataforma 3 días consecutivos",
            "icon_name": "fire",
            "category": "streak",
            "criteria_type": "streak_days",
            "criteria_value": '{"days": 3}',
            "sort_order": 5,
            "is_secret": "false",
        },
        {
            "code": "streak_7",
            "display_name_en": "Week Warrior",
            "display_name_es": "Guerrero Semanal",
            "description_en": "Use the platform for 7 consecutive days",
            "description_es": "Usa la plataforma 7 días consecutivos",
            "icon_name": "fire",
            "category": "streak",
            "criteria_type": "streak_days",
            "criteria_value": '{"days": 7}',
            "sort_order": 6,
            "is_secret": "false",
        },
        {
            "code": "streak_30",
            "display_name_en": "Month Master",
            "display_name_es": "Maestro Mensual",
            "description_en": "Use the platform for 30 consecutive days",
            "description_es": "Usa la plataforma 30 días consecutivos",
            "icon_name": "crown",
            "category": "streak",
            "criteria_type": "streak_days",
            "criteria_value": '{"days": 30}',
            "sort_order": 7,
            "is_secret": "false",
        },
        # Mastery badges
        {
            "code": "specialist",
            "display_name_en": "Specialist",
            "display_name_es": "Especialista",
            "description_en": "Master all simulations in one category",
            "description_es": "Domina todas las simulaciones en una categoría",
            "icon_name": "star",
            "category": "mastery",
            "criteria_type": "category_mastery",
            "criteria_value": "{}",
            "sort_order": 8,
            "is_secret": "false",
        },
        {
            "code": "perfectionist",
            "display_name_en": "Perfectionist",
            "display_name_es": "Perfeccionista",
            "description_en": "Score 90% or higher on a task",
            "description_es": "Obtén un 90% o más en una tarea",
            "icon_name": "target",
            "category": "special",
            "criteria_type": "task_score",
            "criteria_value": '{"score": 90}',
            "sort_order": 9,
            "is_secret": "false",
        },
        # Time-based badges
        {
            "code": "night_owl",
            "display_name_en": "Night Owl",
            "display_name_es": "Búho Nocturno",
            "description_en": "Complete a simulation between 10 PM and 5 AM",
            "description_es": "Completa una simulación entre las 10 PM y las 5 AM",
            "icon_name": "moon",
            "category": "time_based",
            "criteria_type": "time_based",
            "criteria_value": '{"start_hour": 22, "end_hour": 5, "label": "night"}',
            "sort_order": 10,
            "is_secret": "false",
        },
        {
            "code": "early_bird",
            "display_name_en": "Early Bird",
            "display_name_es": "Madrugador",
            "description_en": "Complete a simulation between 5 AM and 8 AM",
            "description_es": "Completa una simulación entre las 5 AM y las 8 AM",
            "icon_name": "sun",
            "category": "time_based",
            "criteria_type": "time_based",
            "criteria_value": '{"start_hour": 5, "end_hour": 8, "label": "morning"}',
            "sort_order": 11,
            "is_secret": "false",
        },
    ]

    for ach in achievements:
        # Use safe string formatting for seed data (fixed values, no user input)
        cv = ach["criteria_value"]
        op.execute(
            sa.text(
                f"""INSERT INTO achievement_definitions
(code, display_name_en, display_name_es, description_en, description_es,
 icon_name, category, criteria_type, criteria_value, sort_order, is_secret, updated_at)
VALUES ('{ach["code"]}', '{ach["display_name_en"]}',
        '{ach["display_name_es"]}', '{ach["description_en"]}',
        '{ach["description_es"]}', '{ach["icon_name"]}',
        '{ach["category"]}', '{ach["criteria_type"]}',
        '{cv}'::jsonb,
        {ach["sort_order"]}, {ach["is_secret"]}, '{now}')"""
            )
        )


def downgrade() -> None:
    op.drop_table("student_achievements")
    op.drop_table("achievement_definitions")
    op.drop_column("users", "last_streak_date")
    op.drop_column("users", "streak_count")
