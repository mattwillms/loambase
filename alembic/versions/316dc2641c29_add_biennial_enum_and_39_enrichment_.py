"""add biennial enum and 39 enrichment columns to plants

Revision ID: 316dc2641c29
Revises: 9e3909e30d4c
Create Date: 2026-02-28 14:58:38.961810

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '316dc2641c29'
down_revision: Union[str, None] = '9e3909e30d4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'biennial' to plant_type_enum (Alembic doesn't detect enum additions)
    op.execute("ALTER TYPE plant_type_enum ADD VALUE IF NOT EXISTS 'biennial'")

    # 39 new columns on plants
    op.add_column('plants', sa.Column('height_inches', sa.Float(), nullable=True))
    op.add_column('plants', sa.Column('width_inches', sa.Float(), nullable=True))
    op.add_column('plants', sa.Column('soil_type', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('soil_ph_min', sa.Float(), nullable=True))
    op.add_column('plants', sa.Column('soil_ph_max', sa.Float(), nullable=True))
    op.add_column('plants', sa.Column('growth_rate', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('life_cycle', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('drought_resistant', sa.Boolean(), nullable=True))
    op.add_column('plants', sa.Column('days_to_harvest', sa.Integer(), nullable=True))
    op.add_column('plants', sa.Column('propagation_method', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('germination_days_min', sa.Integer(), nullable=True))
    op.add_column('plants', sa.Column('germination_days_max', sa.Integer(), nullable=True))
    op.add_column('plants', sa.Column('germination_temp_min_f', sa.Float(), nullable=True))
    op.add_column('plants', sa.Column('germination_temp_max_f', sa.Float(), nullable=True))
    op.add_column('plants', sa.Column('sow_outdoors', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('sow_indoors', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('start_indoors_weeks', sa.Integer(), nullable=True))
    op.add_column('plants', sa.Column('start_outdoors_weeks', sa.Integer(), nullable=True))
    op.add_column('plants', sa.Column('plant_transplant', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('plant_cuttings', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('plant_division', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('native_to', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('habitat', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('family', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('genus', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('edible', sa.Boolean(), nullable=True))
    op.add_column('plants', sa.Column('edible_parts', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('edible_uses', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('medicinal', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('medicinal_parts', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('utility', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('warning', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('pollination', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('nitrogen_fixing', sa.Boolean(), nullable=True))
    op.add_column('plants', sa.Column('root_type', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('root_depth', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('wikipedia_url', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('pfaf_url', sa.Text(), nullable=True))
    op.add_column('plants', sa.Column('powo_url', sa.Text(), nullable=True))

    # Seed enrichment rules (INSERT ... ON CONFLICT for idempotency)
    op.execute("""
        INSERT INTO enrichment_rules (field_name, strategy, source_priority, updated_at)
        VALUES
            ('common_name', 'priority', '{perenual,permapeople}', NOW()),
            ('scientific_name', 'priority', '{perenual,permapeople}', NOW()),
            ('image_url', 'priority', '{perenual,permapeople}', NOW()),
            ('description', 'longest', '{permapeople,perenual}', NOW()),
            ('plant_type', 'priority', '{permapeople}', NOW()),
            ('water_needs', 'priority', '{permapeople}', NOW()),
            ('sun_requirement', 'priority', '{permapeople}', NOW()),
            ('hardiness_zones', 'union', '{permapeople}', NOW()),
            ('days_to_maturity', 'priority', '{permapeople}', NOW()),
            ('spacing_inches', 'priority', '{permapeople}', NOW()),
            ('planting_depth_inches', 'priority', '{permapeople}', NOW()),
            ('common_pests', 'union', '{permapeople}', NOW()),
            ('common_diseases', 'union', '{permapeople}', NOW()),
            ('fertilizer_needs', 'priority', '{permapeople}', NOW()),
            ('bloom_season', 'priority', '{permapeople}', NOW()),
            ('harvest_window', 'priority', '{permapeople}', NOW()),
            ('companion_plants', 'union', '{permapeople}', NOW()),
            ('antagonist_plants', 'union', '{permapeople}', NOW()),
            ('height_inches', 'priority', '{permapeople}', NOW()),
            ('width_inches', 'priority', '{permapeople}', NOW()),
            ('soil_type', 'priority', '{permapeople}', NOW()),
            ('soil_ph_min', 'priority', '{permapeople}', NOW()),
            ('soil_ph_max', 'priority', '{permapeople}', NOW()),
            ('growth_rate', 'priority', '{permapeople}', NOW()),
            ('life_cycle', 'priority', '{permapeople}', NOW()),
            ('drought_resistant', 'priority', '{permapeople}', NOW()),
            ('days_to_harvest', 'priority', '{permapeople}', NOW()),
            ('propagation_method', 'priority', '{permapeople}', NOW()),
            ('germination_days_min', 'priority', '{permapeople}', NOW()),
            ('germination_days_max', 'priority', '{permapeople}', NOW()),
            ('germination_temp_min_f', 'priority', '{permapeople}', NOW()),
            ('germination_temp_max_f', 'priority', '{permapeople}', NOW()),
            ('sow_outdoors', 'priority', '{permapeople}', NOW()),
            ('sow_indoors', 'priority', '{permapeople}', NOW()),
            ('start_indoors_weeks', 'priority', '{permapeople}', NOW()),
            ('start_outdoors_weeks', 'priority', '{permapeople}', NOW()),
            ('plant_transplant', 'priority', '{permapeople}', NOW()),
            ('plant_cuttings', 'priority', '{permapeople}', NOW()),
            ('plant_division', 'priority', '{permapeople}', NOW()),
            ('native_to', 'priority', '{permapeople}', NOW()),
            ('habitat', 'priority', '{permapeople}', NOW()),
            ('family', 'priority', '{permapeople}', NOW()),
            ('genus', 'priority', '{permapeople}', NOW()),
            ('edible', 'priority', '{permapeople}', NOW()),
            ('edible_parts', 'priority', '{permapeople}', NOW()),
            ('edible_uses', 'priority', '{permapeople}', NOW()),
            ('medicinal', 'longest', '{permapeople}', NOW()),
            ('medicinal_parts', 'priority', '{permapeople}', NOW()),
            ('utility', 'priority', '{permapeople}', NOW()),
            ('warning', 'priority', '{permapeople}', NOW()),
            ('pollination', 'priority', '{permapeople}', NOW()),
            ('nitrogen_fixing', 'priority', '{permapeople}', NOW()),
            ('root_type', 'priority', '{permapeople}', NOW()),
            ('root_depth', 'priority', '{permapeople}', NOW()),
            ('wikipedia_url', 'priority', '{permapeople}', NOW()),
            ('pfaf_url', 'priority', '{permapeople}', NOW()),
            ('powo_url', 'priority', '{permapeople}', NOW())
        ON CONFLICT (field_name) DO UPDATE SET
            strategy = EXCLUDED.strategy,
            source_priority = EXCLUDED.source_priority,
            updated_at = NOW()
    """)


def downgrade() -> None:
    op.drop_column('plants', 'powo_url')
    op.drop_column('plants', 'pfaf_url')
    op.drop_column('plants', 'wikipedia_url')
    op.drop_column('plants', 'root_depth')
    op.drop_column('plants', 'root_type')
    op.drop_column('plants', 'nitrogen_fixing')
    op.drop_column('plants', 'pollination')
    op.drop_column('plants', 'warning')
    op.drop_column('plants', 'utility')
    op.drop_column('plants', 'medicinal_parts')
    op.drop_column('plants', 'medicinal')
    op.drop_column('plants', 'edible_uses')
    op.drop_column('plants', 'edible_parts')
    op.drop_column('plants', 'edible')
    op.drop_column('plants', 'genus')
    op.drop_column('plants', 'family')
    op.drop_column('plants', 'habitat')
    op.drop_column('plants', 'native_to')
    op.drop_column('plants', 'plant_division')
    op.drop_column('plants', 'plant_cuttings')
    op.drop_column('plants', 'plant_transplant')
    op.drop_column('plants', 'start_outdoors_weeks')
    op.drop_column('plants', 'start_indoors_weeks')
    op.drop_column('plants', 'sow_indoors')
    op.drop_column('plants', 'sow_outdoors')
    op.drop_column('plants', 'germination_temp_max_f')
    op.drop_column('plants', 'germination_temp_min_f')
    op.drop_column('plants', 'germination_days_max')
    op.drop_column('plants', 'germination_days_min')
    op.drop_column('plants', 'propagation_method')
    op.drop_column('plants', 'days_to_harvest')
    op.drop_column('plants', 'drought_resistant')
    op.drop_column('plants', 'life_cycle')
    op.drop_column('plants', 'growth_rate')
    op.drop_column('plants', 'soil_ph_max')
    op.drop_column('plants', 'soil_ph_min')
    op.drop_column('plants', 'soil_type')
    op.drop_column('plants', 'width_inches')
    op.drop_column('plants', 'height_inches')

    # Remove seeded enrichment rules for new fields
    op.execute("""
        DELETE FROM enrichment_rules WHERE field_name IN (
            'height_inches', 'width_inches', 'soil_type', 'soil_ph_min', 'soil_ph_max',
            'growth_rate', 'life_cycle', 'drought_resistant', 'days_to_harvest',
            'propagation_method', 'germination_days_min', 'germination_days_max',
            'germination_temp_min_f', 'germination_temp_max_f', 'sow_outdoors', 'sow_indoors',
            'start_indoors_weeks', 'start_outdoors_weeks', 'plant_transplant', 'plant_cuttings',
            'plant_division', 'native_to', 'habitat', 'family', 'genus', 'edible', 'edible_parts',
            'edible_uses', 'medicinal', 'medicinal_parts', 'utility', 'warning', 'pollination',
            'nitrogen_fixing', 'root_type', 'root_depth', 'wikipedia_url', 'pfaf_url', 'powo_url'
        )
    """)
