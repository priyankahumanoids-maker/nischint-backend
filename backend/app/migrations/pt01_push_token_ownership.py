"""PT-01 ? enforce one current user per FCM installation token.

The active push registration API uses::

    ON CONFLICT (token) DO UPDATE ...

That contract requires ``push_tokens.token`` to be globally unique.

Older environments allowed UNIQUE(user_id, token), which can leave the
same installation token attached to multiple accounts.

When an existing token has more than one owner, ownership is ambiguous.
Historical timestamps alone are not authoritative evidence of which
account currently owns the physical installation. PT-01 therefore
fails closed: all rows for an ambiguous token are removed before the
single-column unique index is created. The currently authenticated
mobile installation can then register the token again and establish
one authoritative owner.

The migration is idempotent and safe to run on every application boot.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_push_token_single_owner() -> int:
    """Remove ambiguous token ownership and enforce UNIQUE(token).

    Returns the number of ambiguous ownership rows removed during this
    invocation.
    """
    from app.db.session import async_session

    async with async_session() as session:
        table_exists = (
            await session.execute(
                text(
                    "SELECT to_regclass('public.push_tokens')"
                )
            )
        ).scalar()

        if not table_exists:
            raise RuntimeError(
                "push_tokens table is missing"
            )

        # Prevent registrations from racing the ownership repair.
        # Readers remain available while this short transaction runs.
        await session.execute(
            text(
                "LOCK TABLE public.push_tokens "
                "IN SHARE ROW EXCLUSIVE MODE"
            )
        )

        # Security rule:
        #
        # If one FCM installation token currently points at more than
        # one row, do NOT guess its owner from historical timestamps.
        # Purge every ambiguous ownership row. A live authenticated
        # installation will register again through /push/token.
        delete_result = await session.execute(
            text(
                """
                WITH ambiguous_tokens AS (
                    SELECT token
                    FROM public.push_tokens
                    GROUP BY token
                    HAVING COUNT(*) > 1
                )
                DELETE FROM public.push_tokens AS pt
                USING ambiguous_tokens AS ambiguous
                WHERE pt.token = ambiguous.token
                """
            )
        )

        # PostgreSQL can now infer this index for:
        #
        #     ON CONFLICT (token)
        #
        # Keep the existing UNIQUE(user_id, token) constraint for
        # backwards compatibility.
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_push_tokens_token "
                "ON public.push_tokens (token)"
            )
        )

        await session.commit()

        rowcount = getattr(
            delete_result,
            "rowcount",
            0,
        )

        try:
            removed = max(
                0,
                int(rowcount or 0),
            )
        except (TypeError, ValueError):
            removed = 0

        logger.info(
            "[PT-01] push token ownership ready: "
            "ambiguous_rows_purged=%d "
            "unique_token_index=ready",
            removed,
        )

        return removed
