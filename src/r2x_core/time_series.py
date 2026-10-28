"""Time series utils."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from sqlite3 import Connection
from typing import TYPE_CHECKING, Any, cast

from infrasys import SingleTimeSeries
from loguru import logger

if TYPE_CHECKING:
    from infrasys import Component

    from .plugin_context import PluginContext
    from .system import System


@dataclass(frozen=True, slots=True)
class TimeSeriesTransferResult:
    """Transfer status of time series metadata."""

    transferred: int
    updated: int
    children_remapped: int


UNIQUE_TS_COLUMNS: tuple[str, ...] = (
    "owner_uuid",
    "owner_type",
    "owner_category",
    "time_series_uuid",
    "name",
    "time_series_type",
    "features",
)


def main_database_path(conn: Connection) -> str | None:
    """Return filesystem path for the main SQLite database, if present."""
    for _, name, path in conn.execute("PRAGMA database_list").fetchall():
        if name == "main" and path:
            return str(path)
    return None


def time_series_columns(conn: Connection) -> list[str]:
    """Return ordered column names excluding the autoincrement primary key."""
    rows = conn.execute("PRAGMA table_info(time_series_associations)").fetchall()
    return [row[1] for row in rows if row[1] != "id"]


def deduplicate_time_series_associations(conn: Connection, unique_cols: tuple[str, ...]) -> int:
    """Remove duplicate association rows using the unique key columns."""
    group_by = ",".join(unique_cols)
    before = conn.total_changes
    conn.execute(
        f"""
        DELETE FROM time_series_associations
        WHERE rowid NOT IN (
            SELECT MIN(rowid)
            FROM time_series_associations
            GROUP BY {group_by}
        )
        """
    )
    return conn.total_changes - before


def count_time_series_associations(conn: Connection) -> int:
    """Return total rows in time series associations."""
    count = conn.execute("SELECT COUNT(*) FROM time_series_associations").fetchone()[0]
    return int(count)


def create_target_and_child_tables(
    tgt_metadata: Connection,
    *,
    source_system: System,
    target_system: System,
) -> int:
    """Stage target components and their source associations without bulk SQL parameters."""
    tgt_metadata.execute("DROP TABLE IF EXISTS target_components")
    tgt_metadata.execute("CREATE TEMP TABLE target_components (uuid TEXT PRIMARY KEY, type TEXT)")
    tgt_metadata.executemany(
        "INSERT INTO target_components VALUES (?, ?)",
        (
            (str(component.uuid), type(component).__name__)
            for component in target_system.iter_all_components()
        ),
    )

    child_remapping: list[tuple[str, str, str]] = [
        (str(associated.uuid), str(component.uuid), type(component).__name__)
        for component in target_system.iter_all_components()
        for associated in source_system.list_parent_components(component)
    ]

    tgt_metadata.execute("DROP TABLE IF EXISTS child_mapping")
    tgt_metadata.execute(
        "CREATE TEMP TABLE child_mapping (child_uuid TEXT, parent_uuid TEXT, parent_type TEXT)"
    )
    if child_remapping:
        tgt_metadata.executemany("INSERT INTO child_mapping VALUES (?, ?, ?)", child_remapping)

    return len(child_remapping)


def transfer_associations(
    src_metadata: Connection,
    tgt_metadata: Connection,
    target_uuids: set[str],
    columns: list[str],
) -> None:
    """Transfer time series associations from source to target."""
    column_csv = ",".join(columns)
    placeholders = ",".join(["?"] * len(columns))
    src_db_path = main_database_path(src_metadata)

    if src_db_path:
        tgt_metadata.execute("ATTACH DATABASE ? AS src_ts", (src_db_path,))
        try:
            tgt_metadata.execute(
                f"""
                INSERT OR IGNORE INTO time_series_associations ({column_csv})
                SELECT {column_csv}
                FROM src_ts.time_series_associations s
                WHERE s.owner_uuid IN (SELECT uuid FROM target_components)
                AND s.time_series_type != 'Deterministic'
                AND NOT EXISTS (
                    SELECT 1 FROM time_series_associations t
                    WHERE t.owner_uuid = s.owner_uuid
                    AND t.owner_type = s.owner_type
                    AND t.owner_category = s.owner_category
                    AND t.time_series_uuid = s.time_series_uuid
                    AND t.name = s.name
                    AND t.time_series_type = s.time_series_type
                    AND t.features = s.features
                )
                """
            )
        finally:
            try:
                tgt_metadata.execute("DETACH DATABASE src_ts")
            except Exception as exc:
                logger.warning("Could not detach src_ts during time series transfer: {}", exc)
    else:
        src_rows = src_metadata.execute(f"SELECT {column_csv} FROM time_series_associations").fetchall()
        ts_type_idx = columns.index("time_series_type")
        filtered_rows = [
            row
            for row in src_rows
            if row[columns.index("owner_uuid")] in target_uuids
            and row[ts_type_idx] != "DeterministicSingleTimeSeries"
        ]
        if filtered_rows:
            tgt_metadata.executemany(
                f"INSERT OR IGNORE INTO time_series_associations ({column_csv}) VALUES ({placeholders})",
                filtered_rows,
            )


def remove_duplicate_rows_before_remap(tgt_metadata: Connection) -> None:
    """Remove rows that would become duplicates after remapping."""
    tgt_metadata.execute("""
        WITH owner_resolution AS (
            SELECT
                ts.rowid as rowid,
                ts.owner_uuid as original_uuid,
                COALESCE(tc_direct.uuid, cm.parent_uuid) as resolved_uuid,
                ts.time_series_type,
                ts.name,
                ts.resolution,
                ts.features,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        COALESCE(tc_direct.uuid, cm.parent_uuid),
                        ts.time_series_type,
                        ts.name,
                        ts.resolution,
                        ts.features
                    ORDER BY ts.rowid
                ) as rn
            FROM time_series_associations ts
            LEFT JOIN target_components tc_direct ON ts.owner_uuid = tc_direct.uuid
            LEFT JOIN child_mapping cm ON ts.owner_uuid = cm.child_uuid
            WHERE tc_direct.uuid IS NOT NULL OR cm.parent_uuid IS NOT NULL
        )
        DELETE FROM time_series_associations
        WHERE rowid IN (
            SELECT rowid FROM owner_resolution WHERE rn > 1
        )
    """)


def remap_child_associations(tgt_metadata: Connection) -> int:
    """Remap child associations with new owner UUIDs and types.

    Returns
    -------
        Number of associations updated.
    """
    result = tgt_metadata.execute("""
        WITH owner_resolution AS (
            SELECT
                ts.owner_uuid as original_uuid,
                COALESCE(tc_direct.uuid, cm.parent_uuid) as resolved_uuid,
                COALESCE(tc_direct.type, cm.parent_type) as resolved_type
            FROM time_series_associations ts
            LEFT JOIN target_components tc_direct ON ts.owner_uuid = tc_direct.uuid
            LEFT JOIN child_mapping cm ON ts.owner_uuid = cm.child_uuid
            WHERE tc_direct.uuid IS NOT NULL OR cm.parent_uuid IS NOT NULL
        )
        UPDATE time_series_associations
        SET
            owner_uuid = (SELECT resolved_uuid FROM owner_resolution WHERE original_uuid = time_series_associations.owner_uuid),
            owner_type = (SELECT resolved_type FROM owner_resolution WHERE original_uuid = time_series_associations.owner_uuid)
        WHERE owner_uuid IN (SELECT original_uuid FROM owner_resolution)
    """)
    return max(result.rowcount if result.rowcount is not None else 0, 0)


def finalize_transfer(tgt_metadata: Connection) -> None:
    """Create unique index and prepare for metadata reload."""
    tgt_metadata.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ts_owner_series_unique
        ON time_series_associations (
            owner_uuid,
            owner_type,
            owner_category,
            time_series_uuid,
            name,
            time_series_type,
            features
        )
        """
    )


