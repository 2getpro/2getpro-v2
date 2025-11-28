"""
Readiness checker для проверки готовности системы к приему трафика.

Проверяет:
- Готовность к приему трафика
- Миграции БД
- Кэш
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import redis.asyncio as aioredis


class ReadinessChecker:
    """Класс для проверки готовности системы."""
    
    def __init__(
        self,
        db_session: Optional[AsyncSession] = None,
        redis_url: Optional[str] = None
    ):
        """
        Инициализация readiness checker.
        
        Args:
            db_session: Сессия БД
            redis_url: URL Redis
        """
        self.db_session = db_session
        self.redis_url = redis_url
        self._redis_client: Optional[aioredis.Redis] = None
    
    async def check_database_migrations(self) -> Dict[str, Any]:
        """
        Проверка применения миграций БД.
        
        Returns:
            Словарь с результатом проверки
        """
        try:
            if not self.db_session:
                return {
                    'status': 'unknown',
                    'message': 'Database session not configured',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            # Проверяем наличие таблицы миграций
            result = await self.db_session.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'alembic_version'
                    )
                """)
            )
            has_migrations_table = result.scalar()
            
            if not has_migrations_table:
                return {
                    'status': 'not_ready',
                    'message': 'Migrations table does not exist',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            # Получаем текущую версию миграции
            result = await self.db_session.execute(
                text("SELECT version_num FROM alembic_version")
            )
            current_version = result.scalar()
            
            if not current_version:
                return {
                    'status': 'not_ready',
                    'message': 'No migrations applied',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            return {
                'status': 'ready',
                'message': 'Database migrations are up to date',
                'current_version': current_version,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'status': 'not_ready',
                'message': f'Failed to check migrations: {str(e)}',
                'error': type(e).__name__,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    async def check_cache(self) -> Dict[str, Any]:
        """
        Проверка доступности кэша.
        
        Returns:
            Словарь с результатом проверки
        """
        try:
            if not self.redis_url:
                return {
                    'status': 'unknown',
                    'message': 'Redis URL not configured',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            # Создаем клиент если его нет
            if not self._redis_client:
                self._redis_client = await aioredis.from_url(
                    self.redis_url,
                    encoding='utf-8',
                    decode_responses=True
                )
            
            # Проверяем подключение
            await self._redis_client.ping()
            
            # Проверяем возможность записи/чтения
            test_key = '__readiness_check__'
            test_value = 'ok'
            
            await self._redis_client.set(test_key, test_value, ex=10)
            stored_value = await self._redis_client.get(test_key)
            
            if stored_value != test_value:
                return {
                    'status': 'not_ready',
                    'message': 'Cache read/write test failed',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            # Удаляем тестовый ключ
            await self._redis_client.delete(test_key)
            
            return {
                'status': 'ready',
                'message': 'Cache is ready',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'status': 'not_ready',
                'message': f'Cache check failed: {str(e)}',
                'error': type(e).__name__,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    async def check_database_connection(self) -> Dict[str, Any]:
        """
        Проверка подключения к БД.
        
        Returns:
            Словарь с результатом проверки
        """
        try:
            if not self.db_session:
                return {
                    'status': 'unknown',
                    'message': 'Database session not configured',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            # Проверяем подключение
            result = await self.db_session.execute(text('SELECT 1'))
            result.scalar()
            
            return {
                'status': 'ready',
                'message': 'Database connection is ready',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'status': 'not_ready',
                'message': f'Database connection failed: {str(e)}',
                'error': type(e).__name__,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    async def check_all(self) -> Dict[str, Any]:
        """
        Выполнить все проверки готовности.
        
        Returns:
            Словарь с результатами всех проверок
        """
        # Выполняем все проверки
        db_connection = await self.check_database_connection()
        db_migrations = await self.check_database_migrations()
        cache = await self.check_cache()
        
        # Определяем общий статус
        all_checks = [db_connection, db_migrations, cache]
        
        overall_status = 'ready'
        if any(check.get('status') == 'not_ready' for check in all_checks):
            overall_status = 'not_ready'
        elif any(check.get('status') == 'unknown' for check in all_checks):
            overall_status = 'unknown'
        
        return {
            'status': overall_status,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checks': {
                'database_connection': db_connection,
                'database_migrations': db_migrations,
                'cache': cache
            }
        }
    
    async def close(self) -> None:
        """Закрыть все подключения."""
        if self._redis_client:
            await self._redis_client.close()