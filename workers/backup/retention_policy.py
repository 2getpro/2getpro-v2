"""
Модуль для управления политикой хранения резервных копий.

Этот модуль реализует retention policy для автоматического
удаления старых бэкапов согласно настроенным правилам.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from .config import BackupConfig, get_backup_config
from .backup_manager import BackupManager
from .s3_storage import S3Storage

logger = logging.getLogger(__name__)


class RetentionPolicy:
    """Класс для управления политикой хранения бэкапов."""
    
    def __init__(self, config: Optional[BackupConfig] = None):
        """
        Инициализация retention policy.
        
        Args:
            config: Конфигурация системы резервного копирования
        """
        self.config = config or get_backup_config()
        self.backup_manager = BackupManager(self.config)
        self.s3_storage = S3Storage(self.config) if self.config.S3_ENABLED else None
    
    async def apply_retention_policy(self) -> Dict[str, int]:
        """
        Применение политики хранения ко всем бэкапам.
        
        Returns:
            Dict[str, int]: Статистика удаленных бэкапов по категориям
        """
        logger.info("Применение политики хранения бэкапов")
        
        stats = {
            'daily_deleted': 0,
            'weekly_deleted': 0,
            'monthly_deleted': 0,
            'yearly_deleted': 0,
            'total_deleted': 0
        }
        
        try:
            # Получение всех бэкапов
            backups = await self.backup_manager.list_backups()
            
            # Классификация бэкапов
            classified = self._classify_backups(backups)
            
            # Применение политики к каждой категории
            stats['daily_deleted'] = await self._apply_daily_retention(classified['daily'])
            stats['weekly_deleted'] = await self._apply_weekly_retention(classified['weekly'])
            stats['monthly_deleted'] = await self._apply_monthly_retention(classified['monthly'])
            stats['yearly_deleted'] = await self._apply_yearly_retention(classified['yearly'])
            
            stats['total_deleted'] = sum([
                stats['daily_deleted'],
                stats['weekly_deleted'],
                stats['monthly_deleted'],
                stats['yearly_deleted']
            ])
            
            logger.info(f"Политика хранения применена. Удалено бэкапов: {stats['total_deleted']}")
            return stats
            
        except Exception as e:
            logger.error(f"Ошибка применения политики хранения: {e}", exc_info=True)
            return stats
    
    def _classify_backups(self, backups: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Классификация бэкапов по категориям (daily, weekly, monthly, yearly).
        
        Args:
            backups: Список всех бэкапов
            
        Returns:
            Dict[str, List[Dict]]: Классифицированные бэкапы
        """
        now = datetime.now(timezone.utc)
        
        classified = {
            'daily': [],
            'weekly': [],
            'monthly': [],
            'yearly': []
        }
        
        for backup in backups:
            if backup.get('type') != 'full':
                continue
            
            backup_date = datetime.fromisoformat(backup['timestamp'])
            age_days = (now - backup_date).days
            
            # Ежедневные бэкапы (до 7 дней)
            if age_days < 7:
                classified['daily'].append(backup)
            
            # Еженедельные бэкапы (7-28 дней, воскресенье)
            elif age_days < 28:
                if backup_date.weekday() == 6:  # Воскресенье
                    classified['weekly'].append(backup)
            
            # Ежемесячные бэкапы (28-365 дней, первое число месяца)
            elif age_days < 365:
                if backup_date.day == 1:
                    classified['monthly'].append(backup)
            
            # Годовые бэкапы (>365 дней, 1 января)
            else:
                if backup_date.month == 1 and backup_date.day == 1:
                    classified['yearly'].append(backup)
        
        return classified
    
    async def _apply_daily_retention(self, daily_backups: List[Dict]) -> int:
        """
        Применение политики хранения для ежедневных бэкапов.
        
        Args:
            daily_backups: Список ежедневных бэкапов
            
        Returns:
            int: Количество удаленных бэкапов
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.config.DAILY_RETENTION_DAYS)
        deleted_count = 0
        
        for backup in daily_backups:
            backup_date = datetime.fromisoformat(backup['timestamp'])
            if backup_date < cutoff_date:
                if await self._delete_backup_with_s3(backup['backup_id']):
                    deleted_count += 1
        
        logger.info(f"Удалено ежедневных бэкапов: {deleted_count}")
        return deleted_count
    
    async def _apply_weekly_retention(self, weekly_backups: List[Dict]) -> int:
        """
        Применение политики хранения для еженедельных бэкапов.
        
        Args:
            weekly_backups: Список еженедельных бэкапов
            
        Returns:
            int: Количество удаленных бэкапов
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(weeks=self.config.WEEKLY_RETENTION_WEEKS)
        deleted_count = 0
        
        for backup in weekly_backups:
            backup_date = datetime.fromisoformat(backup['timestamp'])
            if backup_date < cutoff_date:
                if await self._delete_backup_with_s3(backup['backup_id']):
                    deleted_count += 1
        
        logger.info(f"Удалено еженедельных бэкапов: {deleted_count}")
        return deleted_count
    
    async def _apply_monthly_retention(self, monthly_backups: List[Dict]) -> int:
        """
        Применение политики хранения для ежемесячных бэкапов.
        
        Args:
            monthly_backups: Список ежемесячных бэкапов
            
        Returns:
            int: Количество удаленных бэкапов
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30 * self.config.MONTHLY_RETENTION_MONTHS)
        deleted_count = 0
        
        for backup in monthly_backups:
            backup_date = datetime.fromisoformat(backup['timestamp'])
            if backup_date < cutoff_date:
                if await self._delete_backup_with_s3(backup['backup_id']):
                    deleted_count += 1
        
        logger.info(f"Удалено ежемесячных бэкапов: {deleted_count}")
        return deleted_count
    
    async def _apply_yearly_retention(self, yearly_backups: List[Dict]) -> int:
        """
        Применение политики хранения для годовых бэкапов.
        
        Args:
            yearly_backups: Список годовых бэкапов
            
        Returns:
            int: Количество удаленных бэкапов
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=365 * self.config.YEARLY_RETENTION_YEARS)
        deleted_count = 0
        
        for backup in yearly_backups:
            backup_date = datetime.fromisoformat(backup['timestamp'])
            if backup_date < cutoff_date:
                if await self._delete_backup_with_s3(backup['backup_id']):
                    deleted_count += 1
        
        logger.info(f"Удалено годовых бэкапов: {deleted_count}")
        return deleted_count
    
    async def _delete_backup_with_s3(self, backup_id: str) -> bool:
        """
        Удаление бэкапа локально и из S3.
        
        Args:
            backup_id: ID бэкапа
            
        Returns:
            bool: True если удаление успешно
        """
        try:
            # Удаление из S3
            if self.s3_storage:
                s3_files = await self.s3_storage.list_files(f"backups/{backup_id}/")
                for file_info in s3_files:
                    await self.s3_storage.delete_file(file_info['key'])
            
            # Удаление локально
            await self.backup_manager.delete_backup(backup_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка удаления бэкапа {backup_id}: {e}")
            return False
    
    async def calculate_retention(self, backup_date: datetime) -> str:
        """
        Расчет категории хранения для бэкапа.
        
        Args:
            backup_date: Дата бэкапа
            
        Returns:
            str: Категория хранения (daily/weekly/monthly/yearly)
        """
        now = datetime.now(timezone.utc)
        age_days = (now - backup_date).days
        
        if age_days < 7:
            return 'daily'
        elif age_days < 28:
            return 'weekly' if backup_date.weekday() == 6 else 'daily'
        elif age_days < 365:
            return 'monthly' if backup_date.day == 1 else 'weekly'
        else:
            return 'yearly' if (backup_date.month == 1 and backup_date.day == 1) else 'monthly'
    
    async def get_retention_statistics(self) -> Dict:
        """
        Получение статистики по политике хранения.
        
        Returns:
            Dict: Статистика по категориям
        """
        backups = await self.backup_manager.list_backups()
        classified = self._classify_backups(backups)
        
        now = datetime.now(timezone.utc)
        
        stats = {
            'daily': {
                'count': len(classified['daily']),
                'retention_days': self.config.DAILY_RETENTION_DAYS,
                'oldest': None,
                'newest': None
            },
            'weekly': {
                'count': len(classified['weekly']),
                'retention_weeks': self.config.WEEKLY_RETENTION_WEEKS,
                'oldest': None,
                'newest': None
            },
            'monthly': {
                'count': len(classified['monthly']),
                'retention_months': self.config.MONTHLY_RETENTION_MONTHS,
                'oldest': None,
                'newest': None
            },
            'yearly': {
                'count': len(classified['yearly']),
                'retention_years': self.config.YEARLY_RETENTION_YEARS,
                'oldest': None,
                'newest': None
            }
        }
        
        # Добавление информации о самых старых и новых бэкапах
        for category in ['daily', 'weekly', 'monthly', 'yearly']:
            if classified[category]:
                dates = [datetime.fromisoformat(b['timestamp']) for b in classified[category]]
                stats[category]['oldest'] = min(dates).isoformat()
                stats[category]['newest'] = max(dates).isoformat()
        
        return stats
    
    async def preview_retention_policy(self) -> Dict:
        """
        Предпросмотр применения политики хранения без удаления.
        
        Returns:
            Dict: Информация о бэкапах, которые будут удалены
        """
        logger.info("Предпросмотр политики хранения")
        
        backups = await self.backup_manager.list_backups()
        classified = self._classify_backups(backups)
        
        now = datetime.now(timezone.utc)
        
        to_delete = {
            'daily': [],
            'weekly': [],
            'monthly': [],
            'yearly': []
        }
        
        # Ежедневные
        cutoff_date = now - timedelta(days=self.config.DAILY_RETENTION_DAYS)
        for backup in classified['daily']:
            backup_date = datetime.fromisoformat(backup['timestamp'])
            if backup_date < cutoff_date:
                to_delete['daily'].append(backup)
        
        # Еженедельные
        cutoff_date = now - timedelta(weeks=self.config.WEEKLY_RETENTION_WEEKS)
        for backup in classified['weekly']:
            backup_date = datetime.fromisoformat(backup['timestamp'])
            if backup_date < cutoff_date:
                to_delete['weekly'].append(backup)
        
        # Ежемесячные
        cutoff_date = now - timedelta(days=30 * self.config.MONTHLY_RETENTION_MONTHS)
        for backup in classified['monthly']:
            backup_date = datetime.fromisoformat(backup['timestamp'])
            if backup_date < cutoff_date:
                to_delete['monthly'].append(backup)
        
        # Годовые
        cutoff_date = now - timedelta(days=365 * self.config.YEARLY_RETENTION_YEARS)
        for backup in classified['yearly']:
            backup_date = datetime.fromisoformat(backup['timestamp'])
            if backup_date < cutoff_date:
                to_delete['yearly'].append(backup)
        
        summary = {
            'total_to_delete': sum(len(v) for v in to_delete.values()),
            'by_category': {
                category: len(backups)
                for category, backups in to_delete.items()
            },
            'backups_to_delete': to_delete
        }
        
        logger.info(f"Будет удалено бэкапов: {summary['total_to_delete']}")
        return summary
    
    async def force_cleanup(self, older_than_days: int) -> int:
        """
        Принудительная очистка всех бэкапов старше указанного количества дней.
        
        Args:
            older_than_days: Количество дней
            
        Returns:
            int: Количество удаленных бэкапов
        """
        logger.warning(f"Принудительная очистка бэкапов старше {older_than_days} дней")
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        backups = await self.backup_manager.list_backups()
        deleted_count = 0
        
        for backup in backups:
            backup_date = datetime.fromisoformat(backup['timestamp'])
            if backup_date < cutoff_date:
                if await self._delete_backup_with_s3(backup['backup_id']):
                    deleted_count += 1
        
        logger.info(f"Принудительно удалено бэкапов: {deleted_count}")
        return deleted_count