def replace_single_time_series(
    system: System,
    owner: Component,
    time_series: SingleTimeSeries,
    **features: Any,
) -> None:
    """Replace exactly one time series association without removing shared data.

    The metadata change is rolled back if storing the replacement fails. This
    preserves the existing association and any backing data shared with another
    system.
    """
    metadata = system.list_time_series_metadata(
        owner,
        name=time_series.name,
        time_series_type=SingleTimeSeries,
        **features,
    )
    if len(metadata) != 1:
        msg = (
            f"Expected one SingleTimeSeries named '{time_series.name}' on {owner.name}, found {len(metadata)}"
        )
        raise ValueError(msg)

    metadata_store = system.time_series.metadata_store
    error: Exception | None = None
    try:
        with system.open_time_series_store(mode="a") as store:
            try:
                metadata_store.remove(
                    owner,
                    name=time_series.name,
                    time_series_type=SingleTimeSeries.__name__,
                    connection=store.metadata_conn,
                    **features,
                )
                system.add_time_series(time_series, owner, **features)
            except Exception as exc:
                store.metadata_conn.rollback()
                error = exc
    except Exception:
        metadata_store._cache_metadata.clear()
        metadata_store._load_metadata_into_memory()
        raise

    if error is not None:
        metadata_store._cache_metadata.clear()
        metadata_store._load_metadata_into_memory()
        raise error.with_traceback(error.__traceback__)


