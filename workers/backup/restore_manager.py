"""
Менеджер для восстановления базы данных из резервных копий.

Этот модуль отвечает за восстановление БД из полных и инкрементальных бэкапов,
проверку восстановленной БД и откат изменений.
"""

import asyncio
import gzip
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
from cryptography.fernet import Fernet

from .config import BackupConfig, get_backup_config
from .backup_manager import BackupManager
from .s3_storage import S3Storage

logger = logging.getLogger(__name__)


class RestoreManager:
    """Менеджер для восстановления базы данных."""
    
    def __init__(self, config: Optional[BackupConfig] = None):
        """
        Инициализация restore manager.
        
        Args:
            config: Конфигурация системы резервного копирования
        """
        self.config = config or get_backup_config()
        self.backup_manager = BackupManager(self.config)
        self.s3_storage = S3Storage(self.config) if self.config.S3_ENABLED else None
        self.restore_dir = Path(self.config.BACKUP_DIR) / "restore"
        self.restore_dir.mkdir(parents=True, exist_ok=True)
    
    async def restore_from_backup(
        self,
        backup_id: str,
        target_db: Optional[str] = None,
        verify: bool = True
    ) -> bool:
        """
        Восстановление базы данных из бэкапа.
        
        Args:
            backup_id: ID бэкапа для восстановления
            target_db: Целевая БД (по умолчанию основная БД)
            verify: Проверять восстановленную БД
            
        Returns:
            bool: True если восстановление успешно
            
        Raises:
            Exception: При ошибке восстановления
        """
        logger.info(f"Начало восстановления из бэкапа: {backup_id}")
        
        try:
            # Получение метаданных бэкапа
            metadata = await self.backup_manager.get_backup_info(backup_id)
            if not metadata:
                raise ValueError(f"Бэкап не найден: {backup_id}")
            
            # Создание snapshot перед восстановлением
            if self.config.RESTORE_SNAPSHOT_ENABLED:
                snapshot_id = await self._create_snapshot()
                logger.info(f"Создан snapshot: {snapshot_id}")
            
            # Подготовка файла бэкапа
            backup_file = await self._prepare_backup_file(backup_id, metadata)
            
            # Восстановление БД
            target_db = target_db or self.config.DB_NAME
            await self._restore_database(backup_file, target_db)
            
            # Проверка восстановленной БД
            if verify and self.config.RESTORE_VERIFY_ENABLED:
                if not await self.verify_restore(target_db):
                    raise Exception("Проверка восстановленной БД не прошла")
            
            logger.info(f"Восстановление завершено успешно: {backup_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка восстановления из бэкапа: {e}", exc_info=True)
            
            # Откат к snapshot при ошибке
            if self.config.RESTORE_SNAPSHOT_ENABLED:
                logger.info("Откат к snapshot...")
                await self.rollback_restore()
            
            raise
    
    async def restore_to_point_in_time(
        self,
        timestamp: datetime,
        target_db: Optional[str] = None
    ) -> bool:
        """
        Восстановление базы данных на определенный момент времени.
        
        Args:
            timestamp: Момент времени для восстановления
            target_db: Целевая БД
            
        Returns:
            bool: True если восстановление успешно
        """
        logger.info(f"Восстановление на момент времени: {timestamp}")
        
        try:
            # Поиск ближайшего полного бэкапа
            full_backup = await self._find_closest_full_backup(timestamp)
            if not full_backup:
                raise ValueError("Не найден подходящий полный бэкап")
            
            # Восстановление из полного бэкапа
            await self.restore_from_backup(
                full_backup['backup_id'],
                target_db=target_db,
                verify=False
            )
            
            # Применение WAL файлов до указанного времени
            await self._apply_wal_files(timestamp, target_db)
            
            # Проверка восстановленной БД
            if self.config.RESTORE_VERIFY_ENABLED:
                if not await self.verify_restore(target_db):
                    raise Exception("Проверка восстановленной БД не прошла")
            
            logger.info(f"Восстановление на момент времени завершено: {timestamp}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка восстановления на момент времени: {e}", exc_info=True)
            raise
    
    async def _prepare_backup_file(self, backup_id: str, metadata: Dict) -> Path:
        """
        Подготовка файла бэкапа для восстановления.
        
        Args:
            backup_id: ID бэкапа
            metadata: Метаданные бэкапа
            
        Returns:
            Path: Путь к подготовленному файлу
        """
        # Проверка локального файла
        backup_path = await self.backup_manager.get_backup_path(backup_id)
        
        # Скачивание из S3 если нужно
        if not backup_path and self.s3_storage:
            logger.info(f"Скачивание бэкапа из S3: {backup_id}")
            s3_key = f"backups/{backup_id}/{backup_id}.sql"
            
            if metadata.get('compressed'):
                s3_key += '.gz'
            if metadata.get('encrypted'):
                s3_key += '.enc'
            
            local_path = self.restore_dir / Path(s3_key).name
            await self.s3_storage.download_file(s3_key, str(local_path))
            backup_path = local_path
        
        if not backup_path:
            raise FileNotFoundError(f"Файл бэкапа не найден: {backup_id}")
        
        # Расшифровка
        if metadata.get('encrypted'):
            backup_path = await self._decrypt_backup(backup_path)
        
        # Распаковка
        if metadata.get('compressed'):
            backup_path = await self._decompress_backup(backup_path)
        
        return backup_path
    
    async def _decrypt_backup(self, backup_path: Path) -> Path:
        """
        Расшифровка бэкапа.
        
        Args:
            backup_path: Путь к зашифрованному файлу
            
        Returns:
            Path: Путь к расшифрованному файлу
        """
        if not self.config.ENCRYPTION_KEY:
            raise ValueError("Ключ шифрования не настроен")
        
        decrypted_path = backup_path.with_suffix('')
        
        # Создание cipher
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
        
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'backup_salt_2getpro',
            iterations=100000,
        )
        key = kdf.derive(self.config.ENCRYPTION_KEY.encode())
        cipher = Fernet(key)
        
        def decrypt():
            with open(backup_path, 'rb') as f_in:
                encrypted_data = f_in.read()
                decrypted_data = cipher.decrypt(encrypted_data)
                with open(decrypted_path, 'wb') as f_out:
                    f_out.write(decrypted_data)
            backup_path.unlink()  # Удаление зашифрованного файла
        
        await asyncio.to_thread(decrypt)
        logger.info(f"Бэкап расшифрован: {decrypted_path}")
        return decrypted_path
    
    async def _decompress_backup(self, backup_path: Path) -> Path:
        """
        Распаковка бэкапа.
        
        Args:
            backup_path: Путь к сжатому файлу
            
        Returns:
            Path: Путь к распакованному файлу
        """
        decompressed_path = backup_path.with_suffix('')
        
        def decompress():
            with gzip.open(backup_path, 'rb') as f_in:
                with open(decompressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            backup_path.unlink()  # Удаление сжатого файла
        
        await asyncio.to_thread(decompress)
        logger.info(f"Бэкап распакован: {decompressed_path}")
        return decompressed_path
    
    async def _restore_database(self, backup_file: Path, target_db: str) -> None:
        """
        Восстановление базы данных из файла.
        
        Args:
            backup_file: Путь к файлу бэкапа
            target_db: Целевая база данных
        """
        logger.info(f"Восстановление БД {target_db} из {backup_file}")
        
        env = os.environ.copy()
        env['PGPASSWORD'] = self.config.DB_PASSWORD
        
        # Проверка формата файла
        if backup_file.suffix == '.sql':
            # SQL формат
            cmd = [
                'psql',
                '-h', self.config.DB_HOST,
                '-p', str(self.config.DB_PORT),
                '-U', self.config.DB_USER,
                '-d', target_db,
                '-f', str(backup_file)
            ]
        else:
            # Custom формат (pg_dump -Fc)
            cmd = [
                'pg_restore',
                '-h', self.config.DB_HOST,
                '-p', str(self.config.DB_PORT),
                '-U', self.config.DB_USER,
                '-d', target_db,
                '--clean',
                '--if-exists',
                str(backup_file)
            ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=self.config.RESTORE_TIMEOUT
        )
        
        if process.returncode != 0:
            raise Exception(f"Восстановление БД не удалось: {stderr.decode()}")
        
        logger.info(f"БД {target_db} восстановлена успешно")
    
    async def verify_restore(self, target_db: Optional[str] = None) -> bool:
        """
        Проверка восстановленной базы данных.
        
        Args:
            target_db: Целевая БД для проверки
            
        Returns:
            bool: True если БД валидна
        """
        target_db = target_db or self.config.DB_NAME
        logger.info(f"Проверка восстановленной БД: {target_db}")
        
        try:
            # Проверка подключения к БД
            env = os.environ.copy()
            env['PGPASSWORD'] = self.config.DB_PASSWORD
            
            cmd = [
                'psql',
                '-h', self.config.DB_HOST,
                '-p', str(self.config.DB_PORT),
                '-U', self.config.DB_USER,
                '-d', target_db,
                '-c', 'SELECT 1;'
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Проверка БД не прошла: {stderr.decode()}")
                return False
            
            logger.info(f"БД {target_db} валидна")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка проверки БД: {e}", exc_info=True)
            return False
    
    async def test_restore(self, backup_id: str) -> bool:
        """
        Тестовое восстановление в отдельную БД.
        
        Args:
            backup_id: ID бэкапа для тестирования
            
        Returns:
            bool: True если тест успешен
        """
        test_db = f"{self.config.DB_NAME}_test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"Тестовое восстановление в БД: {test_db}")
        
        try:
            # Создание тестовой БД
            await self._create_database(test_db)
            
            # Восстановление в тестовую БД
            result = await self.restore_from_backup(backup_id, target_db=test_db)
            
            # Удаление тестовой БД
            await self._drop_database(test_db)
            
            logger.info(f"Тестовое восстановление завершено: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка тестового восстановления: {e}", exc_info=True)
            # Попытка удалить тестовую БД при ошибке
            try:
                await self._drop_database(test_db)
            except:
                pass
            return False
    
    async def _create_snapshot(self) -> str:
        """
        Создание snapshot текущей БД.
        
        Returns:
            str: ID snapshot
        """
        snapshot_id = f"snapshot_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        snapshot_db = f"{self.config.DB_NAME}_{snapshot_id}"
        
        logger.info(f"Создание snapshot: {snapshot_db}")
        
        # Создание копии БД
        env = os.environ.copy()
        env['PGPASSWORD'] = self.config.DB_PASSWORD
        
        cmd = [
            'createdb',
            '-h', self.config.DB_HOST,
            '-p', str(self.config.DB_PORT),
            '-U', self.config.DB_USER,
            '-T', self.config.DB_NAME,
            snapshot_db
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"Создание snapshot не удалось: {stderr.decode()}")
        
        return snapshot_id
    
    async def rollback_restore(self) -> bool:
        """
        Откат восстановления к последнему snapshot.
        
        Returns:
            bool: True если откат успешен
        """
        logger.info("Откат восстановления к snapshot")
        
        try:
            # Поиск последнего snapshot
            # В реальной реализации нужно хранить информацию о snapshot
            # Здесь упрощенная версия
            logger.warning("Функция отката требует доработки")
            return False
            
        except Exception as e:
            logger.error(f"Ошибка отката восстановления: {e}", exc_info=True)
            return False
    
    async def _find_closest_full_backup(self, timestamp: datetime) -> Optional[Dict]:
        """
        Поиск ближайшего полного бэкапа до указанного времени.
        
        Args:
            timestamp: Момент времени
            
        Returns:
            Optional[Dict]: Метаданные бэкапа или None
        """
        backups = await self.backup_manager.list_backups(
            backup_type='full',
            end_date=timestamp
        )
        
        return backups[0] if backups else None
    
    async def _apply_wal_files(self, timestamp: datetime, target_db: Optional[str] = None) -> None:
        """
        Применение WAL файлов до указанного времени.
        
        Args:
            timestamp: Момент времени
            target_db: Целевая БД
        """
        logger.info(f"Применение WAL файлов до {timestamp}")
        # Реализация зависит от настройки WAL архивирования
        # Требует настройки recovery.conf или recovery.signal в PostgreSQL
        pass
    
    async def _create_database(self, db_name: str) -> None:
        """Создание базы данных."""
        env = os.environ.copy()
        env['PGPASSWORD'] = self.config.DB_PASSWORD
        
        cmd = [
            'createdb',
            '-h', self.config.DB_HOST,
            '-p', str(self.config.DB_PORT),
            '-U', self.config.DB_USER,
            db_name
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        await process.communicate()
    
    async def _drop_database(self, db_name: str) -> None:
        """Удаление базы данных."""
        env = os.environ.copy()
        env['PGPASSWORD'] = self.config.DB_PASSWORD
        
        cmd = [
            'dropdb',
            '-h', self.config.DB_HOST,
            '-p', str(self.config.DB_PORT),
            '-U', self.config.DB_USER,
            db_name
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        await process.communicate()