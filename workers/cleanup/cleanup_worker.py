"""
Worker для очистки данных.

Выполняет периодическую очистку истекших сессий, старых логов,
кэша и архивирование данных.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict

from sqlalchemy import text, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cache import RedisClient

logger = logging.getLogger(__name__)


class CleanupWorker:
    """
    Worker для очистки данных.
    
    Выполняет:
    - Очистку истекших сессий
    - Удаление старых логов
    - Очистку истекшего кэша
    - Архивирование старых платежей
    """
    
    def __init__(
        self,
        session_factory: async_sessionmaker,
        redis_client: Optional[RedisClient] = None,
        cleanup_interval: int = 3600  # 1 час
    ):
        """
        Инициализация worker.
        
        Args:
            session_factory: Фабрика сессий БД
            redis_client: Redis клиент
            cleanup_interval: Интервал очистки в секундах
        """
        self.session_factory = session_factory
        self.redis = redis_client
        self.cleanup_interval = cleanup_interval
        self._running = False
        self._task: Optional["asyncio.Task[Any]"] = None
    
    async def start(self) -> None:
        """Запуск worker."""
        if self._running:
            logger.warning("CleanupWorker уже запущен")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"CleanupWorker запущен (интервал: {self.cleanup_interval}s)")
    
    async def stop(self) -> None:
        """Остановка worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CleanupWorker остановлен")
    
    async def _run_loop(self) -> None:
        """Основной цикл worker."""
        while self._running:
            try:
                await self.run_cleanup()
                await asyncio.sleep(self.cleanup_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в CleanupWorker: {e}", exc_info=True)
                await asyncio.sleep(60)  # Ждем минуту перед повтором
    
    async def run_cleanup(self) -> Dict[str, int]:
        """
        Выполнение всех задач очистки.
        
        Returns:
            Словарь с результатами очистки
        """
        logger.info("Запуск очистки данных")
        
        results = {
            'sessions': await self.cleanup_expired_sessions(),
            'logs': await self.cleanup_old_logs(),
            'cache': await self.cleanup_expired_cache(),
            'payments': await self.cleanup_old_payments()
        }
        
        logger.info(f"Очистка завершена: {results}")
        return results
    
    async def cleanup_expired_sessions(self, days: int = 7) -> int:
        """
        Очистка истекших сессий.
        
        Args:
            days: Удалять сессии старше N дней
            
        Returns:
            Количество удаленных сессий
        """
        try:
            async with self.session_factory() as session:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                
                query = text("""
                    DELETE FROM sessions
                    WHERE expires_at < :cutoff_date
                    OR created_at < :cutoff_date
                """)
                
                result = await session.execute(query, {"cutoff_date": cutoff_date})
                await session.commit()
                
                deleted = result.rowcount
                logger.info(f"Удалено {deleted} истекших сессий")
                return deleted
                
        except Exception as e:
            logger.error(f"Ошибка очистки сессий: {e}", exc_info=True)
            return 0
    
    async def cleanup_old_logs(self, days: int = 30) -> int:
        """
        Очистка старых логов.
        
        Args:
            days: Удалять логи старше N дней
            
        Returns:
            Количество удаленных записей
        """
        try:
            async with self.session_factory() as session:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                
                query = text("""
                    DELETE FROM message_logs
                    WHERE created_at < :cutoff_date
                """)
                
                result = await session.execute(query, {"cutoff_date": cutoff_date})
                await session.commit()
                
                deleted = result.rowcount
                logger.info(f"Удалено {deleted} старых логов")
                return deleted
                
        except Exception as e:
            logger.error(f"Ошибка очистки логов: {e}", exc_info=True)
            return 0
    
    async def cleanup_expired_cache(self) -> int:
        """
        Очистка истекшего кэша Redis.
        
        Returns:
            Количество удаленных ключей
        """
        if not self.redis:
            logger.warning("Redis клиент недоступен")
            return 0
        
        try:
            # Redis автоматически удаляет истекшие ключи,
            # но мы можем принудительно очистить определенные паттерны
            deleted = 0
            
            # Очищаем временные ключи
            deleted += self.redis.delete_pattern('temp:*')
            
            logger.info(f"Очищено {deleted} ключей кэша")
            return deleted
            
        except Exception as e:
            logger.error(f"Ошибка очистки кэша: {e}", exc_info=True)
            return 0
    
    async def cleanup_old_payments(self, days: int = 90) -> int:
        """
        Архивирование старых платежей.
        
        Args:
            days: Архивировать платежи старше N дней
            
        Returns:
            Количество архивированных записей
        """
        try:
            async with self.session_factory() as session:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                
                # Помечаем старые завершенные платежи как архивные
                query = text("""
                    UPDATE payments
                    SET metadata = jsonb_set(
                        COALESCE(metadata, '{}'::jsonb),
                        '{archived}',
                        'true'::jsonb
                    )
                    WHERE created_at < :cutoff_date
                    AND status IN ('completed', 'failed', 'cancelled')
                    AND (metadata->>'archived' IS NULL OR metadata->>'archived' = 'false')
                """)
                
                result = await session.execute(query, {"cutoff_date": cutoff_date})
                await session.commit()
                
                archived = result.rowcount
                logger.info(f"Архивировано {archived} старых платежей")
                return archived
                
        except Exception as e:
            logger.error(f"Ошибка архивирования платежей: {e}", exc_info=True)
            return 0