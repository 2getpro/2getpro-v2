"""
Health checker для проверки состояния системы.

Проверяет:
- Подключение к БД
- Подключение к Redis
- Доступность Telegram API
- Доступность панели управления
- Доступность платежных систем
"""

from typing import Dict, Any, Optional
import asyncio
import aiohttp
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import redis.asyncio as aioredis


class HealthChecker:
    """Класс для проверки здоровья системы."""
    
    def __init__(
        self,
        db_session: Optional[AsyncSession] = None,
        redis_url: Optional[str] = None,
        telegram_token: Optional[str] = None,
        panel_url: Optional[str] = None,
        payment_systems: Optional[Dict[str, str]] = None
    ):
        """
        Инициализация health checker.
        
        Args:
            db_session: Сессия БД
            redis_url: URL Redis
            telegram_token: Токен Telegram бота
            panel_url: URL панели управления
            payment_systems: Словарь платежных систем {name: url}
        """
        self.db_session = db_session
        self.redis_url = redis_url
        self.telegram_token = telegram_token
        self.panel_url = panel_url
        self.payment_systems = payment_systems or {}
        self._redis_client: Optional[aioredis.Redis] = None
    
    async def check_database(self) -> Dict[str, Any]:
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
            
            # Простой запрос для проверки подключения
            result = await self.db_session.execute(text('SELECT 1'))
            result.scalar()
            
            return {
                'status': 'healthy',
                'message': 'Database connection is working',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Database connection failed: {str(e)}',
                'error': type(e).__name__,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    async def check_redis(self) -> Dict[str, Any]:
        """
        Проверка подключения к Redis.
        
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
            
            return {
                'status': 'healthy',
                'message': 'Redis connection is working',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Redis connection failed: {str(e)}',
                'error': type(e).__name__,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    async def check_telegram_api(self) -> Dict[str, Any]:
        """
        Проверка доступности Telegram API.
        
        Returns:
            Словарь с результатом проверки
        """
        try:
            if not self.telegram_token:
                return {
                    'status': 'unknown',
                    'message': 'Telegram token not configured',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            url = f'https://api.telegram.org/bot{self.telegram_token}/getMe'
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('ok'):
                            return {
                                'status': 'healthy',
                                'message': 'Telegram API is accessible',
                                'bot_username': data.get('result', {}).get('username'),
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            }
                    
                    return {
                        'status': 'unhealthy',
                        'message': f'Telegram API returned status {response.status}',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
        except asyncio.TimeoutError:
            return {
                'status': 'unhealthy',
                'message': 'Telegram API request timeout',
                'error': 'TimeoutError',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Telegram API check failed: {str(e)}',
                'error': type(e).__name__,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    async def check_panel(self) -> Dict[str, Any]:
        """
        Проверка доступности панели управления.
        
        Returns:
            Словарь с результатом проверки
        """
        try:
            if not self.panel_url:
                return {
                    'status': 'unknown',
                    'message': 'Panel URL not configured',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            # Проверяем health endpoint панели
            health_url = f'{self.panel_url.rstrip("/")}/api/health'
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    health_url,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        return {
                            'status': 'healthy',
                            'message': 'Panel is accessible',
                            'timestamp': datetime.now(timezone.utc).isoformat()
                        }
                    
                    return {
                        'status': 'unhealthy',
                        'message': f'Panel returned status {response.status}',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
        except asyncio.TimeoutError:
            return {
                'status': 'unhealthy',
                'message': 'Panel request timeout',
                'error': 'TimeoutError',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Panel check failed: {str(e)}',
                'error': type(e).__name__,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    async def check_payment_system(
        self,
        name: str,
        url: str
    ) -> Dict[str, Any]:
        """
        Проверка доступности платежной системы.
        
        Args:
            name: Название платежной системы
            url: URL для проверки
        
        Returns:
            Словарь с результатом проверки
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status in [200, 301, 302]:
                        return {
                            'status': 'healthy',
                            'message': f'{name} is accessible',
                            'timestamp': datetime.now(timezone.utc).isoformat()
                        }
                    
                    return {
                        'status': 'unhealthy',
                        'message': f'{name} returned status {response.status}',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
        except asyncio.TimeoutError:
            return {
                'status': 'unhealthy',
                'message': f'{name} request timeout',
                'error': 'TimeoutError',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'{name} check failed: {str(e)}',
                'error': type(e).__name__,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    async def check_all_payment_systems(self) -> Dict[str, Dict[str, Any]]:
        """
        Проверка всех платежных систем.
        
        Returns:
            Словарь с результатами проверок
        """
        results = {}
        
        for name, url in self.payment_systems.items():
            results[name] = await self.check_payment_system(name, url)
        
        return results
    
    async def check_all(self) -> Dict[str, Any]:
        """
        Выполнить все проверки здоровья.
        
        Returns:
            Словарь с результатами всех проверок
        """
        # Запускаем все проверки параллельно
        database_check, redis_check, telegram_check, panel_check = await asyncio.gather(
            self.check_database(),
            self.check_redis(),
            self.check_telegram_api(),
            self.check_panel(),
            return_exceptions=True
        )
        
        # Проверяем платежные системы
        payment_systems_check = await self.check_all_payment_systems()
        
        # Определяем общий статус
        all_checks = [
            database_check,
            redis_check,
            telegram_check,
            panel_check,
            *payment_systems_check.values()
        ]
        
        # Фильтруем исключения
        all_checks = [
            check if not isinstance(check, Exception) else {
                'status': 'unhealthy',
                'message': str(check),
                'error': type(check).__name__
            }
            for check in all_checks
        ]
        
        overall_status = 'healthy'
        if any(check.get('status') == 'unhealthy' for check in all_checks):
            overall_status = 'unhealthy'
        elif any(check.get('status') == 'unknown' for check in all_checks):
            overall_status = 'degraded'
        
        return {
            'status': overall_status,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checks': {
                'database': database_check if not isinstance(database_check, Exception) else {
                    'status': 'unhealthy',
                    'message': str(database_check)
                },
                'redis': redis_check if not isinstance(redis_check, Exception) else {
                    'status': 'unhealthy',
                    'message': str(redis_check)
                },
                'telegram_api': telegram_check if not isinstance(telegram_check, Exception) else {
                    'status': 'unhealthy',
                    'message': str(telegram_check)
                },
                'panel': panel_check if not isinstance(panel_check, Exception) else {
                    'status': 'unhealthy',
                    'message': str(panel_check)
                },
                'payment_systems': payment_systems_check
            }
        }
    
    async def close(self) -> None:
        """Закрыть все подключения."""
        if self._redis_client:
            await self._redis_client.close()