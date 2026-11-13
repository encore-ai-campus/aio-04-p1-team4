"""PostgreSQL DB-first schema transition; refuses populated application tables."""
from alembic import op
import sqlalchemy as sa
revision = "0003_db_first_schema"
down_revision = "0002_catalog_food_types"
branch_labels = None
depends_on = None
# Frozen DDL, independent of future ORM changes.
DDL = [
  "\nCREATE TABLE menu_catalog (\n\tid VARCHAR(40) NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tnormalized_name VARCHAR(100) NOT NULL, \n\tcuisine VARCHAR(20) NOT NULL, \n\tsearch_keyword VARCHAR(100) NOT NULL, \n\tdescription VARCHAR(500) NOT NULL, \n\tprice_hint INTEGER, \n\tactive BOOLEAN DEFAULT true NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_menu_catalog PRIMARY KEY (id), \n\tCONSTRAINT ck_menu_catalog_price_hint_nonnegative CHECK (price_hint IS NULL OR price_hint >= 0), \n\tCONSTRAINT ck_menu_catalog_cuisine_value CHECK (cuisine IN ('한식', '중식', '일식/회', '양식', '분식', '패스트푸드', '치킨', '도시락/구내식당', '뷔페식', '냉면', '고기', '카페/빵', '술집', '기타')), \n\tCONSTRAINT uq_menu_catalog_name UNIQUE (name), \n\tCONSTRAINT uq_menu_catalog_normalized_name UNIQUE (normalized_name)\n)\n\n",
  "CREATE INDEX ix_menu_catalog_filter ON menu_catalog (active, cuisine, price_hint)",
  "\nCREATE TABLE restaurant (\n\tid UUID NOT NULL, \n\tkakao_id VARCHAR(40), \n\tnaver_id VARCHAR(40), \n\toperating_status VARCHAR(20) DEFAULT 'unknown' NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tcategory_name VARCHAR(300), \n\tcuisine VARCHAR(30), \n\tlatitude FLOAT NOT NULL, \n\tlongitude FLOAT NOT NULL, \n\taddress VARCHAR(500) NOT NULL, \n\tplace_url VARCHAR(1000), \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_restaurant PRIMARY KEY (id), \n\tCONSTRAINT ck_restaurant_latitude_range CHECK (latitude BETWEEN -90 AND 90), \n\tCONSTRAINT ck_restaurant_longitude_range CHECK (longitude BETWEEN -180 AND 180), \n\tCONSTRAINT ck_restaurant_operating_status_value CHECK (operating_status IN ('operating', 'closed', 'unknown')), \n\tCONSTRAINT uq_restaurant_kakao_id UNIQUE (kakao_id)\n)\n\n",
  "CREATE INDEX ix_restaurant_cuisine ON restaurant (cuisine)",
  "CREATE INDEX ix_restaurant_location ON restaurant (latitude, longitude)",
  "\nCREATE TABLE business_hours (\n\tid SERIAL NOT NULL, \n\trestaurant_id UUID NOT NULL, \n\tday_of_week INTEGER NOT NULL, \n\tholiday BOOLEAN, \n\tstart_time TIME WITHOUT TIME ZONE, \n\tend_time TIME WITHOUT TIME ZONE, \n\tends_next_day BOOLEAN DEFAULT false NOT NULL, \n\tlast_order_time TIME WITHOUT TIME ZONE, \n\tsequence INTEGER DEFAULT '0' NOT NULL, \n\tsource_url VARCHAR(1000), \n\tverified_at TIMESTAMP WITH TIME ZONE, \n\tCONSTRAINT pk_business_hours PRIMARY KEY (id), \n\tCONSTRAINT restaurant_day_sequence UNIQUE (restaurant_id, day_of_week, sequence), \n\tCONSTRAINT ck_business_hours_day_range CHECK (day_of_week BETWEEN 0 AND 6), \n\tCONSTRAINT ck_business_hours_sequence_nonnegative CHECK (sequence >= 0), \n\tCONSTRAINT ck_business_hours_time_pair CHECK ((start_time IS NULL AND end_time IS NULL) OR (start_time IS NOT NULL AND end_time IS NOT NULL)), \n\tCONSTRAINT ck_business_hours_holiday_without_hours CHECK (holiday IS NOT TRUE OR (start_time IS NULL AND end_time IS NULL)), \n\tCONSTRAINT fk_business_hours_restaurant_id_restaurant FOREIGN KEY(restaurant_id) REFERENCES restaurant (id) ON DELETE CASCADE\n)\n\n",
  "CREATE INDEX ix_business_hours_lookup ON business_hours (restaurant_id, day_of_week)",
  "\nCREATE TABLE menu (\n\tid SERIAL NOT NULL, \n\trestaurant_id UUID NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tnormalized_name VARCHAR(200) NOT NULL, \n\tprice INTEGER, \n\tprice_status VARCHAR(20) DEFAULT 'missing' NOT NULL, \n\tmenu_catalog_id VARCHAR(40), \n\tavailability_status VARCHAR(20) DEFAULT 'unknown' NOT NULL, \n\tsource_provider VARCHAR(40), \n\tsource_url VARCHAR(1000), \n\tverified_at TIMESTAMP WITH TIME ZONE, \n\tCONSTRAINT pk_menu PRIMARY KEY (id), \n\tCONSTRAINT restaurant_name UNIQUE (restaurant_id, normalized_name), \n\tCONSTRAINT ck_menu_price_nonnegative CHECK (price IS NULL OR price >= 0), \n\tCONSTRAINT ck_menu_price_status_value CHECK (price_status IN ('known', 'missing', 'variable')), \n\tCONSTRAINT ck_menu_availability_status_value CHECK (availability_status IN ('available', 'sold_out', 'unknown')), \n\tCONSTRAINT ck_menu_price_status_consistent CHECK ((price_status = 'known' AND price > 0 AND price IS NOT NULL) OR (price_status IN ('missing', 'variable') AND price IS NULL)), \n\tCONSTRAINT fk_menu_restaurant_id_restaurant FOREIGN KEY(restaurant_id) REFERENCES restaurant (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_menu_menu_catalog_id_menu_catalog FOREIGN KEY(menu_catalog_id) REFERENCES menu_catalog (id) ON DELETE SET NULL\n)\n\n",
  "CREATE INDEX ix_menu_catalog_price ON menu (menu_catalog_id, price)",
  "CREATE INDEX ix_menu_lookup ON menu (normalized_name, price)",
  "\nCREATE TABLE menu_alias (\n\tid SERIAL NOT NULL, \n\tmenu_catalog_id VARCHAR(40) NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tnormalized_name VARCHAR(100) NOT NULL, \n\tCONSTRAINT pk_menu_alias PRIMARY KEY (id), \n\tCONSTRAINT normalized_name UNIQUE (normalized_name), \n\tCONSTRAINT fk_menu_alias_menu_catalog_id_menu_catalog FOREIGN KEY(menu_catalog_id) REFERENCES menu_catalog (id) ON DELETE CASCADE\n)\n\n",
  "CREATE INDEX ix_menu_alias_catalog ON menu_alias (menu_catalog_id)",
  "\nCREATE TABLE place_detail_status (\n\trestaurant_id UUID NOT NULL, \n\tmenu_status VARCHAR(20) DEFAULT 'pending' NOT NULL, \n\thours_status VARCHAR(20) DEFAULT 'pending' NOT NULL, \n\tlast_attempt_at TIMESTAMP WITH TIME ZONE, \n\tlast_success_at TIMESTAMP WITH TIME ZONE, \n\terror_code VARCHAR(50), \n\tmenu_last_success_at TIMESTAMP WITH TIME ZONE, \n\thours_last_success_at TIMESTAMP WITH TIME ZONE, \n\tCONSTRAINT pk_place_detail_status PRIMARY KEY (restaurant_id), \n\tCONSTRAINT ck_place_detail_status_menu_status_value CHECK (menu_status IN ('pending', 'success', 'missing', 'fetch_failed', 'parse_failed')), \n\tCONSTRAINT ck_place_detail_status_hours_status_value CHECK (hours_status IN ('pending', 'success', 'missing', 'fetch_failed', 'parse_failed')), \n\tCONSTRAINT fk_place_detail_status_restaurant_id_restaurant FOREIGN KEY(restaurant_id) REFERENCES restaurant (id) ON DELETE CASCADE\n)\n\n",
  "\nCREATE TABLE restaurant_match (\n\tid BIGSERIAL NOT NULL, \n\trestaurant_id UUID, \n\tsource_name VARCHAR(200) NOT NULL, \n\tsource_address VARCHAR(500) NOT NULL, \n\tcandidate_kakao_id VARCHAR(40), \n\tmatch_status VARCHAR(20) DEFAULT 'review' NOT NULL, \n\treason VARCHAR(500), \n\treviewed_at TIMESTAMP WITH TIME ZONE, \n\tCONSTRAINT pk_restaurant_match PRIMARY KEY (id), \n\tCONSTRAINT ck_restaurant_match_match_status_value CHECK (match_status IN ('matched', 'review', 'not_found')), \n\tCONSTRAINT fk_restaurant_match_restaurant_id_restaurant FOREIGN KEY(restaurant_id) REFERENCES restaurant (id) ON DELETE SET NULL\n)\n\n",
  "CREATE INDEX ix_restaurant_match_status ON restaurant_match (match_status)"
]
TABLES = ("menu_catalog", "menu_alias", "restaurant", "menu", "business_hours", "place_detail_status", "restaurant_match")

def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("0003 requires PostgreSQL. SQLite tests use create_all.")
    present = set(sa.inspect(connection).get_table_names())
    for table in TABLES:
        if table in present and connection.scalar(sa.text('SELECT count(*) FROM "' + table + '"')):
            raise RuntimeError("Populated schema requires an explicit UUID data migration.")
    for table in ("restaurant_match", "menu_alias", "menu", "business_hours", "place_detail_status", "restaurant", "menu_catalog"):
        if table in present:
            op.execute(sa.text('DROP TABLE "' + table + '"'))
    for statement in DDL:
        op.execute(sa.text(statement))
    for table in TABLES:
        op.execute(sa.text('ALTER TABLE "' + table + '" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text('REVOKE ALL ON TABLE "' + table + '" FROM anon, authenticated'))

def downgrade():
    raise RuntimeError("UUID transition requires an explicit reverse migration.")
