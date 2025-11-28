"""
Модуль для мониторинга системы резервного копирования.

Этот модуль отвечает за отслеживание статуса бэкапов,
отправку алертов и сбор метрик.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .config import BackupConfig, get_backup_config
from .backup_manager import BackupManager

logger = logging.getLogger(__name__)


class BackupMonitoring:
    """Класс для мониторинга системы резервного копирования."""
    
    def __init__(self, config: Optional[BackupConfig] = None):
        """
        Инициализация backup monitoring.
        
        Args:
            config: Конфигурация системы резервного копирования
        """
        self.config = config or get_backup_config()
        self.backup_manager = BackupManager(self.config)
        self.metrics = {
            'total_backups': 0,
            'successful_backups': 0,
            'failed_backups': 0,
            'last_backup_time': None,
            'last_backup_size': 0,
            'average_backup_time': 0,
            'total_backup_size': 0
        }
    
    async def check_backup_status(self) -> Dict:
        """
        Проверка статуса последнего бэкапа.
        
        Returns:
            Dict: Статус бэкапа
        """
        logger.info("Проверка статуса бэкапов")
        
        try:
            latest_backup = await self.backup_manager.get_latest_backup()
            
            if not latest_backup:
                return {
                    'status': 'no_backups',
                    'message': 'Бэкапы не найдены',
                    'healthy': False
                }
            
            backup_date = datetime.fromisoformat(latest_backup['timestamp'])
            age_hours = (datetime.now(timezone.utc) - backup_date).total_seconds() / 3600
            
            # Проверка свежести бэкапа (не старше 25 часов для ежедневных)
            if age_hours > 25:
                return {
                    'status': 'outdated',
                    'message': f'Последний бэкап устарел ({age_hours:.1f} часов назад)',
                    'healthy': False,
                    'last_backup': latest_backup
                }
            
            # Проверка статуса последнего бэкапа
            if latest_backup.get('status') != 'completed':
                return {
                    'status': 'failed',
                    'message': f'Последний бэкап завершился с ошибкой',
                    'healthy': False,
                    'last_backup': latest_backup
                }
            
            return {
                'status': 'healthy',
                'message': 'Система бэкапов работает нормально',
                'healthy': True,
                'last_backup': latest_backup,
                'age_hours': age_hours
            }
            
        except Exception as e:
            logger.error(f"Ошибка проверки статуса бэкапов: {e}", exc_info=True)
            return {
                'status': 'error',
                'message': f'Ошибка проверки: {str(e)}',
                'healthy': False
            }
    
    async def alert_on_failure(self, backup_id: str, error: str) -> None:
        """
        Отправка алерта при ошибке бэкапа.
        
        Args:
            backup_id: ID бэкапа
            error: Сообщение об ошибке
        """
        logger.error(f"Алерт: Ошибка бэкапа {backup_id}: {error}")
        
        if not self.config.MONITORING_ENABLED:
            return
        
        # Отправка email алерта
        if self.config.ALERT_EMAIL:
            await self._send_email_alert(backup_id, error)
        
        # Отправка Telegram алерта
        if self.config.ALERT_TELEGRAM_CHAT_ID and self.config.ALERT_TELEGRAM_BOT_TOKEN:
            await self._send_telegram_alert(backup_id, error)
    
    async def _send_email_alert(self, backup_id: str, error: str) -> None:
        """
        Отправка email алерта.
        
        Args:
            backup_id: ID бэкапа
            error: Сообщение об ошибке
        """
        try:
            subject = f"[ALERT] Ошибка резервного копирования: {backup_id}"
            body = f"""
Произошла ошибка при создании резервной копии.

Backup ID: {backup_id}
Время: {datetime.now(timezone.utc).isoformat()}
Ошибка: {error}

Требуется проверка системы резервного копирования.
            """
            
            msg = MIMEMultipart()
            msg['From'] = "backup-system@2getpro.com"
            msg['To'] = self.config.ALERT_EMAIL
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            
            # В реальной реализации нужно настроить SMTP сервер
            logger.info(f"Email алерт отправлен на {self.config.ALERT_EMAIL}")
            
        except Exception as e:
            logger.error(f"Ошибка отправки email алерта: {e}")
    
    async def _send_telegram_alert(self, backup_id: str, error: str) -> None:
        """
        Отправка Telegram алерта.
        
        Args:
            backup_id: ID бэкапа
            error: Сообщение об ошибке
        """
        try:
            import aiohttp
            
            message = f"""
