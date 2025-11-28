"""
Модуль для работы с S3/MinIO хранилищем.

Этот модуль отвечает за загрузку, скачивание и управление
файлами бэкапов в S3-совместимом хранилище.
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from .config import BackupConfig, get_backup_config

logger = logging.getLogger(__name__)


class S3Storage:
    """Класс для работы с S3/MinIO хранилищем."""
    
    def __init__(self, config: Optional[BackupConfig] = None):
        """
        Инициализация S3 storage.
        
        Args:
            config: Конфигурация системы резервного копирования
        """
        self.config = config or get_backup_config()
        
        if not self.config.S3_ENABLED:
            raise ValueError("S3 хранилище не включено в конфигурации")
        
        # Настройка boto3 клиента
        self.s3_config = Config(
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'
            },
            max_pool_connections=self.config.MAX_PARALLEL_UPLOADS
        )
        
        self.s3_client = boto3.client(
            's3',
            endpoint_url=self.config.S3_ENDPOINT,
            aws_access_key_id=self.config.S3_ACCESS_KEY,
            aws_secret_access_key=self.config.S3_SECRET_KEY,
            region_name=self.config.S3_REGION,
            use_ssl=self.config.S3_USE_SSL,
            config=self.s3_config
        )
        
        # Проверка и создание bucket
        asyncio.create_task(self._ensure_bucket_exists())
    
    async def _ensure_bucket_exists(self) -> None:
        """Проверка существования bucket и создание при необходимости."""
        try:
            await asyncio.to_thread(
                self.s3_client.head_bucket,
                Bucket=self.config.S3_BUCKET
            )
            logger.info(f"S3 bucket существует: {self.config.S3_BUCKET}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                logger.info(f"Создание S3 bucket: {self.config.S3_BUCKET}")
                await asyncio.to_thread(
                    self.s3_client.create_bucket,
                    Bucket=self.config.S3_BUCKET
                )
            else:
                logger.error(f"Ошибка проверки S3 bucket: {e}")
    
    async def upload_file(
        self,
        local_path: str,
        s3_key: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Загрузка файла в S3.
        
        Args:
            local_path: Локальный путь к файлу
            s3_key: Ключ в S3
            metadata: Дополнительные метаданные
            
        Returns:
            bool: True если загрузка успешна
        """
        logger.info(f"Загрузка файла в S3: {local_path} -> {s3_key}")
        
        try:
            file_size = Path(local_path).stat().st_size
            
            # Использование multipart upload для больших файлов
            if file_size > self.config.MULTIPART_THRESHOLD:
                await self._multipart_upload(local_path, s3_key, metadata)
            else:
                await self._simple_upload(local_path, s3_key, metadata)
            
            logger.info(f"Файл загружен в S3: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка загрузки файла в S3: {e}", exc_info=True)
            return False
    
    async def _simple_upload(
        self,
        local_path: str,
        s3_key: str,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Простая загрузка файла.
        
        Args:
            local_path: Локальный путь к файлу
            s3_key: Ключ в S3
            metadata: Метаданные
        """
        extra_args = {}
        if metadata:
            extra_args['Metadata'] = metadata
        
        await asyncio.to_thread(
            self.s3_client.upload_file,
            local_path,
            self.config.S3_BUCKET,
            s3_key,
            ExtraArgs=extra_args
        )
    
    async def _multipart_upload(
        self,
        local_path: str,
        s3_key: str,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Multipart загрузка файла.
        
        Args:
            local_path: Локальный путь к файлу
            s3_key: Ключ в S3
            metadata: Метаданные
        """
        logger.info(f"Использование multipart upload для {s3_key}")
        
        # Инициализация multipart upload
        extra_args = {}
        if metadata:
            extra_args['Metadata'] = metadata
        
        response = await asyncio.to_thread(
            self.s3_client.create_multipart_upload,
            Bucket=self.config.S3_BUCKET,
            Key=s3_key,
            **extra_args
        )
        
        upload_id = response['UploadId']
        parts = []
        
        try:
            # Загрузка частей
            with open(local_path, 'rb') as f:
                part_number = 1
                while True:
                    data = f.read(self.config.MULTIPART_CHUNKSIZE)
                    if not data:
                        break
                    
                    part_response = await asyncio.to_thread(
                        self.s3_client.upload_part,
                        Bucket=self.config.S3_BUCKET,
                        Key=s3_key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=data
                    )
                    
                    parts.append({
                        'PartNumber': part_number,
                        'ETag': part_response['ETag']
                    })
                    
                    part_number += 1
                    logger.debug(f"Загружена часть {part_number - 1} для {s3_key}")
            
            # Завершение multipart upload
            await asyncio.to_thread(
                self.s3_client.complete_multipart_upload,
                Bucket=self.config.S3_BUCKET,
                Key=s3_key,
                UploadId=upload_id,
                MultipartUpload={'Parts': parts}
            )
            
        except Exception as e:
            # Отмена multipart upload при ошибке
            logger.error(f"Ошибка multipart upload, отмена: {e}")
            await asyncio.to_thread(
                self.s3_client.abort_multipart_upload,
                Bucket=self.config.S3_BUCKET,
                Key=s3_key,
                UploadId=upload_id
            )
            raise
    
    async def download_file(self, s3_key: str, local_path: str) -> bool:
        """
        Скачивание файла из S3.
        
        Args:
            s3_key: Ключ в S3
            local_path: Локальный путь для сохранения
            
        Returns:
            bool: True если скачивание успешно
        """
        logger.info(f"Скачивание файла из S3: {s3_key} -> {local_path}")
        
        try:
            # Создание директории если нужно
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            
            await asyncio.to_thread(
                self.s3_client.download_file,
                self.config.S3_BUCKET,
                s3_key,
                local_path
            )
            
            logger.info(f"Файл скачан из S3: {local_path}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка скачивания файла из S3: {e}", exc_info=True)
            return False
    
    async def delete_file(self, s3_key: str) -> bool:
        """
        Удаление файла из S3.
        
        Args:
            s3_key: Ключ в S3
            
        Returns:
            bool: True если удаление успешно
        """
        logger.info(f"Удаление файла из S3: {s3_key}")
        
        try:
            await asyncio.to_thread(
                self.s3_client.delete_object,
                Bucket=self.config.S3_BUCKET,
                Key=s3_key
            )
            
            logger.info(f"Файл удален из S3: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка удаления файла из S3: {e}", exc_info=True)
            return False
    
    async def list_files(self, prefix: str = "") -> List[Dict]:
        """
        Получение списка файлов в S3.
        
        Args:
            prefix: Префикс для фильтрации
            
        Returns:
            List[Dict]: Список файлов с метаданными
        """
        logger.debug(f"Получение списка файлов из S3 с префиксом: {prefix}")
        
        try:
            files = []
            paginator = self.s3_client.get_paginator('list_objects_v2')
            
            async def list_pages():
                for page in paginator.paginate(
                    Bucket=self.config.S3_BUCKET,
                    Prefix=prefix
                ):
                    if 'Contents' in page:
                        for obj in page['Contents']:
                            files.append({
                                'key': obj['Key'],
                                'size': obj['Size'],
                                'last_modified': obj['LastModified'].isoformat(),
                                'etag': obj['ETag']
                            })
            
            await asyncio.to_thread(list_pages)
            
            logger.debug(f"Найдено файлов в S3: {len(files)}")
            return files
            
        except Exception as e:
            logger.error(f"Ошибка получения списка файлов из S3: {e}", exc_info=True)
            return []
    
    async def get_file_metadata(self, s3_key: str) -> Optional[Dict]:
        """
        Получение метаданных файла.
        
        Args:
            s3_key: Ключ в S3
            
        Returns:
            Optional[Dict]: Метаданные файла или None
        """
        logger.debug(f"Получение метаданных файла из S3: {s3_key}")
        
        try:
            response = await asyncio.to_thread(
                self.s3_client.head_object,
                Bucket=self.config.S3_BUCKET,
                Key=s3_key
            )
            
            metadata = {
                'size': response['ContentLength'],
                'last_modified': response['LastModified'].isoformat(),
                'etag': response['ETag'],
                'content_type': response.get('ContentType'),
                'metadata': response.get('Metadata', {})
            }
            
            return metadata
            
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                logger.warning(f"Файл не найден в S3: {s3_key}")
            else:
                logger.error(f"Ошибка получения метаданных из S3: {e}")
            return None
    
    async def file_exists(self, s3_key: str) -> bool:
        """
        Проверка существования файла в S3.
        
        Args:
            s3_key: Ключ в S3
            
        Returns:
            bool: True если файл существует
        """
        try:
            await asyncio.to_thread(
                self.s3_client.head_object,
                Bucket=self.config.S3_BUCKET,
                Key=s3_key
            )
            return True
        except ClientError:
            return False
    
    async def copy_file(self, source_key: str, dest_key: str) -> bool:
        """
        Копирование файла в S3.
        
        Args:
            source_key: Исходный ключ
            dest_key: Целевой ключ
            
        Returns:
            bool: True если копирование успешно
        """
        logger.info(f"Копирование файла в S3: {source_key} -> {dest_key}")
        
        try:
            copy_source = {
                'Bucket': self.config.S3_BUCKET,
                'Key': source_key
            }
            
            await asyncio.to_thread(
                self.s3_client.copy_object,
                CopySource=copy_source,
                Bucket=self.config.S3_BUCKET,
                Key=dest_key
            )
            
            logger.info(f"Файл скопирован в S3: {dest_key}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка копирования файла в S3: {e}", exc_info=True)
            return False
    
    async def get_bucket_size(self) -> int:
        """
        Получение общего размера bucket.
        
        Returns:
            int: Размер в байтах
        """
        try:
            files = await self.list_files()
            total_size = sum(f['size'] for f in files)
            return total_size
        except Exception as e:
            logger.error(f"Ошибка получения размера bucket: {e}")
            return 0
    
    async def cleanup_old_files(self, prefix: str, days: int) -> int:
        """
        Удаление старых файлов из S3.
        
        Args:
            prefix: Префикс для фильтрации
            days: Количество дней для хранения
            
        Returns:
            int: Количество удаленных файлов
        """
        from datetime import datetime, timedelta, timezone
        
        logger.info(f"Очистка старых файлов в S3 (старше {days} дней)")
        
        try:
            files = await self.list_files(prefix)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            deleted_count = 0
            
            for file_info in files:
                file_date = datetime.fromisoformat(file_info['last_modified'].replace('Z', '+00:00'))
                if file_date < cutoff_date:
                    if await self.delete_file(file_info['key']):
                        deleted_count += 1
            
            logger.info(f"Удалено старых файлов из S3: {deleted_count}")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Ошибка очистки старых файлов из S3: {e}", exc_info=True)
            return 0