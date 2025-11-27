#!/bin/bash
################################################################################
# Docker-based установщик 2GETPRO v2 для Ubuntu 24.04 LTS
# Версия: 1.0
# Автор: 2GETPRO Team
################################################################################

set -e  # Прервать выполнение при ошибке

################################################################################
# ЦВЕТНОЙ ВЫВОД
################################################################################

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Символы для статусов
CHECK_MARK="${GREEN}✓${NC}"
CROSS_MARK="${RED}✗${NC}"
INFO_MARK="${BLUE}ℹ${NC}"
WARN_MARK="${YELLOW}⚠${NC}"

################################################################################
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="/opt/2getpro-v2"
LOG_FILE="/var/log/2getpro-docker-install.log"
ENV_FILE=".env"
BACKUP_DIR="/opt/2getpro-backups"
DOCKER_COMPOSE_FILE="docker-compose.yml"

# Флаги режима работы
SILENT_MODE=false
SKIP_CONFIRMATIONS=false
DRY_RUN=false

# Собранные данные конфигурации
declare -A CONFIG

################################################################################
# ФУНКЦИИ ЛОГИРОВАНИЯ
################################################################################

log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
}

print_header() {
    echo -e "\n${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${WHITE}$1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}\n"
}

print_step() {
    echo -e "${BLUE}▶${NC} $1"
    log "INFO" "$1"
}

print_success() {
    echo -e "${CHECK_MARK} ${GREEN}$1${NC}"
    log "SUCCESS" "$1"
}

print_error() {
    echo -e "${CROSS_MARK} ${RED}$1${NC}"
    log "ERROR" "$1"
}

print_warning() {
    echo -e "${WARN_MARK} ${YELLOW}$1${NC}"
    log "WARNING" "$1"
}

print_info() {
    echo -e "${INFO_MARK} ${CYAN}$1${NC}"
    log "INFO" "$1"
}

################################################################################
# ФУНКЦИИ ПРОВЕРКИ СИСТЕМЫ
################################################################################

check_root() {
    print_step "Проверка прав суперпользователя..."
    if [[ $EUID -ne 0 ]]; then
        print_error "Этот скрипт должен быть запущен с правами root"
        print_info "Используйте: sudo $0"
        exit 1
    fi
    print_success "Права root подтверждены"
}

check_ubuntu_version() {
    print_step "Проверка версии Ubuntu..."
    
    if [[ ! -f /etc/os-release ]]; then
        print_error "Не удалось определить версию ОС"
        exit 1
    fi
    
    source /etc/os-release
    
    if [[ "$ID" != "ubuntu" ]]; then
        print_error "Этот скрипт предназначен только для Ubuntu"
        print_info "Обнаружена ОС: $ID"
        exit 1
    fi
    
    # Проверяем версию Ubuntu (24.04)
    if [[ "$VERSION_ID" != "24.04" ]]; then
        print_warning "Рекомендуется Ubuntu 24.04 LTS"
        print_info "Обнаружена версия: $VERSION_ID"
        
        if [[ "$SKIP_CONFIRMATIONS" == false ]]; then
            read -p "Продолжить установку? (y/n): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    fi
    
    print_success "Ubuntu $VERSION_ID обнаружена"
}

check_system_requirements() {
    print_step "Проверка системных требований..."
    
    # Проверка RAM (минимум 4GB для Docker)
    local total_ram=$(free -g | awk '/^Mem:/{print $2}')
    if [[ $total_ram -lt 4 ]]; then
        print_error "Недостаточно RAM: ${total_ram}GB (минимум 4GB для Docker)"
        exit 1
    else
        print_success "RAM: ${total_ram}GB"
    fi
    
    # Проверка свободного места на диске (минимум 30GB для Docker)
    local free_space=$(df -BG / | awk 'NR==2 {print $4}' | sed 's/G//')
    if [[ $free_space -lt 30 ]]; then
        print_error "Недостаточно свободного места: ${free_space}GB (минимум 30GB)"
        exit 1
    else
        print_success "Свободное место: ${free_space}GB"
    fi
    
    # Проверка подключения к интернету
    if ! ping -c 1 8.8.8.8 &> /dev/null; then
        print_error "Нет подключения к интернету"
        exit 1
    fi
    print_success "Подключение к интернету активно"
}

################################################################################
# ФУНКЦИИ ВАЛИДАЦИИ ВВОДА
################################################################################

