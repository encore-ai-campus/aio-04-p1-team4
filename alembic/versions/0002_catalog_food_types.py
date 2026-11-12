"""카탈로그 음식 종류 확장 및 기존 분류 변환.

Revision ID: 0002_catalog_food_types
Revises: 0001_initial_schema
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_catalog_food_types"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

# 과거 마이그레이션 결과가 향후 코드 변경에 영향을 받지 않도록 목록을 고정한다.
NEW_VALUES = (
    "한식", "중식", "일식/회", "양식", "분식", "패스트푸드", "치킨",
    "도시락/구내식당", "뷔페식", "냉면", "고기", "카페/빵", "술집", "기타",
)
OLD_VALUES = ("한식", "중식", "일식", "양식", "샐러드")
CONSTRAINT = "ck_menu_catalog_cuisine_value"


def _drop_check():
    # SQLite는 CHECK 직접 변경이 불가능해 Alembic 배치 복사를 사용한다.
    # 메뉴 PK·별칭 FK·인덱스·활성 상태·가격·작성 시각은 그대로 복사된다.
    # 초기 Alembic 생성 DB와 create_all DB는 naming convention 접두사 수가 다를 수 있다.
    names = [row['name'] for row in sa.inspect(op.get_bind()).get_check_constraints('menu_catalog')
             if row['name'] and row['name'].endswith('cuisine_value')]
    if len(names) != 1:
        raise RuntimeError("카탈로그 음식 분류 CHECK를 식별할 수 없습니다.")
    with op.batch_alter_table("menu_catalog") as batch:
        batch.drop_constraint(op.f(names[0]), type_="check")


def _add_check(values):
    sql = "cuisine IN (" + ", ".join(repr(value) for value in values) + ")"
    with op.batch_alter_table("menu_catalog") as batch:
        batch.create_check_constraint(op.f(CONSTRAINT), sql)


def upgrade():
    _drop_check()
    table = sa.table("menu_catalog", sa.column("cuisine", sa.String()))
    # 다른 컬럼이나 식당 원본 분류는 갱신하지 않는다.
    op.execute(table.update().where(table.c.cuisine == "일식").values(cuisine="일식/회"))
    op.execute(table.update().where(table.c.cuisine == "샐러드").values(cuisine="기타"))
    _add_check(NEW_VALUES)


def downgrade():
    # 새 분류 데이터는 과거 스키마에 손실 없이 표현할 수 없으므로 축소를 거부한다.
    connection = op.get_bind()
    table = sa.table("menu_catalog", sa.column("cuisine", sa.String()))
    safe_values = ("한식", "중식", "일식/회", "양식")
    count = connection.scalar(sa.select(sa.func.count()).select_from(table).where(
        table.c.cuisine.not_in(safe_values)
    ))
    if count:
        raise RuntimeError("새 분류 데이터가 있어 무손실 downgrade를 할 수 없습니다. 백업을 사용하세요.")
    _drop_check()
    op.execute(table.update().where(table.c.cuisine == "일식/회").values(cuisine="일식"))
    _add_check(OLD_VALUES)
