import argparse
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import cast

from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.configs.app_configs import SECRET_ENCRYPTION_MODE
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import Base
from onyx.db.models import EncryptedJson
from onyx.db.models import EncryptedJsonUnmasked
from onyx.db.models import EncryptedString
from onyx.db.models import EncryptedStringUnmasked
from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.encryption import encrypt_string_to_bytes
from onyx.utils.encryption import ensure_secret_encryption_ready
from onyx.utils.encryption import is_versioned_encrypted_payload
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SUPPORTED_MODE = "aws_kms_envelope"
_SUPPORTED_ENCRYPTED_TYPES = (
    EncryptedString,
    EncryptedJson,
    EncryptedStringUnmasked,
    EncryptedJsonUnmasked,
)


@dataclass(frozen=True)
class EncryptedColumnTarget:
    table_name: str
    column_name: str
    pk_columns: tuple[str, ...]

    @property
    def id(self) -> str:
        return f"{self.table_name}.{self.column_name}"


@dataclass
class ReencryptStats:
    rows_scanned: int = 0
    rows_already_versioned: int = 0
    rows_legacy: int = 0
    rows_updated: int = 0
    rows_update_conflict: int = 0
    rows_errors: int = 0
    samples: list[str] = field(default_factory=list)


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _build_targets() -> list[EncryptedColumnTarget]:
    targets: list[EncryptedColumnTarget] = []
    for table in Base.metadata.sorted_tables:
        pk_columns = tuple(column.name for column in table.primary_key.columns)
        if not pk_columns:
            continue

        for column in table.columns:
            if isinstance(column.type, _SUPPORTED_ENCRYPTED_TYPES):
                targets.append(
                    EncryptedColumnTarget(
                        table_name=table.name,
                        column_name=column.name,
                        pk_columns=pk_columns,
                    )
                )
    return targets


def _normalize_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError(f"Unsupported secret value type: {type(value)}")


