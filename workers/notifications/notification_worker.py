"""
Worker для отправки уведомлений.

Выполняет периодическую отправку уведомлений пользователям
о истечении подписок, платежах и промо-акциях.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from aiogram import Bot

logger = logging.getLogger(__name__)


class NotificationWorker:
    """
    Worker для отправки уведомлений.
    
    Выполняет:
    - Напоминания об истечении подписки
    - Напоминания об оплате
    - Промо-сообщения
    """
    
    def __init__(
        self,
        session_factory: async_sessionmaker,
        bot: Optional[Bot] = None,
        check_interval: int = 3600  # 1 час
    ):
        """
        Инициализация worker.
        
        Args:
            session_factory: Фабрика сессий БД
            bot: Telegram бот для отправки сообщений
            check_interval: Интервал проверки в секундах
        """
        self.session_factory = session_factory
        self.bot = bot
        self.check_interval = check_interval
        self._running = False
        self._task: Optional["asyncio.Task[Any]"] = None
    
    async def start(self) -> None:
        """Запуск worker."""
        if self._running:
            logger.warning("NotificationWorker уже запущен")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"NotificationWorker запущен (интервал: {self.check_interval}s)")
    
    async def stop(self) -> None:
        """Остановка worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NotificationWorker остановлен")
    
    async def _run_loop(self) -> None:
        """Основной цикл worker."""
        while self._running:
            try:
                await self.process_notifications()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в NotificationWorker: {e}", exc_info=True)
                await asyncio.sleep(60)
    
    async def process_notifications(self) -> Dict[str, int]:
        """
        Обработка всех уведомлений.
        
        Returns:
            Словарь с результатами отправки
        """
        logger.info("Обработка уведомлений")
        
        results = {
            'expiration_reminders': await self.send_expiration_reminders(),
            'payment_reminders': await self.send_payment_reminders()
        }
        
        logger.info(f"Уведомления обработаны: {results}")
        return results
    
    async def send_expiration_reminders(self, days_before: int = 3) -> int:
        """
        Отправка напоминаний об истечении подписки.
        
        Args:
            days_before: За сколько дней до истечения отправлять
            
        Returns:
            Количество отправленных уведомлений
        """
        if not self.bot:
            logger.warning("Bot недоступен для отправки уведомлений")
            return 0
        
        try:
            async with self.session_factory() as session:
                # Находим подписки, истекающие через N дней
                target_date = datetime.now(timezone.utc) + timedelta(days=days_before)
                start_range = target_date.replace(hour=0, minute=0, second=0)
                end_range = target_date.replace(hour=23, minute=59, second=59)
                
                query = text("""
                    SELECT 
                        s.id,
                        s.user_id,
                        u.telegram_id,
                        s.expires_at,
                        s.plan_id
                    FROM subscriptions s
                    JOIN users u ON s.user_id = u.id
                    WHERE s.status = 'active'
                    AND s.expires_at BETWEEN :start_range AND :end_range
                    AND u.is_active = true
                    AND u.is_banned = false
                """)
                
                result = await session.execute(query, {
                    "start_range": start_range,
                    "end_range": end_range
                })
                
                subscriptions = result.fetchall()
                sent = 0
                
                for sub in subscriptions:
                    try:
                        telegram_id = sub[2]
                        expires_at = sub[3]
                        
                        message = (
                            f"⚠️ Ваша подписка истекает {expires_at.strftime('%d.%m.%Y')}!\n\n"
                            f"Продлите подписку, чтобы продолжить пользоваться сервисом."
                        )
                        
                        await self.bot.send_message(telegram_id, message)
                        sent += 1
                        
                        # Небольшая задержка между сообщениями
                        await asyncio.sleep(0.1)
                        
                    except Exception as e:
                        logger.error(f"Ошибка отправки напоминания: {e}")
                
                logger.info(f"Отправлено {sent} напоминаний об истечении подписки")
                return sent
                
        except Exception as e:
            logger.error(f"Ошибка отправки напоминаний: {e}", exc_info=True)
            return 0
    
    async def send_payment_reminders(self) -> int:
        """
        Отправка напоминаний об оплате.
        
        Returns:
            Количество отправленных уведомлений
        """
        if not self.bot:
            logger.warning("Bot недоступен для отправки уведомлений")
            return 0
        
        try:
            async with self.session_factory() as session:
                # Находим неоплаченные платежи старше 1 часа
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
                
                query = text("""
                    SELECT 
                        p.id,
                        p.user_id,
                        u.telegram_id,
                        p.amount,
                        p.created_at
                    FROM payments p
                    JOIN users u ON p.user_id = u.id
                    WHERE p.status = 'pending'
                    AND p.created_at < :cutoff_time
                    AND u.is_active = true
                    AND u.is_banned = false
                """)
                
                result = await session.execute(query, {"cutoff_time": cutoff_time})
                payments = result.fetchall()
                sent = 0
                
                for payment in payments:
                    try:
                        telegram_id = payment[2]
                        amount = payment[3]
                        
                        message = (
                            f"💳 У вас есть неоплаченный платеж на сумму {amount} руб.\n\n"
                            f"Завершите оплату, чтобы активировать подписку."
                        )
                        
                        await self.bot.send_message(telegram_id, message)
                        sent += 1
                        await asyncio.sleep(0.1)
                        
                    except Exception as e:
                        logger.error(f"Ошибка отправки напоминания об оплате: {e}")
                
                logger.info(f"Отправлено {sent} напоминаний об оплате")
                return sent
                
        except Exception as e:
            logger.error(f"Ошибка отправки напоминаний об оплате: {e}", exc_info=True)
            return 0
    
    async def send_promotional_messages(
        self,
        user_ids: List[int],
        message: str
    ) -> int:
        """
        Отправка промо-сообщений.
        
        Args:
            user_ids: Список ID пользователей
            message: Текст сообщения
            
        Returns:
            Количество отправленных сообщений
        """
        if not self.bot:
            logger.warning("Bot недоступен для отправки сообщений")
            return 0
        
        try:
            async with self.session_factory() as session:
                # Получаем telegram_id пользователей
                query = text("""
                    SELECT telegram_id
                    FROM users
                    WHERE id = ANY(:user_ids)
                    AND is_active = true
                    AND is_banned = false
                """)
                
                result = await session.execute(query, {"user_ids": user_ids})
                telegram_ids = [row[0] for row in result.fetchall()]
                
                sent = 0
                for telegram_id in telegram_ids:
                    try:
                        await self.bot.send_message(telegram_id, message)
                        sent += 1
                        await asyncio.sleep(0.05)  # 20 сообщений в секунду
                    except Exception as e:
                        logger.error(f"Ошибка отправки промо-сообщения: {e}")
                
                logger.info(f"Отправлено {sent} промо-сообщений")
                return sent
                
        except Exception as e:
            logger.error(f"Ошибка отправки промо-сообщений: {e}", exc_info=True)
            return 0