validate_telegram_token() {
    local token="$1"
    if [[ ! "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
        return 1
    fi
    return 0
}

validate_telegram_id() {
    local id="$1"
    if [[ ! "$id" =~ ^[0-9]+$ ]]; then
        return 1
    fi
    return 0
}

validate_url() {
    local url="$1"
    if [[ ! "$url" =~ ^https?:// ]]; then
        return 1
    fi
    return 0
}

validate_email() {
    local email="$1"
    if [[ ! "$email" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        return 1
    fi
    return 0
}

validate_domain() {
    local domain="$1"
    if [[ ! "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$ ]]; then
        return 1
    fi
    return 0
}

################################################################################
# ФУНКЦИИ ИНТЕРАКТИВНОГО СБОРА ДАННЫХ
################################################################################

collect_bot_config() {
    print_header "НАСТРОЙКА TELEGRAM БОТА"
    
    # Токен бота
    while true; do
        read -p "Введите токен Telegram бота (от @BotFather): " bot_token
        if validate_telegram_token "$bot_token"; then
            CONFIG[BOT_TOKEN]="$bot_token"
            break
        else
            print_error "Неверный формат токена. Пример: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
        fi
    done
    
    # ID администраторов
    while true; do
        read -p "Введите ID администраторов (через запятую): " admin_ids
        local valid=true
        IFS=',' read -ra IDS <<< "$admin_ids"
        for id in "${IDS[@]}"; do
            id=$(echo "$id" | xargs)
            if ! validate_telegram_id "$id"; then
                print_error "Неверный ID: $id"
                valid=false
                break
            fi
        done
        if [[ "$valid" == true ]]; then
            CONFIG[ADMIN_IDS]="$admin_ids"
            break
        fi
    done
    
    print_success "Конфигурация бота собрана"
}

collect_database_config() {
    print_header "НАСТРОЙКА БАЗЫ ДАННЫХ"
    
    print_info "База данных будет запущена в Docker контейнере"
    
    # Имя базы данных
    read -p "Имя базы данных [2getpro_v2_db]: " db_name
    CONFIG[DB_NAME]="${db_name:-2getpro_v2_db}"
    
    # Пользователь БД
    read -p "Пользователь PostgreSQL [2getpro_user]: " db_user
    CONFIG[DB_USER]="${db_user:-2getpro_user}"
    
    # Пароль БД
    while true; do
        read -sp "Пароль PostgreSQL (оставьте пустым для автогенерации): " db_password
        echo
        if [[ -z "$db_password" ]]; then
            db_password=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
            print_info "Сгенерирован пароль: $db_password"
            CONFIG[DB_PASSWORD]="$db_password"
            break
        elif [[ ${#db_password} -ge 8 ]]; then
            CONFIG[DB_PASSWORD]="$db_password"
            break
        else
            print_error "Пароль должен содержать минимум 8 символов"
        fi
    done
    
    # Пароль Redis
    while true; do
        read -sp "Пароль Redis (оставьте пустым для автогенерации): " redis_password
        echo
        if [[ -z "$redis_password" ]]; then
            redis_password=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
            print_info "Сгенерирован пароль Redis: $redis_password"
            CONFIG[REDIS_PASSWORD]="$redis_password"
            break
        elif [[ ${#redis_password} -ge 8 ]]; then
            CONFIG[REDIS_PASSWORD]="$redis_password"
            break
        else
            print_error "Пароль должен содержать минимум 8 символов"
        fi
    done
    
    CONFIG[DB_HOST]="postgres"
    CONFIG[DB_PORT]="5432"
    CONFIG[REDIS_HOST]="redis"
    CONFIG[REDIS_PORT]="6379"
    
    print_success "Конфигурация базы данных собрана"
}

collect_panel_config() {
    print_header "НАСТРОЙКА ПАНЕЛИ УПРАВЛЕНИЯ VPN"
    
    # URL панели
    while true; do
        read -p "URL API панели управления: " panel_url
        if validate_url "$panel_url"; then
            CONFIG[PANEL_API_URL]="$panel_url"
            break
        else
            print_error "Неверный формат URL. Должен начинаться с http:// или https://"
        fi
    done
    
    # API ключ
    read -p "API ключ панели: " panel_key
    CONFIG[PANEL_API_KEY]="$panel_key"
    
    print_success "Конфигурация панели собрана"
}

collect_payment_config() {
    print_header "НАСТРОЙКА ПЛАТЕЖНЫХ СИСТЕМ"
    
    # YooKassa
    read -p "Включить YooKassa? (y/n) [y]: " enable_yookassa
    if [[ "${enable_yookassa:-y}" =~ ^[Yy]$ ]]; then
        CONFIG[YOOKASSA_ENABLED]="true"
        read -p "YooKassa Shop ID: " yookassa_shop_id
        CONFIG[YOOKASSA_SHOP_ID]="$yookassa_shop_id"
        read -p "YooKassa Secret Key: " yookassa_secret
        CONFIG[YOOKASSA_SECRET_KEY]="$yookassa_secret"
    else
        CONFIG[YOOKASSA_ENABLED]="false"
    fi
    
    # CryptoPay
    read -p "Включить CryptoPay? (y/n) [y]: " enable_cryptopay
    if [[ "${enable_cryptopay:-y}" =~ ^[Yy]$ ]]; then
        CONFIG[CRYPTOPAY_ENABLED]="true"
        read -p "CryptoPay Token: " cryptopay_token
        CONFIG[CRYPTOPAY_TOKEN]="$cryptopay_token"
    else
        CONFIG[CRYPTOPAY_ENABLED]="false"
    fi
    
    # Telegram Stars
    read -p "Включить Telegram Stars? (y/n) [y]: " enable_stars
    CONFIG[STARS_ENABLED]="${enable_stars:-y}"
    
    print_success "Конфигурация платежных систем собрана"
}

collect_webhook_config() {
    print_header "НАСТРОЙКА ВЕБ-ХУКОВ (ОПЦИОНАЛЬНО)"
    
    read -p "Настроить веб-хуки? (y/n) [n]: " setup_webhooks
    if [[ "$setup_webhooks" =~ ^[Yy]$ ]]; then
        CONFIG[SETUP_WEBHOOKS]="true"
        
        while true; do
            read -p "Введите домен для веб-хуков: " webhook_domain
            if validate_domain "$webhook_domain"; then
                CONFIG[WEBHOOK_DOMAIN]="$webhook_domain"
                break
            else
                print_error "Неверный формат домена"
            fi
        done
        
        while true; do
            read -p "Email для SSL сертификата: " ssl_email
            if validate_email "$ssl_email"; then
                CONFIG[SSL_EMAIL]="$ssl_email"
                break
            else
                print_error "Неверный формат email"
            fi
        done
    else
        CONFIG[SETUP_WEBHOOKS]="false"
    fi
    
    print_success "Конфигурация веб-хуков собрана"
}

################################################################################
# ФУНКЦИИ УСТАНОВКИ DOCKER
################################################################################

update_system() {
    print_step "Обновление системы..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск обновления системы"
        return
    fi
    
    apt-get update -qq >> "$LOG_FILE" 2>&1
    DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq >> "$LOG_FILE" 2>&1
    
    print_success "Система обновлена"
}

install_docker() {
    print_step "Установка Docker Engine..."
    
    # Проверка, установлен ли Docker
    if command -v docker &> /dev/null; then
        local docker_version=$(docker --version | awk '{print $3}' | tr -d ',')
        print_info "Docker $docker_version уже установлен"
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск установки Docker"
        return
    fi
    
    # Установка зависимостей
    apt-get install -y -qq \
        ca-certificates \
        curl \
        gnupg \
        lsb-release >> "$LOG_FILE" 2>&1
    
    # Добавление GPG ключа Docker
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg >> "$LOG_FILE" 2>&1
    chmod a+r /etc/apt/keyrings/docker.gpg
    
    # Добавление репозитория Docker
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Установка Docker
    apt-get update -qq >> "$LOG_FILE" 2>&1
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >> "$LOG_FILE" 2>&1
    
    # Запуск и автозапуск Docker
    systemctl start docker >> "$LOG_FILE" 2>&1
    systemctl enable docker >> "$LOG_FILE" 2>&1
    
    print_success "Docker Engine установлен"
}

configure_docker() {
    print_step "Настройка Docker..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск настройки Docker"
        return
    fi
    
    # Создание конфигурации Docker daemon
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
EOF
    
    # Перезапуск Docker для применения настроек
    systemctl restart docker >> "$LOG_FILE" 2>&1
    
    print_success "Docker настроен"
}

add_user_to_docker_group() {
    print_step "Добавление пользователя в группу docker (опционально)..."
    
    read -p "Добавить текущего пользователя в группу docker? (y/n) [n]: " add_to_group
    if [[ "$add_to_group" =~ ^[Yy]$ ]]; then
        if [[ -n "$SUDO_USER" ]]; then
            usermod -aG docker "$SUDO_USER" >> "$LOG_FILE" 2>&1
            print_success "Пользователь $SUDO_USER добавлен в группу docker"
            print_warning "Перелогиньтесь для применения изменений"
        else
            print_warning "Не удалось определить пользователя"
        fi
    fi
}

################################################################################
# ФУНКЦИИ ПОДГОТОВКИ ПРОЕКТА
################################################################################

clone_repository() {
    print_step "Подготовка директории проекта..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск клонирования репозитория"
        return
    fi
    
    # Если директория существует и это git-репозиторий
    if [[ -d "$PROJECT_DIR/.git" ]]; then
        print_info "Репозиторий уже существует в $PROJECT_DIR"
        print_info "Обновление кода из git..."
        
        cd "$PROJECT_DIR"
        if git pull origin main >> "$LOG_FILE" 2>&1; then
            print_success "Код обновлён из репозитория"
        else
            print_warning "Не удалось обновить код, продолжаем с текущей версией"
        fi
        return
    fi
    
    # Если директория существует, но не является git-репозиторием
    if [[ -d "$PROJECT_DIR" ]]; then
        print_warning "Директория $PROJECT_DIR уже существует"
        
        # Проверяем, есть ли в ней файлы проекта
        if [[ -f "$PROJECT_DIR/main.py" ]] && [[ -f "$PROJECT_DIR/requirements.txt" ]]; then
            print_info "Обнаружены файлы проекта, продолжаем установку"
            print_success "Используем существующий код"
            return
        fi
        
        # Если это не наш проект, спрашиваем что делать
        if [[ "$SKIP_CONFIRMATIONS" == false ]]; then
            read -p "Удалить и клонировать заново? (y/n): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                rm -rf "$PROJECT_DIR"
            else
                print_info "Продолжаем с существующей директорией"
                return
            fi
        else
            print_info "Продолжаем с существующей директорией"
            return
        fi
    fi
    
    # Клонирование репозитория
    print_step "Клонирование репозитория..."
    if git clone https://github.com/2getpro/2GETPRO_v2.git "$PROJECT_DIR" >> "$LOG_FILE" 2>&1; then
        print_success "Репозиторий клонирован"
    else
        print_error "Не удалось клонировать репозиторий"
        print_info "Проверьте подключение к интернету и доступ к GitHub"
        return 1
    fi
}

create_directories() {
    print_step "Создание необходимых директорий..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск создания директорий"
        return
    fi
    
    # Создание директорий для volumes
    mkdir -p /var/lib/2getpro/{postgres,redis,prometheus,grafana}
    mkdir -p /var/backups/2getpro/postgres
    mkdir -p /var/log/{2getpro,nginx}
    
    # Установка прав
    chmod 755 /var/lib/2getpro
    chmod 755 /var/backups/2getpro
    chmod 755 /var/log/2getpro
    
    print_success "Директории созданы"
}

generate_env_file() {
    print_step "Генерация файла конфигурации..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск генерации конфигурации"
        return
    fi
    
    local env_path="$PROJECT_DIR/$ENV_FILE"
    
    # Создание резервной копии если файл существует
    if [[ -f "$env_path" ]]; then
        cp "$env_path" "$env_path.backup.$(date +%Y%m%d_%H%M%S)"
        print_info "Создана резервная копия существующего .env файла"
    fi
    
    # Генерация секретных ключей
    local jwt_secret=$(openssl rand -hex 32)
    local webhook_secret=$(openssl rand -hex 32)
    
    cat > "$env_path" << EOF
# Конфигурация 2GETPRO v2 (Docker)
# Сгенерировано автоматически: $(date)

# ============================================================================
# ОСНОВНЫЕ НАСТРОЙКИ БОТА
# ============================================================================
BOT_TOKEN=${CONFIG[BOT_TOKEN]}
ADMIN_IDS=${CONFIG[ADMIN_IDS]}

# ============================================================================
# БАЗА ДАННЫХ (Docker контейнер)
# ============================================================================
DB_HOST=${CONFIG[DB_HOST]}
DB_PORT=${CONFIG[DB_PORT]}
DB_NAME=${CONFIG[DB_NAME]}
DB_USER=${CONFIG[DB_USER]}
DB_PASSWORD=${CONFIG[DB_PASSWORD]}

# ============================================================================
# REDIS (Docker контейнер)
# ============================================================================
REDIS_HOST=${CONFIG[REDIS_HOST]}
REDIS_PORT=${CONFIG[REDIS_PORT]}
REDIS_PASSWORD=${CONFIG[REDIS_PASSWORD]}
REDIS_DB=0
REDIS_ENABLED=true

# ============================================================================
# ПАНЕЛЬ УПРАВЛЕНИЯ VPN
# ============================================================================
PANEL_API_URL=${CONFIG[PANEL_API_URL]}
PANEL_API_KEY=${CONFIG[PANEL_API_KEY]}
USER_TRAFFIC_LIMIT_GB=0
USER_TRAFFIC_STRATEGY=NO_RESET

# ============================================================================
# ПЛАТЕЖНЫЕ СИСТЕМЫ
# ============================================================================

# YooKassa
YOOKASSA_ENABLED=${CONFIG[YOOKASSA_ENABLED]:-false}
YOOKASSA_SHOP_ID=${CONFIG[YOOKASSA_SHOP_ID]:-}
YOOKASSA_SECRET_KEY=${CONFIG[YOOKASSA_SECRET_KEY]:-}
YOOKASSA_RETURN_URL=https://t.me/your_bot
YOOKASSA_AUTOPAYMENTS_ENABLED=false

# CryptoPay
CRYPTOPAY_ENABLED=${CONFIG[CRYPTOPAY_ENABLED]:-false}
CRYPTOPAY_TOKEN=${CONFIG[CRYPTOPAY_TOKEN]:-}
CRYPTOPAY_NETWORK=mainnet
CRYPTOPAY_ASSET=RUB

# Telegram Stars
STARS_ENABLED=${CONFIG[STARS_ENABLED]:-true}

# FreeKassa
FREEKASSA_ENABLED=false
FREEKASSA_MERCHANT_ID=
FREEKASSA_FIRST_SECRET=
FREEKASSA_SECOND_SECRET=
FREEKASSA_API_KEY=

# ============================================================================
# ЦЕНЫ НА ПОДПИСКИ (в копейках для рублей)
# ============================================================================
RUB_PRICE_1_MONTH=15000
RUB_PRICE_3_MONTHS=40000
RUB_PRICE_6_MONTHS=75000
RUB_PRICE_12_MONTHS=140000

STARS_PRICE_1_MONTH=150
STARS_PRICE_3_MONTHS=400
STARS_PRICE_6_MONTHS=750
STARS_PRICE_12_MONTHS=1400

1_MONTH_ENABLED=true
3_MONTHS_ENABLED=true
6_MONTHS_ENABLED=true
12_MONTHS_ENABLED=true

# ============================================================================
# РЕФЕРАЛЬНАЯ ПРОГРАММА
# ============================================================================
REFERRAL_ENABLED=true
REFERRAL_BONUS_DAYS_1_MONTH=3
REFERRAL_BONUS_DAYS_3_MONTHS=7
REFERRAL_BONUS_DAYS_6_MONTHS=15
REFERRAL_BONUS_DAYS_12_MONTHS=30

REFEREE_BONUS_DAYS_1_MONTH=1
REFEREE_BONUS_DAYS_3_MONTHS=3
REFEREE_BONUS_DAYS_6_MONTHS=7
REFEREE_BONUS_DAYS_12_MONTHS=15

REFERRAL_ONE_BONUS_PER_REFEREE=true

# ============================================================================
# ПРОБНЫЙ ПЕРИОД
# ============================================================================
TRIAL_ENABLED=true
TRIAL_DURATION_DAYS=3
TRIAL_TRAFFIC_LIMIT_GB=5.0

# ============================================================================
# УВЕДОМЛЕНИЯ
# ============================================================================
SUBSCRIPTION_NOTIFICATIONS_ENABLED=true
SUBSCRIPTION_NOTIFY_ON_EXPIRE=true
SUBSCRIPTION_NOTIFY_AFTER_EXPIRE=true
SUBSCRIPTION_NOTIFY_DAYS_BEFORE=3

LOG_CHAT_ID=
LOG_THREAD_ID=
LOG_NEW_USERS=true
LOG_PAYMENTS=true
LOG_PROMO_ACTIVATIONS=true
LOG_TRIAL_ACTIVATIONS=true

# ============================================================================
# МОНИТОРИНГ
# ============================================================================
SENTRY_ENABLED=false
SENTRY_DSN=
SENTRY_ENVIRONMENT=production

PROMETHEUS_ENABLED=true
PROMETHEUS_PORT=9090

# Grafana (для Docker)
GRAFANA_USER=admin
GRAFANA_PASSWORD=$(openssl rand -base64 16 | tr -d "=+/")

# ============================================================================
# БЕЗОПАСНОСТЬ
# ============================================================================
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=30
RATE_LIMIT_WINDOW=60

WEBHOOK_VALIDATION_ENABLED=true
WEBHOOK_SECRET_TOKEN=$webhook_secret
JWT_SECRET=$jwt_secret

# ============================================================================
# ВЕБ-СЕРВЕР
# ============================================================================
WEB_SERVER_HOST=0.0.0.0
WEB_SERVER_PORT=8080
WEBHOOK_BASE_URL=${CONFIG[WEBHOOK_DOMAIN]:+https://${CONFIG[WEBHOOK_DOMAIN]}}

# ============================================================================
# ЛОКАЛИЗАЦИЯ
# ============================================================================
DEFAULT_LANGUAGE=ru
DEFAULT_CURRENCY_SYMBOL=RUB
SUPPORTED_LANGUAGES=ru,en

# ============================================================================
# ОБЯЗАТЕЛЬНАЯ ПОДПИСКА НА КАНАЛ
# ============================================================================
REQUIRED_CHANNEL_ID=
REQUIRED_CHANNEL_LINK=

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
LOG_LEVEL=INFO
LOG_FORMAT=json

# ============================================================================
# DOCKER СПЕЦИФИЧНЫЕ НАСТРОЙКИ
# ============================================================================
VERSION=latest
EOF

    chmod 600 "$env_path"
    
    print_success "Файл конфигурации создан: $env_path"
}

setup_docker_compose() {
    print_step "Настройка Docker Compose..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск настройки Docker Compose"
        return
    fi
    
    # Копирование docker-compose файла
    cp "$PROJECT_DIR/infrastructure/docker/docker-compose.prod.yml" "$PROJECT_DIR/$DOCKER_COMPOSE_FILE"
    
    # Упрощение конфигурации для базовой установки (убираем мониторинг по умолчанию)
    cat > "$PROJECT_DIR/$DOCKER_COMPOSE_FILE" << 'EOF'
version: '3.8'

services:
  # Bot service
  bot:
    build: .
    container_name: 2getpro-bot
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - ENVIRONMENT=production
      - LOG_LEVEL=INFO
      - DEBUG=false
    networks:
      - backend
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - /var/log/2getpro:/app/logs
      - cache:/app/cache
    ports:
      - "127.0.0.1:8080:8080"
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:8080/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
  
  # PostgreSQL database
  postgres:
    image: postgres:15-alpine
    container_name: 2getpro-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DB_NAME:-2getpro_v2_db}
      POSTGRES_USER: ${DB_USER:-2getpro_user}
      POSTGRES_PASSWORD: ${DB_PASSWORD:?Database password required}
      POSTGRES_INITDB_ARGS: "-E UTF8 --locale=en_US.UTF-8"
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - /var/lib/2getpro/postgres:/var/lib/postgresql/data
      - /var/backups/2getpro/postgres:/backups
    networks:
      - backend
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-2getpro_user} -d ${DB_NAME:-2getpro_v2_db}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
  
  # Redis cache
  redis:
    image: redis:7-alpine
    container_name: 2getpro-redis
    restart: unless-stopped
    command: >
      redis-server
      --appendonly yes
      --appendfsync everysec
      --requirepass ${REDIS_PASSWORD:?Redis password required}
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
    volumes:
      - /var/lib/2getpro/redis:/data
    networks:
      - backend
    ports:
      - "127.0.0.1:6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 5s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

# Volumes
volumes:
  cache:
    driver: local

# Networks
networks:
  backend:
    driver: bridge
EOF
    
    print_success "Docker Compose настроен"
}

################################################################################
# ФУНКЦИИ ЗАПУСКА И ПРОВЕРКИ
################################################################################

build_docker_images() {
    print_step "Сборка Docker образов..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск сборки образов"
        return
    fi
    
    cd "$PROJECT_DIR"
    docker compose build >> "$LOG_FILE" 2>&1
    
    print_success "Docker образы собраны"
}

start_docker_compose() {
    print_step "Запуск Docker Compose..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск запуска контейнеров"
        return
    fi
    
    cd "$PROJECT_DIR"
    docker compose up -d >> "$LOG_FILE" 2>&1
    
    print_success "Контейнеры запущены"
    
    # Ждем запуска контейнеров
    print_step "Ожидание запуска контейнеров..."
    sleep 10
}

apply_migrations() {
    print_step "Применение миграций базы данных..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск применения миграций"
        return
    fi
    
    cd "$PROJECT_DIR"
    
    # Ждем готовности базы данных
    print_info "Ожидание готовности базы данных..."
    local max_attempts=30
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        if docker compose exec -T postgres pg_isready -U "${CONFIG[DB_USER]}" &> /dev/null; then
            break
        fi
        sleep 2
        ((attempt++))
    done
    
    if [[ $attempt -gt $max_attempts ]]; then
        print_error "База данных не готова после $max_attempts попыток"
        return 1
    fi
    
    # Применение миграций
    docker compose exec -T bot python db/migrator.py >> "$LOG_FILE" 2>&1
    
    print_success "Миграции применены"
}

check_docker_installation() {
    print_header "ПРОВЕРКА УСТАНОВКИ"
    
    local all_ok=true
    
    # Проверка контейнеров
    print_step "Проверка статуса контейнеров..."
    cd "$PROJECT_DIR"
    
    local running_containers=$(docker compose ps --services --filter "status=running" | wc -l)
    local total_containers=$(docker compose ps --services | wc -l)
    
    if [[ $running_containers -eq $total_containers ]]; then
        print_success "Все контейнеры запущены ($running_containers/$total_containers)"
    else
        print_error "Не все контейнеры запущены ($running_containers/$total_containers)"
        all_ok=false
    fi
    
    # Проверка логов бота
    print_step "Проверка логов бота на ошибки..."
    if docker compose logs bot | grep -qi "error"; then
        print_warning "Обнаружены ошибки в логах бота"
        all_ok=false
    else
        print_success "Критических ошибок не обнаружено"
    fi
    
    # Проверка подключения к БД
    print_step "Проверка подключения к базе данных..."
    if docker compose exec -T postgres pg_isready -U "${CONFIG[DB_USER]}" &> /dev/null; then
        print_success "База данных доступна"
    else
        print_error "База данных недоступна"
        all_ok=false
    fi
    
    # Проверка Redis
    print_step "Проверка Redis..."
    if docker compose exec -T redis redis-cli -a "${CONFIG[REDIS_PASSWORD]}" ping &> /dev/null; then
        print_success "Redis работает"
    else
        print_error "Redis не отвечает"
        all_ok=false
    fi
    
    if [[ "$all_ok" == true ]]; then
        print_success "Все проверки пройдены успешно!"
        return 0
    else
        print_warning "Некоторые проверки не пройдены"
        return 1
    fi
}

################################################################################
# ФУНКЦИИ НАСТРОЙКИ ВЕБ-ХУКОВ
################################################################################

install_nginx() {
    if [[ "${CONFIG[SETUP_WEBHOOKS]}" != "true" ]]; then
        return
    fi
    
    print_step "Установка Nginx на хосте..."
    
    if systemctl is-active --quiet nginx; then
        print_info "Nginx уже установлен и запущен"
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск установки Nginx"
        return
    fi
    
    apt-get install -y -qq nginx >> "$LOG_FILE" 2>&1
    systemctl start nginx >> "$LOG_FILE" 2>&1
    systemctl enable nginx >> "$LOG_FILE" 2>&1
    
    print_success "Nginx установлен и запущен"
}

setup_nginx_config() {
    if [[ "${CONFIG[SETUP_WEBHOOKS]}" != "true" ]]; then
        return
    fi
    
    print_step "Настройка Nginx reverse proxy..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск настройки Nginx"
        return
    fi
    
    local domain="${CONFIG[WEBHOOK_DOMAIN]}"
    local nginx_config="/etc/nginx/sites-available/2getpro-v2"
    
    cat > "$nginx_config" << EOF
server {
    listen 80;
    server_name $domain;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

    ln -sf "$nginx_config" /etc/nginx/sites-enabled/
    nginx -t >> "$LOG_FILE" 2>&1
    systemctl reload nginx >> "$LOG_FILE" 2>&1
    
    print_success "Nginx настроен"
}

setup_ssl_certificate() {
    if [[ "${CONFIG[SETUP_WEBHOOKS]}" != "true" ]]; then
        return
    fi
    
    print_step "Установка SSL сертификата..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск установки SSL"
        return
    fi
    
    # Установка Certbot
    apt-get install -y -qq certbot python3-certbot-nginx >> "$LOG_FILE" 2>&1
    
    # Получение сертификата
    certbot --nginx -d "${CONFIG[WEBHOOK_DOMAIN]}" \
        --non-interactive \
        --agree-tos \
        --email "${CONFIG[SSL_EMAIL]}" \
        --redirect >> "$LOG_FILE" 2>&1
    
    print_success "SSL сертификат установлен"
}

################################################################################
# ФУНКЦИЯ ВЫВОДА ИТОГОВОЙ ИНФОРМАЦИИ
################################################################################

print_summary() {
    print_header "УСТАНОВКА ЗАВЕРШЕНА"
    
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${NC}  ${WHITE}2GETPRO v2 успешно установлен через Docker!${NC}                ${GREEN}║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo
    
    echo -e "${CYAN}📋 Информация об установке:${NC}"
    echo -e "   Директория: ${WHITE}$PROJECT_DIR${NC}"
    echo -e "   Конфигурация: ${WHITE}$PROJECT_DIR/$ENV_FILE${NC}"
    echo -e "   Docker Compose: ${WHITE}$PROJECT_DIR/$DOCKER_COMPOSE_FILE${NC}"
    echo -e "   Логи: ${WHITE}/var/log/2getpro${NC}"
    echo
    
    echo -e "${CYAN}🔐 Данные базы данных:${NC}"
    echo -e "   База данных: ${WHITE}${CONFIG[DB_NAME]}${NC}"
    echo -e "   Пользователь: ${WHITE}${CONFIG[DB_USER]}${NC}"
    echo -e "   Пароль: ${WHITE}${CONFIG[DB_PASSWORD]}${NC}"
    echo -e "   Redis пароль: ${WHITE}${CONFIG[REDIS_PASSWORD]}${NC}"
    echo -e "   ${YELLOW}⚠ Сохраните эти данные в безопасном месте!${NC}"
    echo
    
    echo -e "${CYAN}🐳 Управление Docker контейнерами:${NC}"
    echo -e "   Статус:      ${WHITE}docker compose ps${NC}"
    echo -e "   Логи:        ${WHITE}docker compose logs -f bot${NC}"
    echo -e "   Перезапуск:  ${WHITE}docker compose restart${NC}"
    echo -e "   Остановка:   ${WHITE}docker compose down${NC}"
    echo -e "   Запуск:      ${WHITE}docker compose up -d${NC}"
    echo -e "   Обновление:  ${WHITE}docker compose pull && docker compose up -d${NC}"
    echo
    
    echo -e "${CYAN}📊 Полезные команды:${NC}"
    echo -e "   Войти в контейнер бота:  ${WHITE}docker compose exec bot bash${NC}"
    echo -e "   Войти в PostgreSQL:      ${WHITE}docker compose exec postgres psql -U ${CONFIG[DB_USER]} -d ${CONFIG[DB_NAME]}${NC}"
    echo -e "   Войти в Redis:           ${WHITE}docker compose exec redis redis-cli -a ${CONFIG[REDIS_PASSWORD]}${NC}"
    echo -e "   Просмотр логов всех:     ${WHITE}docker compose logs -f${NC}"
    echo
    
    if [[ "${CONFIG[SETUP_WEBHOOKS]}" == "true" ]]; then
        echo -e "${CYAN}🌐 Веб-хуки:${NC}"
        echo -e "   Домен: ${WHITE}https://${CONFIG[WEBHOOK_DOMAIN]}${NC}"
        echo -e "   SSL: ${GREEN}✓ Установлен${NC}"
        echo
    fi
    
    echo -e "${CYAN}📚 Следующие шаги:${NC}"
    echo -e "   1. Проверьте работу бота: отправьте ${WHITE}/start${NC} в Telegram"
    echo -e "   2. Настройте резервное копирование"
    echo -e "   3. Изучите документацию в ${WHITE}docs/${NC}"
    echo -e "   4. Настройте мониторинг (опционально)"
    echo
    
    echo -e "${CYAN}📞 Помощь:${NC}"
    echo -e "   Документация: ${WHITE}$PROJECT_DIR/docs/${NC}"
    echo -e "   Логи установки: ${WHITE}$LOG_FILE${NC}"
    echo -e "   Docker документация: ${WHITE}$PROJECT_DIR/docs/deployment/docker.md${NC}"
    echo
    
    echo -e "${GREEN}✨ Спасибо за использование 2GETPRO v2!${NC}"
    echo
}

################################################################################
# ОБРАБОТКА ПАРАМЕТРОВ КОМАНДНОЙ СТРОКИ
################################################################################

show_usage() {
    cat << EOF
Использование: $0 [ОПЦИИ]

Docker-based установщик 2GETPRO v2 для Ubuntu 24.04 LTS

ОПЦИИ:
    -h, --help              Показать эту справку
    -s, --silent            Тихий режим (без интерактивных запросов)
    -y, --yes               Автоматически отвечать "да" на все вопросы
    -d, --dry-run           Режим проверки без реальных изменений
    --skip-system-update    Пропустить обновление системы
    --skip-webhooks         Пропустить настройку веб-хуков

ПРИМЕРЫ:
    # Интерактивная установка
    sudo $0

    # Тихая установка с автоподтверждением
    sudo $0 --silent --yes

    # Проверка без изменений
    sudo $0 --dry-run

EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -s|--silent)
                SILENT_MODE=true
                shift
                ;;
            -y|--yes)
                SKIP_CONFIRMATIONS=true
                shift
                ;;
            -d|--dry-run)
                DRY_RUN=true
                shift
                ;;
            --skip-system-update)
                SKIP_SYSTEM_UPDATE=true
                shift
                ;;
            --skip-webhooks)
                CONFIG[SETUP_WEBHOOKS]="false"
                shift
                ;;
            *)
                print_error "Неизвестная опция: $1"
                show_usage
                exit 1
                ;;
        esac
    done
}

################################################################################
# ГЛАВНАЯ ФУНКЦИЯ
################################################################################

main() {
    # Инициализация лога
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
    chmod 644 "$LOG_FILE"
    
    log "INFO" "=========================================="
    log "INFO" "Начало Docker установки 2GETPRO v2"
    log "INFO" "=========================================="
    
    # Заголовок
    clear
    echo -e "${CYAN}"
    cat << "EOF"
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║         2GETPRO v2 - Docker установщик для Production        ║
║                     Ubuntu 24.04 LTS                          ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}\n"
    
    # Проверки системы
    check_root
    check_ubuntu_version
    check_system_requirements
    
    # Сбор конфигурации
    if [[ "$SILENT_MODE" == false ]]; then
        collect_bot_config
        collect_database_config
        collect_panel_config
        collect_payment_config
        collect_webhook_config
        
        # Подтверждение установки
        print_header "ПОДТВЕРЖДЕНИЕ УСТАНОВКИ"
        echo -e "${YELLOW}Будут установлены следующие компоненты:${NC}"
        echo -e "  • Docker Engine"
        echo -e "  • Docker Compose V2"
        echo -e "  • PostgreSQL (в контейнере)"
        echo -e "  • Redis (в контейнере)"
        echo -e "  • 2GETPRO v2 Bot (в контейнере)"
        if [[ "${CONFIG[SETUP_WEBHOOKS]}" == "true" ]]; then
            echo -e "  • Nginx + SSL сертификат (на хосте)"
        fi
        echo
        
        if [[ "$SKIP_CONFIRMATIONS" == false ]]; then
            read -p "Продолжить установку? (y/n): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                print_info "Установка отменена"
                exit 0
            fi
        fi
    fi
    
    # Установка компонентов
    print_header "УСТАНОВКА DOCKER"
    
    if [[ "${SKIP_SYSTEM_UPDATE:-false}" != "true" ]]; then
        update_system
    fi
    
    install_docker
    configure_docker
    add_user_to_docker_group
    
    # Подготовка проекта
    print_header "ПОДГОТОВКА ПРОЕКТА"
    
    clone_repository
    create_directories
    generate_env_file
    setup_docker_compose
    
    # Сборка и запуск
    print_header "СБОРКА И ЗАПУСК КОНТЕЙНЕРОВ"
    
    build_docker_images
    start_docker_compose
    
    # Применение миграций
    print_header "ПРИМЕНЕНИЕ МИГРАЦИЙ"
    apply_migrations
    
    # Настройка веб-хуков
    if [[ "${CONFIG[SETUP_WEBHOOKS]}" == "true" ]]; then
        print_header "НАСТРОЙКА ВЕБ-ХУКОВ"
        install_nginx
        setup_nginx_config
        setup_ssl_certificate
    fi
    
    # Проверка установки
    check_docker_installation
    
    # Вывод итоговой информации
    print_summary
    
    log "INFO" "Docker установка завершена успешно"
}

################################################################################
# ОБРАБОТКА ОШИБОК
################################################################################

trap 'handle_error $? $LINENO' ERR

handle_error() {
    local exit_code=$1
    local line_number=$2
    
    print_error "Ошибка на строке $line_number (код: $exit_code)"
    log "ERROR" "Ошибка на строке $line_number (код: $exit_code)"
    
    print_info "Для отката выполните: cd $PROJECT_DIR && docker compose down"
    
    exit $exit_code
}

################################################################################
# ТОЧКА ВХОДА
################################################################################

parse_arguments "$@"
main

exit 0