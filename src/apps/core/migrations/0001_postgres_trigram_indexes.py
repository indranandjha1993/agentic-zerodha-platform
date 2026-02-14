from django.db import migrations


def create_trigram_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    statements = (
        "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
        (
            "CREATE INDEX IF NOT EXISTS agents_agent_name_trgm_idx "
            "ON agents_agent USING GIN (name gin_trgm_ops);"
        ),
        (
            "CREATE INDEX IF NOT EXISTS agents_agent_slug_trgm_idx "
            "ON agents_agent USING GIN (slug gin_trgm_ops);"
        ),
        (
            "CREATE INDEX IF NOT EXISTS execution_tradeintent_symbol_trgm_idx "
            "ON execution_tradeintent USING GIN (symbol gin_trgm_ops);"
        ),
        (
            "CREATE INDEX IF NOT EXISTS execution_tradeintent_broker_order_id_trgm_idx "
            "ON execution_tradeintent USING GIN (broker_order_id gin_trgm_ops);"
        ),
        (
            "CREATE INDEX IF NOT EXISTS market_data_instrument_tradingsymbol_trgm_idx "
            "ON market_data_instrument USING GIN (tradingsymbol gin_trgm_ops);"
        ),
        (
            "CREATE INDEX IF NOT EXISTS market_data_instrument_name_trgm_idx "
            "ON market_data_instrument USING GIN (name gin_trgm_ops);"
        ),
        (
            "CREATE INDEX IF NOT EXISTS approvals_approvalrequest_notes_trgm_idx "
            "ON approvals_approvalrequest USING GIN (notes gin_trgm_ops);"
        ),
        (
            "CREATE INDEX IF NOT EXISTS approvals_approvalrequest_decision_reason_trgm_idx "
            "ON approvals_approvalrequest USING GIN (decision_reason gin_trgm_ops);"
        ),
        (
            "CREATE INDEX IF NOT EXISTS audit_auditevent_message_trgm_idx "
            "ON audit_auditevent USING GIN (message gin_trgm_ops);"
        ),
    )

    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def drop_trigram_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    statements = (
        "DROP INDEX IF EXISTS audit_auditevent_message_trgm_idx;",
        "DROP INDEX IF EXISTS approvals_approvalrequest_decision_reason_trgm_idx;",
        "DROP INDEX IF EXISTS approvals_approvalrequest_notes_trgm_idx;",
        "DROP INDEX IF EXISTS market_data_instrument_name_trgm_idx;",
        "DROP INDEX IF EXISTS market_data_instrument_tradingsymbol_trgm_idx;",
        "DROP INDEX IF EXISTS execution_tradeintent_broker_order_id_trgm_idx;",
        "DROP INDEX IF EXISTS execution_tradeintent_symbol_trgm_idx;",
        "DROP INDEX IF EXISTS agents_agent_slug_trgm_idx;",
        "DROP INDEX IF EXISTS agents_agent_name_trgm_idx;",
    )

    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0006_agent_agents_agen_status_65a1e3_idx_and_more"),
        ("approvals", "0005_approvaldecision_approvals_a_approva_63e748_idx_and_more"),
        ("audit", "0002_auditevent_audit_audit_level_e6924b_idx_and_more"),
        ("execution", "0002_tradeintent_execution_t_status_3a852f_idx_and_more"),
        ("market_data", "0002_instrument_market_data_exchang_1b1149_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(create_trigram_indexes, drop_trigram_indexes),
    ]
