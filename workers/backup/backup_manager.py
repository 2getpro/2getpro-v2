"""
Менеджер для управления резервными копиями.

Этот модуль отвечает за управление метаданными бэкапов,
их хранение и получение информации о бэкапах.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import BackupConfig, get_backup_config

logger = logging.getLogger(__name__)


class BackupManager:
    """Менеджер для управления резервными копиями."""
    
    def __init__(self, config: Optional[BackupConfig] = None):
        """
        Инициализация backup manager.
        
        Args:
            config: Конфигурация системы резервного копирования
        """
        self.config = config or get_backup_config()
        self.metadata_dir = Path(self.config.BACKUP_DIR) / "metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
    
    async def save_metadata(self, backup_id: str, metadata: Dict) -> None:
        """
        Сохранение метаданных бэкапа.
        
        Args:
            backup_id: ID бэкапа
            metadata: Метаданные для сохранения
        """
        metadata_file = self.metadata_dir / f"{backup_id}.json"
        
        def save():
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        await asyncio.to_thread(save)
        logger.debug(f"Метаданные сохранены: {backup_id}")
    
    async def get_backup_info(self, backup_id: str) -> Optional[Dict]:
        """
        Получение информации о бэкапе.
        
        Args:
            backup_id: ID бэкапа
            
        Returns:
            Optional[Dict]: Метаданные бэкапа или None
        """
        metadata_file = self.metadata_dir / f"{backup_id}.json"
        
        if not metadata_file.exists():
            logger.warning(f"Метаданные не найдены: {backup_id}")
            return None
        
        def load():
            with open(metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        return await asyncio.to_thread(load)
    
    async def list_backups(
        self,
        backup_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Получение списка всех бэкапов.
        
        Args:
            backup_type: Тип бэкапа ('full' или 'incremental')
            start_date: Начальная дата фильтрации
            end_date: Конечная дата фильтрации
            
        Returns:
            List[Dict]: Список метаданных бэкапов
        """
        backups = []
        
        def load_backups():
            for metadata_file in self.metadata_dir.glob("*.json"):
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        
                        # Фильтрация по типу
                        if backup_type and metadata.get('type') != backup_type:
                            continue
                        
                        # Фильтрация по дате
                        if start_date or end_date:
                            backup_date = datetime.fromisoformat(metadata['timestamp'])
                            if start_date and backup_date < start_date:
                                continue
                            if end_date and backup_date > end_date:
                                continue
                        
                        backups.append(metadata)
                except Exception as e:
                    logger.error(f"Ошибка чтения метаданных {metadata_file}: {e}")
            
            # Сортировка по дате (новые первыми)
            backups.sort(key=lambda x: x['timestamp'], reverse=True)
            return backups
        
        return await asyncio.to_thread(load_backups)
    
    async def get_latest_backup(self, backup_type: Optional[str] = None) -> Optional[Dict]:
        """
        Получение последнего бэкапа.
        
        Args:
            backup_type: Тип бэкапа ('full' или 'incremental')
            
        Returns:
            Optional[Dict]: Метаданные последнего бэкапа или None
        """
        backups = await self.list_backups(backup_type=backup_type)
        return backups[0] if backups else None
    
    async def delete_backup(self, backup_id: str) -> bool:
        """
        Удаление бэкапа.
        
        Args:
            backup_id: ID бэкапа
            
        Returns:
            bool: True если удаление успешно
        """
        logger.info(f"Удаление бэкапа: {backup_id}")
        
        try:
            # Удаление файлов бэкапа
            backup_dir = Path(self.config.BACKUP_DIR)
            for backup_file in backup_dir.glob(f"{backup_id}*"):
                backup_file.unlink()
                logger.debug(f"Удален файл: {backup_file}")
            
            # Удаление метаданных
            metadata_file = self.metadata_dir / f"{backup_id}.json"
            if metadata_file.exists():
                metadata_file.unlink()
                logger.debug(f"Удалены метаданные: {metadata_file}")
            
            logger.info(f"Бэкап удален: {backup_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка удаления бэкапа {backup_id}: {e}", exc_info=True)
            return False
    
    async def calculate_backup_size(self, backup_id: str) -> int:
        """
        Расчет размера бэкапа.
        
        Args:
            backup_id: ID бэкапа
            
        Returns:
            int: Размер бэкапа в байтах
        """
        total_size = 0
        backup_dir = Path(self.config.BACKUP_DIR)
        
        for backup_file in backup_dir.glob(f"{backup_id}*"):
            if backup_file.is_file():
                total_size += backup_file.stat().st_size
        
        return total_size
    
    async def get_backup_statistics(self) -> Dict:
        """
        Получение статистики по бэкапам.
        
        Returns:
            Dict: Статистика бэкапов
        """
        backups = await self.list_backups()
        
        stats = {
            'total_backups': len(backups),
            'full_backups': len([b for b in backups if b.get('type') == 'full']),
            'incremental_backups': len([b for b in backups if b.get('type') == 'incremental']),
            'total_size': sum(b.get('size', 0) for b in backups),
            'successful_backups': len([b for b in backups if b.get('status') == 'completed']),
            'failed_backups': len([b for b in backups if b.get('status') == 'failed']),
            'oldest_backup': None,
            'newest_backup': None
        }
        
        if backups:
            stats['oldest_backup'] = backups[-1]['timestamp']
            stats['newest_backup'] = backups[0]['timestamp']
        
        return stats
    
    async def verify_backup_integrity(self, backup_id: str) -> bool:
        """
        Проверка целостности бэкапа.
        
        Args:
            backup_id: ID бэкапа
            
        Returns:
            bool: True если бэкап целостен
        """
        metadata = await self.get_backup_info(backup_id)
        if not metadata:
            return False
        
        # Проверка существования файлов
        backup_dir = Path(self.config.BACKUP_DIR)
        backup_files = list(backup_dir.glob(f"{backup_id}*"))
        
        if not backup_files:
            logger.error(f"Файлы бэкапа не найдены: {backup_id}")
            return False
        
        # Проверка размера
        if 'size' in metadata:
            actual_size = sum(f.stat().st_size for f in backup_files if f.is_file())
            if actual_size != metadata['size']:
                logger.error(f"Размер бэкапа не совпадает: {backup_id}")
                return False
        
        return True
    
    async def export_backup_list(self, output_file: str) -> None:
        """
        Экспорт списка бэкапов в файл.
        
        Args:
            output_file: Путь к файлу для экспорта
        """
        backups = await self.list_backups()
        
        def export():
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(backups, f, indent=2, ensure_ascii=False)
        
        await asyncio.to_thread(export)
        logger.info(f"Список бэкапов экспортирован: {output_file}")
    
    async def cleanup_incomplete_backups(self) -> int:
        """
        Очистка незавершенных бэкапов.
        
        Returns:
            int: Количество удаленных бэкапов
        """
        logger.info("Очистка незавершенных бэкапов")
        
        backups = await self.list_backups()
        deleted_count = 0
        
        for backup in backups:
            if backup.get('status') != 'completed':
                backup_id = backup['backup_id']
                if await self.delete_backup(backup_id):
                    deleted_count += 1
        
        logger.info(f"Удалено незавершенных бэкапов: {deleted_count}")
        return deleted_count
    
    async def get_backup_path(self, backup_id: str) -> Optional[Path]:
        """
        Получение пути к файлу бэкапа.
        
        Args:
            backup_id: ID бэкапа
            
        Returns:
            Optional[Path]: Путь к файлу бэкапа или None
        """
        backup_dir = Path(self.config.BACKUP_DIR)
        backup_files = list(backup_dir.glob(f"{backup_id}*"))
        
        if not backup_files:
            return None
        
        # Возвращаем первый найденный файл (основной файл бэкапа)
        return backup_files[0]
    
    async def update_backup_status(self, backup_id: str, status: str, error: Optional[str] = None) -> None:
        """
        Обновление статуса бэкапа.
        
        Args:
            backup_id: ID бэкапа
            status: Новый статус
            error: Сообщение об ошибке (опционально)
        """
        metadata = await self.get_backup_info(backup_id)
        if not metadata:
            logger.warning(f"Метаданные не найдены для обновления статуса: {backup_id}")
            return
        
        metadata['status'] = status
        if error:
            metadata['error'] = error
        metadata['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        await self.save_metadata(backup_id, metadata)
        logger.info(f"Статус бэкапа обновлен: {backup_id} -> {status}")