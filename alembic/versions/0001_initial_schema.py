"""Initial restaurant, menu and business-hours schema.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """현재 SQLAlchemy 모델과 같은 초기 스키마를 생성한다."""

    op.create_table(
        "menu_catalog",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("cuisine", sa.String(length=20), nullable=False),
        sa.Column("search_keyword", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("price_hint", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.CheckConstraint("price_hint IS NULL OR price_hint >= 0", name="ck_menu_catalog_price_hint_nonnegative"),
        sa.CheckConstraint("cuisine IN ('한식', '중식', '일식', '양식', '샐러드')", name="ck_menu_catalog_cuisine_value"),
        sa.PrimaryKeyConstraint("id", name="pk_menu_catalog"),
        sa.UniqueConstraint("name", name="uq_menu_catalog_name"),
        sa.UniqueConstraint("normalized_name", name="uq_menu_catalog_normalized_name"),
    )
    op.create_index("ix_menu_catalog_filter", "menu_catalog", ["active", "cuisine", "price_hint"], unique=False)

    op.create_table(
        "restaurant",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category_name", sa.String(length=300), nullable=True),
        sa.Column("cuisine", sa.String(length=30), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("place_url", sa.String(length=1000), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_restaurant_latitude_range"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_restaurant_longitude_range"),
        sa.PrimaryKeyConstraint("id", name="pk_restaurant"),
    )
    op.create_index("ix_restaurant_cuisine", "restaurant", ["cuisine"], unique=False)
    op.create_index("ix_restaurant_location", "restaurant", ["latitude", "longitude"], unique=False)

    op.create_table(
        "menu_alias",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("menu_catalog_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["menu_catalog_id"], ["menu_catalog.id"], name="fk_menu_alias_menu_catalog_id_menu_catalog", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_menu_alias"),
        sa.UniqueConstraint("normalized_name", name="normalized_name"),
    )
    op.create_index("ix_menu_alias_catalog", "menu_alias", ["menu_catalog_id"], unique=False)

    op.create_table(
        "menu",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("restaurant_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("price_status", sa.String(length=20), server_default="missing", nullable=False),
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_menu_price_nonnegative"),
        sa.CheckConstraint("price_status IN ('known', 'missing', 'variable')", name="ck_menu_price_status_value"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurant.id"], name="fk_menu_restaurant_id_restaurant", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_menu"),
        sa.UniqueConstraint("restaurant_id", "normalized_name", name="restaurant_name"),
    )
    op.create_index("ix_menu_lookup", "menu", ["normalized_name", "price"], unique=False)

    op.create_table(
        "business_hours",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("restaurant_id", sa.String(length=40), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("holiday", sa.Boolean(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("ends_next_day", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_order_time", sa.Time(), nullable=True),
        sa.Column("sequence", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_business_hours_day_range"),
        sa.CheckConstraint("sequence >= 0", name="ck_business_hours_sequence_nonnegative"),
        sa.CheckConstraint("(start_time IS NULL AND end_time IS NULL) OR (start_time IS NOT NULL AND end_time IS NOT NULL)", name="ck_business_hours_time_pair"),
        sa.CheckConstraint("holiday IS NOT TRUE OR (start_time IS NULL AND end_time IS NULL)", name="ck_business_hours_holiday_without_hours"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurant.id"], name="fk_business_hours_restaurant_id_restaurant", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_business_hours"),
        sa.UniqueConstraint("restaurant_id", "day_of_week", "sequence", name="restaurant_day_sequence"),
    )
    op.create_index("ix_business_hours_lookup", "business_hours", ["restaurant_id", "day_of_week"], unique=False)

    op.create_table(
        "place_detail_status",
        sa.Column("restaurant_id", sa.String(length=40), nullable=False),
        sa.Column("menu_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("hours_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.CheckConstraint("menu_status IN ('pending', 'success', 'missing', 'fetch_failed', 'parse_failed')", name="ck_place_detail_status_menu_status_value"),
        sa.CheckConstraint("hours_status IN ('pending', 'success', 'missing', 'fetch_failed', 'parse_failed')", name="ck_place_detail_status_hours_status_value"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurant.id"], name="fk_place_detail_status_restaurant_id_restaurant", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("restaurant_id", name="pk_place_detail_status"),
    )


def downgrade() -> None:
    """의존 관계의 역순으로 초기 스키마를 제거한다."""

    op.drop_table("place_detail_status")
    op.drop_index("ix_business_hours_lookup", table_name="business_hours")
    op.drop_table("business_hours")
    op.drop_index("ix_menu_lookup", table_name="menu")
    op.drop_table("menu")
    op.drop_index("ix_menu_alias_catalog", table_name="menu_alias")
    op.drop_table("menu_alias")
    op.drop_index("ix_restaurant_location", table_name="restaurant")
    op.drop_index("ix_restaurant_cuisine", table_name="restaurant")
    op.drop_table("restaurant")
    op.drop_index("ix_menu_catalog_filter", table_name="menu_catalog")
    op.drop_table("menu_catalog")
