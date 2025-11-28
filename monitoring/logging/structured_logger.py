"""
Структурированный логгер для создания структурированных логов.

Включает:
- Класс для создания структурированных логов
- Добавление контекста (request_id, user_id, etc.)
- Методы для разных уровней логирования
- Интеграция с Sentry
"""

from typing import Optional, Dict, Any
import logging
import uuid
from datetime import datetime, timezone
import json


class StructuredLogger:
    """Класс для создания структурированных логов."""
    
    def __init__(
        self,
        name: str,
        default_context: Optional[Dict[str, Any]] = None
    ):
        """
        Инициализация структурированного логгера.
        
        Args:
            name: Имя логгера
            default_context: Контекст по умолчанию
        """
        self.logger = logging.getLogger(name)
        self.default_context = default_context or {}
        self._context_stack: list = []
    
    def _format_message(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Форматировать сообщение в структурированный формат.
        
        Args:
            message: Сообщение
            extra: Дополнительные данные
            **kwargs: Дополнительные поля
        
        Returns:
            Структурированное сообщение
        """
        # Базовая структура
        structured = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'message': message,
        }
        
        # Добавляем контекст по умолчанию
        structured.update(self.default_context)
        
        # Добавляем контекст из стека
        for context in self._context_stack:
            structured.update(context)
        
        # Добавляем extra данные
        if extra:
            structured.update(extra)
        
        # Добавляем kwargs
        structured.update(kwargs)
        
        return structured
    
    def debug(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """
        Логировать DEBUG сообщение.
        
        Args:
            message: Сообщение
            extra: Дополнительные данные
            **kwargs: Дополнительные поля
        """
        structured = self._format_message(message, extra, **kwargs)
        self.logger.debug(json.dumps(structured))
    
    def info(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """
        Логировать INFO сообщение.
        
        Args:
            message: Сообщение
            extra: Дополнительные данные
            **kwargs: Дополнительные поля
        """
        structured = self._format_message(message, extra, **kwargs)
        self.logger.info(json.dumps(structured))
    
    def warning(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """
        Логировать WARNING сообщение.
        
        Args:
            message: Сообщение
            extra: Дополнительные данные
            **kwargs: Дополнительные поля
        """
        structured = self._format_message(message, extra, **kwargs)
        self.logger.warning(json.dumps(structured))
    
    def error(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = False,
        **kwargs
    ) -> None:
        """
        Логировать ERROR сообщение.
        
        Args:
            message: Сообщение
            extra: Дополнительные данные
            exc_info: Включить информацию об исключении
            **kwargs: Дополнительные поля
        """
        structured = self._format_message(message, extra, **kwargs)
        self.logger.error(json.dumps(structured), exc_info=exc_info)
        
        # Отправляем в Sentry если доступен
        if exc_info:
            try:
                from monitoring.sentry import capture_exception
                import sys
                exc_type, exc_value, exc_traceback = sys.exc_info()
                if exc_value:
                    capture_exception(
                        exc_value,
                        level='error',
                        extra=structured
                    )
            except ImportError:
                pass
    
    def critical(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = False,
        **kwargs
    ) -> None:
        """
        Логировать CRITICAL сообщение.
        
        Args:
            message: Сообщение
            extra: Дополнительные данные
            exc_info: Включить информацию об исключении
            **kwargs: Дополнительные поля
        """
        structured = self._format_message(message, extra, **kwargs)
        self.logger.critical(json.dumps(structured), exc_info=exc_info)
        
        # Отправляем в Sentry если доступен
        if exc_info:
            try:
                from monitoring.sentry import capture_exception
                import sys
                exc_type, exc_value, exc_traceback = sys.exc_info()
                if exc_value:
                    capture_exception(
                        exc_value,
                        level='fatal',
                        extra=structured
                    )
            except ImportError:
                pass
    
    def exception(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """
        Логировать исключение.
        
        Args:
            message: Сообщение
            extra: Дополнительные данные
            **kwargs: Дополнительные поля
        """
        self.error(message, extra, exc_info=True, **kwargs)
    
    def add_context(self, **kwargs) -> None:
        """
        Добавить контекст к логгеру.
        
        Args:
            **kwargs: Поля контекста
        """
        self.default_context.update(kwargs)
    
    def remove_context(self, *keys) -> None:
        """
        Удалить контекст из логгера.
        
        Args:
            *keys: Ключи для удаления
        """
        for key in keys:
            self.default_context.pop(key, None)
    
    def clear_context(self) -> None:
        """Очистить весь контекст."""
        self.default_context.clear()
    
    def push_context(self, **kwargs) -> None:
        """
        Добавить временный контекст в стек.
        
        Args:
            **kwargs: Поля контекста
        """
        self._context_stack.append(kwargs)
    
    def pop_context(self) -> Optional[Dict[str, Any]]:
        """
        Удалить последний контекст из стека.
        
        Returns:
            Удаленный контекст или None
        """
        if self._context_stack:
            return self._context_stack.pop()
        return None
    
    def with_request_id(self, request_id: Optional[str] = None) -> 'LogContext':
        """
        Создать контекст с request_id.
        
        Args:
            request_id: ID запроса (генерируется автоматически если не указан)
        
        Returns:
            Контекстный менеджер
        """
        if not request_id:
            request_id = str(uuid.uuid4())
        return LogContext(self, request_id=request_id)
    
    def with_user(
        self,
        user_id: Optional[int] = None,
        username: Optional[str] = None
    ) -> 'LogContext':
        """
        Создать контекст с информацией о пользователе.
        
        Args:
            user_id: ID пользователя
            username: Имя пользователя
        
        Returns:
            Контекстный менеджер
        """
        context = {}
        if user_id is not None:
            context['user_id'] = user_id
        if username:
            context['username'] = username
        return LogContext(self, **context)
    
    def with_context(self, **kwargs) -> 'LogContext':
        """
        Создать контекст с произвольными полями.
        
        Args:
            **kwargs: Поля контекста
        
        Returns:
            Контекстный менеджер
        """
        return LogContext(self, **kwargs)


class LogContext:
    """Контекстный менеджер для временного добавления контекста."""
    
    def __init__(self, logger: StructuredLogger, **kwargs):
        """
        Инициализация контекста.
        
        Args:
            logger: Структурированный логгер
            **kwargs: Поля контекста
        """
        self.logger = logger
        self.context = kwargs
    
    def __enter__(self):
        """Вход в контекст."""
        self.logger.push_context(**self.context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Выход из контекста."""
        self.logger.pop_context()
        return False
    
    async def __aenter__(self):
        """Асинхронный вход в контекст."""
        self.logger.push_context(**self.context)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный выход из контекста."""
        self.logger.pop_context()
        return False


def get_structured_logger(
    name: str,
    default_context: Optional[Dict[str, Any]] = None
) -> StructuredLogger:
    """
    Получить структурированный логгер.
    
    Args:
        name: Имя логгера
        default_context: Контекст по умолчанию
    
    Returns:
        Структурированный логгер
    """
    return StructuredLogger(name, default_context)