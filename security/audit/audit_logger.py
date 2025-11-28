"""
Audit Logger для логирования действий пользователей и событий безопасности.
"""

from enum import Enum
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import json
import logging

logger = logging.getLogger(__name__)


class AuditEvent(str, Enum):
    """Типы событий аудита."""
    # Действия пользователей
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_REGISTER = "user_register"
    USER_UPDATE = "user_update"
    USER_DELETE = "user_delete"
    
    # Подписки
    SUBSCRIPTION_CREATE = "subscription_create"
    SUBSCRIPTION_RENEW = "subscription_renew"
    SUBSCRIPTION_CANCEL = "subscription_cancel"
    
    # Платежи
    PAYMENT_CREATE = "payment_create"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    PAYMENT_REFUND = "payment_refund"
    
    # Промокоды
    PROMO_CREATE = "promo_create"
    PROMO_USE = "promo_use"
    PROMO_DELETE = "promo_delete"
    
    # Административные действия
    ADMIN_ACTION = "admin_action"
    USER_BAN = "user_ban"
    USER_UNBAN = "user_unban"
    BROADCAST_SEND = "broadcast_send"
    
    # Настройки
    SETTINGS_UPDATE = "settings_update"


class SecurityEvent(str, Enum):
    """Типы событий безопасности."""
    # Аутентификация
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILED = "auth_failed"
    AUTH_BLOCKED = "auth_blocked"
    
    # Rate limiting
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    RATE_LIMIT_BLOCKED = "rate_limit_blocked"
    
    # Webhook
    WEBHOOK_INVALID_SIGNATURE = "webhook_invalid_signature"
    WEBHOOK_INVALID_IP = "webhook_invalid_ip"
    
    # Доступ
    ACCESS_DENIED = "access_denied"
    PERMISSION_DENIED = "permission_denied"
    
    # Подозрительная активность
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    MULTIPLE_FAILED_ATTEMPTS = "multiple_failed_attempts"
    
    # Критические события
    CRITICAL_ERROR = "critical_error"
    SECURITY_BREACH = "security_breach"