def _validate_target_column_type(
    db_session: Session, target: EncryptedColumnTarget
) -> None:
    validation_query = text(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = :table_name
          AND column_name = :column_name
        """
    )
    row = db_session.execute(
        validation_query,
        {"table_name": target.table_name, "column_name": target.column_name},
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Column {target.id} not found in current schema.")

    data_type = cast(str | None, row[0])
    if data_type != "bytea":
        raise RuntimeError(
            f"Column {target.id} has SQL type '{data_type}', expected 'bytea'. "
            "Run database migrations before running this command."
        )


def _build_select_query(target: EncryptedColumnTarget) -> str:
    pk_cols = ", ".join(_quote_identifier(col) for col in target.pk_columns)
    table_name = _quote_identifier(target.table_name)
    column_name = _quote_identifier(target.column_name)
    return (
        f"SELECT {pk_cols}, CAST({column_name} AS bytea) AS secret_blob "
        f"FROM {table_name} "
        f"WHERE {column_name} IS NOT NULL "
        f"ORDER BY {pk_cols} "
        "LIMIT :limit OFFSET :offset"
    )


def _build_update_query(target: EncryptedColumnTarget) -> str:
    table_name = _quote_identifier(target.table_name)
    column_name = _quote_identifier(target.column_name)
    where_clause_parts = [f'{_quote_identifier(col)} = :pk_{col}' for col in target.pk_columns]
    where_clause_parts.append(f"{column_name} = :old_blob")
    where_clause = " AND ".join(where_clause_parts)

    return (
        f"UPDATE {table_name} "
        f"SET {column_name} = :new_blob "
        f"WHERE {where_clause}"
    )


def _process_target(
    db_session: Session,
    target: EncryptedColumnTarget,
    *,
    batch_size: int,
    apply_changes: bool,
) -> ReencryptStats:
    stats = ReencryptStats()
    select_query = text(_build_select_query(target))
    update_query = text(_build_update_query(target))

    offset = 0
    while True:
        rows = db_session.execute(
            select_query,
            {"limit": batch_size, "offset": offset},
        ).mappings().all()
        if not rows:
            break

        for row in rows:
            stats.rows_scanned += 1
            try:
                raw_blob = _normalize_bytes(row["secret_blob"])
            except Exception:
                stats.rows_errors += 1
                continue

            if is_versioned_encrypted_payload(raw_blob):
                stats.rows_already_versioned += 1
                continue

            try:
                decrypted = decrypt_bytes_to_string(raw_blob)
                reencrypted = encrypt_string_to_bytes(decrypted)
            except Exception:
                stats.rows_errors += 1
                if len(stats.samples) < 5:
                    pk_sample = ",".join(
                        f"{pk}={row[pk]}" for pk in target.pk_columns
                    )
                    stats.samples.append(pk_sample)
                continue

            stats.rows_legacy += 1
            if not apply_changes:
                continue

            if reencrypted == raw_blob:
                continue

            update_params: dict[str, Any] = {
                "old_blob": raw_blob,
                "new_blob": reencrypted,
            }
            for pk in target.pk_columns:
                update_params[f"pk_{pk}"] = row[pk]

            update_result = db_session.execute(update_query, update_params)
            if update_result.rowcount == 1:
                stats.rows_updated += 1
            else:
                stats.rows_update_conflict += 1

        if apply_changes:
            db_session.commit()
        offset += len(rows)

    return stats


def _run_reencryption(
    *,
    apply_changes: bool,
    batch_size: int,
    selected_targets: set[str],
) -> int:
    targets = _build_targets()
    if selected_targets:
        targets = [target for target in targets if target.id in selected_targets]
    if not targets:
        logger.warning("No encrypted targets found for re-encryption.")
        return 0

    logger.info("Starting secret re-encryption scan. apply=%s", apply_changes)
    total_errors = 0

    with get_session_with_current_tenant() as db_session:
        for target in targets:
            _validate_target_column_type(db_session, target)
            stats = _process_target(
                db_session,
                target,
                batch_size=batch_size,
                apply_changes=apply_changes,
            )
            total_errors += stats.rows_errors

            logger.info(
                "[%s] scanned=%s already_versioned=%s legacy=%s updated=%s conflicts=%s errors=%s",
                target.id,
                stats.rows_scanned,
                stats.rows_already_versioned,
                stats.rows_legacy,
                stats.rows_updated,
                stats.rows_update_conflict,
                stats.rows_errors,
            )
            if stats.samples:
                logger.warning("[%s] sample error row ids: %s", target.id, stats.samples)

    return total_errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Re-encrypt legacy plaintext secret blobs into ONYXENC2 format for all "
            "encrypted DB columns."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates. If omitted, runs in dry-run mode.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="Rows per batch for each table/column.",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help=(
            "Optional target in table.column format. Can be provided multiple times. "
            "Example: --target credential.credential_json"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size must be a positive integer.")

    if SECRET_ENCRYPTION_MODE != _SUPPORTED_MODE:
        raise RuntimeError(
            "Secret re-encryption requires SECRET_ENCRYPTION_MODE=aws_kms_envelope."
        )

    ensure_secret_encryption_ready()

    SqlEngine.set_app_name("secret_reencrypt")
    SqlEngine.init_engine(pool_size=5, max_overflow=5)

    try:
        target_set = set(cast(list[str], args.target))
        errors = _run_reencryption(
            apply_changes=bool(args.apply),
            batch_size=cast(int, args.batch_size),
            selected_targets=target_set,
        )
    finally:
        SqlEngine.reset_engine()

    if args.apply:
        logger.info("Re-encryption apply run completed.")
    else:
        logger.info("Dry-run completed. Re-run with --apply to persist changes.")

    if errors > 0:
        raise RuntimeError(
            f"Re-encryption finished with {errors} row-level errors. Check logs."
        )


if __name__ == "__main__":
    main()
