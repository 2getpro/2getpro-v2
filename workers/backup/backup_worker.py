"""
Основной worker для создания резервных копий базы данных.

Этот модуль отвечает за создание полных и инкрементальных бэкапов,
их сжатие, шифрование и планирование.
"""

import asyncio
import gzip
import hashlib
import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2

from .config import BackupConfig, get_backup_config
from .backup_manager import BackupManager
from .s3_storage import S3Storage

logger = logging.getLogger(__name__)


class BackupWorker:
    """Worker для создания и управления резервными копиями."""
    
    def __init__(self, config: Optional[BackupConfig] = None):
        """
        Инициализация backup worker.
        
        Args:
            config: Конфигурация системы резервного копирования
        """
        self.config = config or get_backup_config()
        self.backup_manager = BackupManager(self.config)
        self.s3_storage = S3Storage(self.config) if self.config.S3_ENABLED else None
        self._setup_directories()
        self._setup_encryption()
    
    def _setup_directories(self) -> None:
        """Создание необходимых директорий."""
        Path(self.config.BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        if self.config.WAL_ARCHIVE_ENABLED:
            Path(self.config.WAL_ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
        
        log_dir = Path(self.config.LOG_FILE).parent
        log_dir.mkdir(parents=True, exist_ok=True)
    
    def _setup_encryption(self) -> None:
        """Настройка шифрования."""
        if self.config.ENCRYPTION_ENABLED and self.config.ENCRYPTION_KEY:
            # Генерация ключа из пароля
            kdf = PBKDF2(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b'backup_salt_2getpro',  # В продакшене использовать случайную соль
                iterations=100000,
            )
            key = kdf.derive(self.config.ENCRYPTION_KEY.encode())
            self.cipher = Fernet(key)
        else:
            self.cipher = None
    
    async def create_full_backup(self) -> str:
        """
        Создание полного бэкапа базы данных.
        
        Returns:
            str: ID созданного бэкапа
            
        Raises:
            Exception: При ошибке создания бэкапа
        """
        backup_id = f"full_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        backup_path = Path(self.config.BACKUP_DIR) / f"{backup_id}.sql"
        
        logger.info(f"Начало создания полного бэкапа: {backup_id}")
        
        try:
            # Создание дампа базы данных
            await self._create_pg_dump(backup_path)
            
            # Сжатие
            if self.config.COMPRESSION_ENABLED:
                backup_path = await self._compress_backup(backup_path)
            
            # Шифрование
            if self.config.ENCRYPTION_ENABLED:
                backup_path = await self._encrypt_backup(backup_path)
            
            # Проверка целостности
            checksum = await self._calculate_checksum(backup_path)
            
            # Сохранение метаданных
            metadata = {
                'backup_id': backup_id,
                'type': 'full',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'size': backup_path.stat().st_size,
                'checksum': checksum,
                'compressed': self.config.COMPRESSION_ENABLED,
                'encrypted': self.config.ENCRYPTION_ENABLED,
                'status': 'completed'
            }
            
            await self.backup_manager.save_metadata(backup_id, metadata)
            
            # Загрузка в S3
            if self.s3_storage:
                await self.s3_storage.upload_file(
                    str(backup_path),
                    f"backups/{backup_id}/{backup_path.name}"
                )
            
            logger.info(f"Полный бэкап создан успешно: {backup_id}")
            return backup_id
            
        except Exception as e:
            logger.error(f"Ошибка создания полного бэкапа: {e}", exc_info=True)
            await self.backup_manager.save_metadata(backup_id, {
                'backup_id': backup_id,
                'type': 'full',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'status': 'failed',
                'error': str(e)
            })
            raise
    
    async def create_incremental_backup(self) -> str:
        """
        Создание инкрементального бэкапа (WAL архивы).
        
        Returns:
            str: ID созданного бэкапа
            
        Raises:
            Exception: При ошибке создания бэкапа
        """
        if not self.config.WAL_ARCHIVE_ENABLED:
            raise ValueError("WAL архивирование не включено")
        
        backup_id = f"incremental_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        
        logger.info(f"Начало создания инкрементального бэкапа: {backup_id}")
        
        try:
            # Архивирование WAL файлов
            wal_files = await self._archive_wal_files()
            
            if not wal_files:
                logger.info("Нет новых WAL файлов для архивирования")
                return backup_id
            
            # Сжатие и шифрование WAL файлов
            for wal_file in wal_files:
                if self.config.COMPRESSION_ENABLED:
                    await self._compress_backup(Path(wal_file))
                if self.config.ENCRYPTION_ENABLED:
                    await self._encrypt_backup(Path(wal_file))
            
            # Сохранение метаданных
            metadata = {
                'backup_id': backup_id,
                'type': 'incremental',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'wal_files': len(wal_files),
                'status': 'completed'
            }
            
            await self.backup_manager.save_metadata(backup_id, metadata)
            
            # Загрузка в S3
            if self.s3_storage:
                for wal_file in wal_files:
                    await self.s3_storage.upload_file(
                        wal_file,
                        f"backups/{backup_id}/wal/{Path(wal_file).name}"
                    )
            
            logger.info(f"Инкрементальный бэкап создан успешно: {backup_id}")
            return backup_id
            
        except Exception as e:
            logger.error(f"Ошибка создания инкрементального бэкапа: {e}", exc_info=True)
            raise
    
    async def _create_pg_dump(self, output_path: Path) -> None:
        """
        Создание дампа PostgreSQL.
        
        Args:
            output_path: Путь для сохранения дампа
        """
        env = os.environ.copy()
        env['PGPASSWORD'] = self.config.DB_PASSWORD
        
        cmd = [
            'pg_dump',
            '-h', self.config.DB_HOST,
            '-p', str(self.config.DB_PORT),
            '-U', self.config.DB_USER,
            '-d', self.config.DB_NAME,
            '-F', 'c',  # Custom format
            '-f', str(output_path)
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"pg_dump failed: {stderr.decode()}")
    
    async def _compress_backup(self, backup_path: Path) -> Path:
        """
        Сжатие бэкапа с помощью gzip.
        
        Args:
            backup_path: Путь к файлу бэкапа
            
        Returns:
            Path: Путь к сжатому файлу
        """
        compressed_path = backup_path.with_suffix(backup_path.suffix + '.gz')
        
        def compress():
            with open(backup_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb', compresslevel=self.config.COMPRESSION_LEVEL) as f_out:
                    f_out.writelines(f_in)
            backup_path.unlink()  # Удаление несжатого файла
        
        await asyncio.to_thread(compress)
        logger.info(f"Бэкап сжат: {compressed_path}")
        return compressed_path
    
    async def _encrypt_backup(self, backup_path: Path) -> Path:
        """
        Шифрование бэкапа.
        
        Args:
            backup_path: Путь к файлу бэкапа
            
        Returns:
            Path: Путь к зашифрованному файлу
        """
        if not self.cipher:
            return backup_path
        
        encrypted_path = backup_path.with_suffix(backup_path.suffix + '.enc')
        
        def encrypt():
            with open(backup_path, 'rb') as f_in:
                data = f_in.read()
                encrypted_data = self.cipher.encrypt(data)
                with open(encrypted_path, 'wb') as f_out:
                    f_out.write(encrypted_data)
            backup_path.unlink()  # Удаление незашифрованного файла
        
        await asyncio.to_thread(encrypt)
        logger.info(f"Бэкап зашифрован: {encrypted_path}")
        return encrypted_path
    
    async def _calculate_checksum(self, file_path: Path) -> str:
        """
        Расчет контрольной суммы файла.
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            str: SHA256 хеш файла
        """
        def calculate():
            sha256_hash = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        
        return await asyncio.to_thread(calculate)
    
    async def _archive_wal_files(self) -> List[str]:
        """
        Архивирование WAL файлов.
        
        Returns:
            List[str]: Список путей к архивированным WAL файлам
        """
        # Получение списка WAL файлов для архивирования
        # В реальной реализации нужно использовать pg_receivewal или настроить archive_command
        wal_dir = Path(self.config.WAL_ARCHIVE_DIR)
        wal_files = list(wal_dir.glob('*.wal'))
        return [str(f) for f in wal_files]
    
    async def verify_backup(self, backup_id: str) -> bool:
        """
        Проверка целостности бэкапа.
        
        Args:
            backup_id: ID бэкапа
            
        Returns:
            bool: True если бэкап валиден
        """
        logger.info(f"Проверка целостности бэкапа: {backup_id}")
        
        try:
            metadata = await self.backup_manager.get_backup_info(backup_id)
            if not metadata:
                logger.error(f"Метаданные бэкапа не найдены: {backup_id}")
                return False
            
            # Проверка существования файла
            backup_files = list(Path(self.config.BACKUP_DIR).glob(f"{backup_id}*"))
            if not backup_files:
                logger.error(f"Файлы бэкапа не найдены: {backup_id}")
                return False
            
            # Проверка контрольной суммы
            if 'checksum' in metadata:
                current_checksum = await self._calculate_checksum(backup_files[0])
                if current_checksum != metadata['checksum']:
                    logger.error(f"Контрольная сумма не совпадает для бэкапа: {backup_id}")
                    return False
            
            logger.info(f"Бэкап валиден: {backup_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка проверки бэкапа: {e}", exc_info=True)
            return False
    
    async def cleanup_old_backups(self) -> None:
        """Удаление старых бэкапов согласно retention policy."""
        logger.info("Начало очистки старых бэкапов")
        
        try:
            from .retention_policy import RetentionPolicy
            retention = RetentionPolicy(self.config)
            await retention.apply_retention_policy()
            logger.info("Очистка старых бэкапов завершена")
            
        except Exception as e:
            logger.error(f"Ошибка очистки старых бэкапов: {e}", exc_info=True)
    
    async def schedule_backups(self) -> None:
        """Планирование автоматических бэкапов."""
        logger.info("Запуск планировщика бэкапов")
        
        # Планирование полных бэкапов (ежедневно в 2:00)
        asyncio.create_task(self._schedule_full_backups())
        
        # Планирование инкрементальных бэкапов (каждый час)
        if self.config.WAL_ARCHIVE_ENABLED:
            asyncio.create_task(self._schedule_incremental_backups())
    
    async def _schedule_full_backups(self) -> None:
        """Планирование полных бэкапов."""
        while True:
            try:
                # Расчет времени до следующего бэкапа (2:00 UTC)
                now = datetime.now(timezone.utc)
                next_backup = now.replace(hour=2, minute=0, second=0, microsecond=0)
                if now >= next_backup:
                    next_backup += timedelta(days=1)
                
                wait_seconds = (next_backup - now).total_seconds()
                logger.info(f"Следующий полный бэкап через {wait_seconds / 3600:.1f} часов")
                
                await asyncio.sleep(wait_seconds)
                
                # Создание бэкапа
                await self.create_full_backup()
                
                # Очистка старых бэкапов
                await self.cleanup_old_backups()
                
            except Exception as e:
                logger.error(f"Ошибка в планировщике полных бэкапов: {e}", exc_info=True)
                await asyncio.sleep(3600)  # Повтор через час при ошибке
    
    async def _schedule_incremental_backups(self) -> None:
        """Планирование инкрементальных бэкапов."""
        while True:
            try:
                # Ожидание до начала следующего часа
                now = datetime.now(timezone.utc)
                next_backup = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                wait_seconds = (next_backup - now).total_seconds()
                
                await asyncio.sleep(wait_seconds)
                
                # Создание инкрементального бэкапа
                await self.create_incremental_backup()
                
            except Exception as e:
                logger.error(f"Ошибка в планировщике инкрементальных бэкапов: {e}", exc_info=True)
                await asyncio.sleep(3600)  # Повтор через час при ошибке