class AuditLogger:
    """
    Логгер для аудита действий и событий безопасности.
    """
    
    def __init__(
        self,
        db_session: Optional[AsyncSession] = None,
        sentry_enabled: bool = False
    ):
        """
        Инициализация audit logger.
        
        Args:
            db_session: Сессия БД для сохранения логов
            sentry_enabled: Отправлять ли критические события в Sentry
        """
        self.db_session = db_session
        self.sentry_enabled = sentry_enabled
    
    async def log_action(
        self,
        user_id: int,
        action: AuditEvent,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None
    ) -> bool:
        """
        Логировать действие пользователя.
        
        Args:
            user_id: ID пользователя
            action: Тип действия
            details: Дополнительные детали
            ip_address: IP адрес пользователя
            
        Returns:
            True если успешно залогировано
        """
        try:
            log_entry = {
                'user_id': user_id,
                'action': action.value,
                'details': details or {},
                'ip_address': ip_address,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'action'
            }
            
            # Логируем в файл
            logger.info(
                f"Audit: user={user_id}, action={action.value}, "
                f"details={json.dumps(details or {})}"
            )
            
            # Сохраняем в БД
            if self.db_session:
                await self._save_to_db(log_entry)
            
            return True
            
        except Exception as e:
            logger.error(f"Error logging action: {e}", exc_info=True)
            return False
    
    async def log_security_event(
        self,
        event_type: SecurityEvent,
        details: Dict[str, Any],
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        severity: str = "warning"
    ) -> bool:
        """
        Логировать событие безопасности.
        
        Args:
            event_type: Тип события
            details: Детали события
            user_id: ID пользователя (если применимо)
            ip_address: IP адрес
            severity: Уровень серьезности (info, warning, error, critical)
            
        Returns:
            True если успешно залогировано
        """
        try:
            log_entry = {
                'event_type': event_type.value,
                'details': details,
                'user_id': user_id,
                'ip_address': ip_address,
                'severity': severity,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'security'
            }
            
            # Логируем в файл с соответствующим уровнем
            log_message = (
                f"Security Event: type={event_type.value}, "
                f"severity={severity}, user={user_id}, "
                f"details={json.dumps(details)}"
            )
            
            if severity == "critical":
                logger.critical(log_message)
            elif severity == "error":
                logger.error(log_message)
            elif severity == "warning":
                logger.warning(log_message)
            else:
                logger.info(log_message)
            
            # Сохраняем в БД
            if self.db_session:
                await self._save_to_db(log_entry)
            
            # Отправляем в Sentry для критических событий
            if self.sentry_enabled and severity in ["error", "critical"]:
                await self._send_to_sentry(log_entry)
            
            return True
            
        except Exception as e:
            logger.error(f"Error logging security event: {e}", exc_info=True)
            return False
    
    async def get_user_actions(
        self,
        user_id: int,
        limit: int = 100,
        action_type: Optional[AuditEvent] = None
    ) -> List[Dict[str, Any]]:
        """
        Получить действия пользователя.
        
        Args:
            user_id: ID пользователя
            limit: Максимальное количество записей
            action_type: Фильтр по типу действия
            
        Returns:
            Список действий
        """
        if not self.db_session:
            logger.warning("Database session not available")
            return []
        
        try:
            # Заглушка - в реальной реализации нужна таблица audit_logs
            return []
            
        except Exception as e:
            logger.error(f"Error getting user actions: {e}", exc_info=True)
            return []
    
    async def get_security_events(
        self,
        limit: int = 100,
        severity: Optional[str] = None,
        event_type: Optional[SecurityEvent] = None
    ) -> List[Dict[str, Any]]:
        """
        Получить события безопасности.
        
        Args:
            limit: Максимальное количество записей
            severity: Фильтр по уровню серьезности
            event_type: Фильтр по типу события
            
        Returns:
            Список событий
        """
        if not self.db_session:
            logger.warning("Database session not available")
            return []
        
        try:
            # Заглушка - в реальной реализации нужна таблица audit_logs
            return []
            
        except Exception as e:
            logger.error(f"Error getting security events: {e}", exc_info=True)
            return []
    
    async def _save_to_db(self, log_entry: Dict[str, Any]) -> None:
        """
        Сохранить запись в БД.
        
        Args:
            log_entry: Запись для сохранения
        """
        # Заглушка - в реальной реализации нужна таблица audit_logs
        # Пример структуры таблицы:
        # - id: int (primary key)
        # - user_id: int (nullable)
        # - type: str (action/security)
        # - event: str
        # - details: json
        # - ip_address: str (nullable)
        # - severity: str (nullable)
        # - timestamp: datetime
        pass
    
    async def _send_to_sentry(self, log_entry: Dict[str, Any]) -> None:
        """
        Отправить событие в Sentry.
        
        Args:
            log_entry: Запись для отправки
        """
        try:
            import sentry_sdk
            
            sentry_sdk.capture_message(
                f"Security Event: {log_entry['event_type']}",
                level=log_entry['severity'],
                extras=log_entry
            )
            
        except ImportError:
            logger.warning("Sentry SDK not installed")
        except Exception as e:
            logger.error(f"Error sending to Sentry: {e}", exc_info=True)
    
    async def search_logs(
        self,
        query: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Поиск по логам.
        
        Args:
            query: Поисковый запрос
            limit: Максимальное количество результатов
            
        Returns:
            Список найденных записей
        """
        # Заглушка - в реальной реализации нужен полнотекстовый поиск
        return []
    
    async def get_statistics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Получить статистику по логам.
        
        Args:
            start_date: Начальная дата
            end_date: Конечная дата
            
        Returns:
            Словарь со статистикой
        """
        # Заглушка - в реальной реализации нужна агрегация данных
        return {
            'total_actions': 0,
            'total_security_events': 0,
            'by_severity': {},
            'by_event_type': {},
            'top_users': []
        }