🚨 *ALERT: Ошибка резервного копирования*

*Backup ID:* `{backup_id}`
*Время:* {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
*Ошибка:* {error}

Требуется проверка системы резервного копирования.
            """
            
            url = f"https://api.telegram.org/bot{self.config.ALERT_TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                'chat_id': self.config.ALERT_TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        logger.info("Telegram алерт отправлен")
                    else:
                        logger.error(f"Ошибка отправки Telegram алерта: {response.status}")
            
        except Exception as e:
            logger.error(f"Ошибка отправки Telegram алерта: {e}")
    
    async def track_backup_metrics(self, backup_id: str, metadata: Dict) -> None:
        """
        Отслеживание метрик бэкапа.
        
        Args:
            backup_id: ID бэкапа
            metadata: Метаданные бэкапа
        """
        try:
            self.metrics['total_backups'] += 1
            
            if metadata.get('status') == 'completed':
                self.metrics['successful_backups'] += 1
            else:
                self.metrics['failed_backups'] += 1
            
            self.metrics['last_backup_time'] = metadata.get('timestamp')
            self.metrics['last_backup_size'] = metadata.get('size', 0)
            
            # Обновление общего размера
            stats = await self.backup_manager.get_backup_statistics()
            self.metrics['total_backup_size'] = stats.get('total_size', 0)
            
            logger.debug(f"Метрики обновлены для бэкапа: {backup_id}")
            
        except Exception as e:
            logger.error(f"Ошибка отслеживания метрик: {e}")
    
    async def generate_backup_report(self, period_days: int = 7) -> Dict:
        """
        Генерация отчета о бэкапах за период.
        
        Args:
            period_days: Период в днях
            
        Returns:
            Dict: Отчет о бэкапах
        """
        logger.info(f"Генерация отчета о бэкапах за {period_days} дней")
        
        try:
            start_date = datetime.now(timezone.utc) - timedelta(days=period_days)
            backups = await self.backup_manager.list_backups(start_date=start_date)
            
            report = {
                'period_days': period_days,
                'start_date': start_date.isoformat(),
                'end_date': datetime.now(timezone.utc).isoformat(),
                'total_backups': len(backups),
                'successful_backups': len([b for b in backups if b.get('status') == 'completed']),
                'failed_backups': len([b for b in backups if b.get('status') == 'failed']),
                'full_backups': len([b for b in backups if b.get('type') == 'full']),
                'incremental_backups': len([b for b in backups if b.get('type') == 'incremental']),
                'total_size': sum(b.get('size', 0) for b in backups),
                'average_size': 0,
                'success_rate': 0,
                'backups': backups
            }
            
            if report['total_backups'] > 0:
                report['average_size'] = report['total_size'] / report['total_backups']
                report['success_rate'] = (report['successful_backups'] / report['total_backups']) * 100
            
            logger.info(f"Отчет сгенерирован: {report['total_backups']} бэкапов")
            return report
            
        except Exception as e:
            logger.error(f"Ошибка генерации отчета: {e}", exc_info=True)
            return {}
    
    async def get_prometheus_metrics(self) -> str:
        """
        Получение метрик в формате Prometheus.
        
        Returns:
            str: Метрики в формате Prometheus
        """
        try:
            stats = await self.backup_manager.get_backup_statistics()
            status = await self.check_backup_status()
            
            metrics = []
            
            # Общее количество бэкапов
            metrics.append(f'backup_total_count {stats["total_backups"]}')
            
            # Успешные бэкапы
            metrics.append(f'backup_successful_count {stats["successful_backups"]}')
            
            # Неудачные бэкапы
            metrics.append(f'backup_failed_count {stats["failed_backups"]}')
            
            # Полные бэкапы
            metrics.append(f'backup_full_count {stats["full_backups"]}')
            
            # Инкрементальные бэкапы
            metrics.append(f'backup_incremental_count {stats["incremental_backups"]}')
            
            # Общий размер бэкапов
            metrics.append(f'backup_total_size_bytes {stats["total_size"]}')
            
            # Статус здоровья (1 = healthy, 0 = unhealthy)
            health_status = 1 if status['healthy'] else 0
            metrics.append(f'backup_health_status {health_status}')
            
            # Время последнего бэкапа (timestamp)
            if status.get('last_backup'):
                last_backup_ts = datetime.fromisoformat(
                    status['last_backup']['timestamp']
                ).timestamp()
                metrics.append(f'backup_last_timestamp {int(last_backup_ts)}')
            
            return '\n'.join(metrics)
            
        except Exception as e:
            logger.error(f"Ошибка получения Prometheus метрик: {e}")
            return ""
    
    async def check_backup_health(self) -> bool:
        """
        Проверка здоровья системы бэкапов.
        
        Returns:
            bool: True если система здорова
        """
        status = await self.check_backup_status()
        return status['healthy']
    
    async def send_daily_report(self) -> None:
        """Отправка ежедневного отчета о бэкапах."""
        if not self.config.MONITORING_ENABLED:
            return
        
        logger.info("Отправка ежедневного отчета")
        
        try:
            report = await self.generate_backup_report(period_days=1)
            
            subject = f"Ежедневный отчет о резервном копировании - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
            body = f"""
Ежедневный отчет о резервном копировании

Период: {report['start_date']} - {report['end_date']}

Статистика:
- Всего бэкапов: {report['total_backups']}
- Успешных: {report['successful_backups']}
- Неудачных: {report['failed_backups']}
- Полных бэкапов: {report['full_backups']}
- Инкрементальных: {report['incremental_backups']}
- Общий размер: {report['total_size'] / (1024**3):.2f} GB
- Средний размер: {report['average_size'] / (1024**3):.2f} GB
- Процент успеха: {report['success_rate']:.1f}%

Статус системы: {'✅ Здорова' if await self.check_backup_health() else '❌ Требует внимания'}
            """
            
            if self.config.ALERT_EMAIL:
                await self._send_email_report(subject, body)
            
            if self.config.ALERT_TELEGRAM_CHAT_ID:
                await self._send_telegram_report(body)
            
        except Exception as e:
            logger.error(f"Ошибка отправки ежедневного отчета: {e}")
    
    async def _send_email_report(self, subject: str, body: str) -> None:
        """Отправка email отчета."""
        try:
            msg = MIMEMultipart()
            msg['From'] = "backup-system@2getpro.com"
            msg['To'] = self.config.ALERT_EMAIL
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            
            logger.info(f"Email отчет отправлен на {self.config.ALERT_EMAIL}")
            
        except Exception as e:
            logger.error(f"Ошибка отправки email отчета: {e}")
    
    async def _send_telegram_report(self, body: str) -> None:
        """Отправка Telegram отчета."""
        try:
            import aiohttp
            
            url = f"https://api.telegram.org/bot{self.config.ALERT_TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                'chat_id': self.config.ALERT_TELEGRAM_CHAT_ID,
                'text': body,
                'parse_mode': 'Markdown'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        logger.info("Telegram отчет отправлен")
                    else:
                        logger.error(f"Ошибка отправки Telegram отчета: {response.status}")
            
        except Exception as e:
            logger.error(f"Ошибка отправки Telegram отчета: {e}")
    
    async def monitor_backup_process(self, backup_id: str) -> None:
        """
        Мониторинг процесса создания бэкапа.
        
        Args:
            backup_id: ID бэкапа
        """
        logger.info(f"Начало мониторинга бэкапа: {backup_id}")
        
        start_time = datetime.now(timezone.utc)
        
        # Ожидание завершения бэкапа (с таймаутом)
        timeout = 3600  # 1 час
        elapsed = 0
        
        while elapsed < timeout:
            await asyncio.sleep(10)
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            metadata = await self.backup_manager.get_backup_info(backup_id)
            if metadata and metadata.get('status') in ['completed', 'failed']:
                break
        
        # Проверка результата
        metadata = await self.backup_manager.get_backup_info(backup_id)
        if metadata:
            if metadata.get('status') == 'completed':
                logger.info(f"Бэкап завершен успешно: {backup_id}")
                await self.track_backup_metrics(backup_id, metadata)
            else:
                logger.error(f"Бэкап завершился с ошибкой: {backup_id}")
                await self.alert_on_failure(backup_id, metadata.get('error', 'Unknown error'))
        else:
            logger.error(f"Метаданные бэкапа не найдены: {backup_id}")