def transfer_time_series_metadata(context: PluginContext) -> TimeSeriesTransferResult:
    """Transfer time series metadata for target system.

    Parameters
    ----------
    context : PluginContext
        Plugin context containing source and target systems.

    Notes
    -----
    Preserved components (those carried over from source when
    ``preserve_source=True``) live in the target's component map under their
    original source UUIDs, so their time series transfer through the normal
    UUID-matched path with no special handling.
    """
    if context.source_system is None or context.target_system is None:
        msg = "source_system and target_system must be set in context"
        raise ValueError(msg)

    source_system = context.source_system
    target_system = context.target_system
    target_uuids = {str(component.uuid) for component in target_system.iter_all_components()}

    logger.info(f"Transferring time series metadata for {len(target_uuids)} components")

    with (
        source_system.open_time_series_store(mode="r") as src_store,
        target_system.open_time_series_store(mode="a") as tgt_store,
    ):
        src_metadata = src_store.metadata_conn
        tgt_metadata = tgt_store.metadata_conn
        children_remapped = create_target_and_child_tables(
            tgt_metadata, source_system=source_system, target_system=target_system
        )

        # Deduplicate before transfer
        removed_duplicates = deduplicate_time_series_associations(tgt_metadata, UNIQUE_TS_COLUMNS)
        if removed_duplicates:
            logger.warning("Removed {} duplicate time series association rows", removed_duplicates)

        initial_count = count_time_series_associations(tgt_metadata)

        # Transfer associations
        columns = time_series_columns(tgt_metadata)
        transfer_associations(src_metadata, tgt_metadata, target_uuids, columns)

        # Remove potential duplicates before remapping
        remove_duplicate_rows_before_remap(tgt_metadata)

        # Remap child associations
        updated = remap_child_associations(tgt_metadata)

        # Deduplicate after remapping
        removed_after_update = deduplicate_time_series_associations(tgt_metadata, UNIQUE_TS_COLUMNS)
        if removed_after_update:
            logger.warning(
                "Removed {} duplicate time series association rows after remapping", removed_after_update
            )

        # Create index
        finalize_transfer(tgt_metadata)

        final_count = count_time_series_associations(tgt_metadata)
        transferred = max(0, final_count - initial_count)

    # Reload metadata into memory
    loader = cast(
        Callable[[], None],
        target_system._time_series_mgr._metadata_store._load_metadata_into_memory,
    )
    loader()

    logger.info(
        f"Time series metadata: {transferred} transferred, {updated} updated, {children_remapped} children remapped"
    )

    return TimeSeriesTransferResult(
        transferred=transferred,
        updated=updated,
        children_remapped=children_remapped,
    )
