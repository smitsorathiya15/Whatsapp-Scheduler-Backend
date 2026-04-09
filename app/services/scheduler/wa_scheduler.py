"""Background APScheduler that fires WhatsApp messages on matching schedules."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config.setting import settings

logger = logging.getLogger(__name__)


class WAScheduler:
    """Singleton background scheduler — checks DB and fires messages every N seconds."""

    _instance: Optional["WAScheduler"] = None

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)

    @classmethod
    def get_instance(cls) -> "WAScheduler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        self._scheduler.add_job(
            self._tick,
            "interval",
            seconds=settings.SCHEDULER_INTERVAL_SECONDS,
            id="wa_tick",
        )
        self._scheduler.start()
        logger.info("WAScheduler started — interval %ss.", settings.SCHEDULER_INTERVAL_SECONDS)

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("WAScheduler stopped.")

    @staticmethod
    async def _tick() -> None:
        """
        Find all due schedules and dispatch messages.

        Each unique user whose schedule is due is processed as an independent
        async task — users never block each other.
        """
        from app.config.postgres import DatabaseManager
        from app.model.schedule import Schedule
        from app.model.message_template import MessageTemplate
        from app.model.group import Group
        from app.model.user import User
        from app.services.whatsapp.bot import WhatsAppBot
        from sqlalchemy import select

        now          = datetime.now()
        current_day  = now.strftime("%A").lower()
        current_time = now.strftime("%H:%M:00")

        db_manager = DatabaseManager.get_instance()
        async with db_manager.async_session_local() as db:

            # Fetch all active schedules due right now
            result = await db.execute(
                select(Schedule).where(Schedule.is_active == True)  # noqa: E712
            )
            all_schedules = result.scalars().all()

            due = [
                s for s in all_schedules
                if current_day in [d.lower() for d in (s.days_of_week or [])]
                and s.time_of_day == current_time
            ]

            if not due:
                return

            # Group due schedules by user_id
            by_user: dict = {}
            for schedule in due:
                by_user.setdefault(schedule.user_id, []).append(schedule)

            # Build per-user payloads (template + groups) while still inside the DB session
            user_payloads = []
            for user_id, schedules in by_user.items():

                user_result = await db.execute(select(User).where(User.id == user_id))
                user = user_result.scalar_one_or_none()
                if not user or not user.wa_linked:
                    logger.warning("Skipping user %s — wa_linked is False.", user_id)
                    continue

                jobs = []
                for schedule in schedules:
                    tmpl = (await db.execute(
                        select(MessageTemplate).where(MessageTemplate.id == schedule.message_template_id)
                    )).scalar_one_or_none()
                    if not tmpl:
                        continue

                    groups = (await db.execute(
                        select(Group).where(
                            Group.user_id == user_id,
                            Group.is_active == True,  # noqa: E712
                        )
                    )).scalars().all()

                    jobs.append((schedule.id, tmpl.content, [g.whatsapp_group_name for g in groups]))

                if jobs:
                    user_payloads.append((user_id, jobs))

        # All DB work is done — now dispatch each user concurrently
        bot = WhatsAppBot.get_instance()
        await asyncio.gather(
            *[WAScheduler._send_for_user(bot, user_id, jobs) for user_id, jobs in user_payloads],
            return_exceptions=True,
        )

    @staticmethod
    async def _send_for_user(bot, user_id, jobs) -> None:
        """
        Restore (or reuse) the session for one user then send all their due messages.

        Because each user has their own Chrome instance, this runs fully in
        parallel with other users — turning off one user's PC does not affect
        another user's session.
        """
        # Get or restore the session for this user
        session = await bot.session_for(user_id)

        if not session.is_logged_in:
            logger.warning(
                "User %s has wa_linked=True in DB but Chrome session is not logged in. "
                "Attempting to detect state from saved profile.",
                user_id,
            )
            # _detect runs during ensure_started; if still not logged in, skip
            if not session.is_logged_in:
                logger.error(
                    "User %s: session could not be restored — user must re-scan QR. Skipping.",
                    user_id,
                )
                return

        for schedule_id, content, group_names in jobs:
            for group_name in group_names:
                success = await session.send_message(group_name, content)
                logger.info(
                    "Schedule %s → user %s → '%s' → %s",
                    schedule_id, user_id, group_name, "OK" if success else "FAIL",
                )
