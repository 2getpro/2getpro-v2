#!/bin/bash
################################################################################
# Автоматический установщик 2GETPRO v2 для Ubuntu 24.04.03 LTS
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
SYSTEM_USER="2getpro"
LOG_FILE="/var/log/2getpro-install.log"
ENV_FILE=".env.production"
BACKUP_DIR="/opt/2getpro-backups"

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
    
    # Проверка RAM (минимум 2GB, рекомендуется 4GB)
    local total_ram=$(free -g | awk '/^Mem:/{print $2}')
    if [[ $total_ram -lt 2 ]]; then
        print_error "Недостаточно RAM: ${total_ram}GB (минимум 2GB)"
        exit 1
    elif [[ $total_ram -lt 4 ]]; then
        print_warning "RAM: ${total_ram}GB (рекомендуется 4GB)"
    else
        print_success "RAM: ${total_ram}GB"
    fi
    
    # Проверка свободного места на диске (минимум 20GB)
    local free_space=$(df -BG / | awk 'NR==2 {print $4}' | sed 's/G//')
    if [[ $free_space -lt 20 ]]; then
        print_error "Недостаточно свободного места: ${free_space}GB (минимум 20GB)"
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
    # Формат токена: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz
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
            id=$(echo "$id" | xargs)  # Убираем пробелы
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
    
    CONFIG[DB_HOST]="localhost"
    CONFIG[DB_PORT]="5432"
    
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
# ФУНКЦИИ УСТАНОВКИ КОМПОНЕНТОВ
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

install_python() {
    print_step "Установка Python 3.11+..."
    
    if command -v python3 &> /dev/null; then
        local python_version=$(python3 --version | awk '{print $2}')
        print_info "Python $python_version уже установлен"
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск установки Python"
        return
    fi
    
    apt-get install -y -qq python3 python3-pip python3-venv python3-dev >> "$LOG_FILE" 2>&1
    
    print_success "Python установлен"
}

install_postgresql() {
    print_step "Установка PostgreSQL..."
    
    if systemctl is-active --quiet postgresql; then
        print_info "PostgreSQL уже установлен и запущен"
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск установки PostgreSQL"
        return
    fi
    
    apt-get install -y -qq postgresql postgresql-contrib >> "$LOG_FILE" 2>&1
    systemctl start postgresql >> "$LOG_FILE" 2>&1
    systemctl enable postgresql >> "$LOG_FILE" 2>&1
    
    print_success "PostgreSQL установлен и запущен"
}

install_redis() {
    print_step "Установка Redis..."
    
    if systemctl is-active --quiet redis-server; then
        print_info "Redis уже установлен и запущен"
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск установки Redis"
        return
    fi
    
    apt-get install -y -qq redis-server >> "$LOG_FILE" 2>&1
    systemctl start redis-server >> "$LOG_FILE" 2>&1
    systemctl enable redis-server >> "$LOG_FILE" 2>&1
    
    print_success "Redis установлен и запущен"
}

install_git() {
    print_step "Установка Git..."
    
    if command -v git &> /dev/null; then
        print_info "Git уже установлен"
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск установки Git"
        return
    fi
    
    apt-get install -y -qq git >> "$LOG_FILE" 2>&1
    
    print_success "Git установлен"
}

install_system_packages() {
    print_step "Установка системных пакетов..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск установки системных пакетов"
        return
    fi
    
    apt-get install -y -qq \
        build-essential \
        libssl-dev \
        libffi-dev \
        libpq-dev \
        curl \
        wget \
        >> "$LOG_FILE" 2>&1
    
    print_success "Системные пакеты установлены"
}

install_nginx() {
    if [[ "${CONFIG[SETUP_WEBHOOKS]}" != "true" ]]; then
        return
    fi
    
    print_step "Установка Nginx..."
    
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

################################################################################
# ФУНКЦИИ НАСТРОЙКИ БАЗЫ ДАННЫХ
################################################################################

# Функция настройки аутентификации PostgreSQL
configure_postgresql_auth() {
    log "INFO" "Настройка аутентификации PostgreSQL..."
    print_step "Настройка аутентификации PostgreSQL..."
    
    # Находим файл pg_hba.conf
    local PG_HBA_CONF=$(sudo -u postgres psql -t -P format=unaligned -c 'SHOW hba_file;' 2>/dev/null | tr -d '[:space:]')
    
    if [[ -z "$PG_HBA_CONF" ]] || [[ ! -f "$PG_HBA_CONF" ]]; then
        print_error "Не удалось найти файл pg_hba.conf"
        return 1
    fi
    
    log "INFO" "Найден файл pg_hba.conf: $PG_HBA_CONF"
    
    # Создаём резервную копию
    if ! sudo cp "$PG_HBA_CONF" "${PG_HBA_CONF}.backup.$(date +%Y%m%d_%H%M%S)"; then
        print_error "Не удалось создать резервную копию pg_hba.conf"
        return 1
    fi
    
    # Проверяем, есть ли уже правило для нашего пользователя
    if sudo grep -q "^host.*${CONFIG[DB_NAME]}.*${CONFIG[DB_USER]}" "$PG_HBA_CONF"; then
        print_warning "Правило для пользователя ${CONFIG[DB_USER]} уже существует"
    else
        # Добавляем правило для подключения с паролем
        log "INFO" "Добавление правила аутентификации для ${CONFIG[DB_USER]}"
        
        # Добавляем правило перед строкой с "local all all"
        sudo sed -i "/^local[[:space:]]*all[[:space:]]*all/i # Rule for ${CONFIG[DB_NAME]}\nhost    ${CONFIG[DB_NAME]}    ${CONFIG[DB_USER]}    127.0.0.1/32    scram-sha-256\nhost    ${CONFIG[DB_NAME]}    ${CONFIG[DB_USER]}    ::1/128         scram-sha-256" "$PG_HBA_CONF"
        
        if [[ $? -eq 0 ]]; then
            print_success "Правило аутентификации добавлено"
        else
            print_error "Не удалось добавить правило аутентификации"
            return 1
        fi
    fi
    
    # Перезагружаем конфигурацию PostgreSQL
    log "INFO" "Перезагрузка конфигурации PostgreSQL..."
    if sudo systemctl reload postgresql; then
        print_success "Конфигурация PostgreSQL перезагружена"
        sleep 2  # Даём время на применение изменений
        return 0
    else
        print_error "Не удалось перезагрузить конфигурацию PostgreSQL"
        return 1
    fi
}

setup_database() {
    print_step "Настройка базы данных PostgreSQL..."
    log "INFO" "Начало настройки базы данных PostgreSQL"
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск настройки базы данных"
        return
    fi
    
    # Проверка, что PostgreSQL запущен
    if ! systemctl is-active --quiet postgresql; then
        print_error "PostgreSQL не запущен"
        log "ERROR" "PostgreSQL не запущен"
        return 1
    fi
    log "INFO" "PostgreSQL запущен и активен"
    
    # Проверка существования пользователя
    log "INFO" "Проверка существования пользователя ${CONFIG[DB_USER]}"
    if sudo -u postgres psql -w -tAc "SELECT 1 FROM pg_roles WHERE rolname='${CONFIG[DB_USER]}'" 2>/dev/null | grep -q 1; then
        print_warning "Пользователь ${CONFIG[DB_USER]} уже существует"
        log "WARNING" "Пользователь ${CONFIG[DB_USER]} уже существует"
    else
        # Создание пользователя с SCRAM-SHA-256
        log "INFO" "Создание пользователя PostgreSQL: ${CONFIG[DB_USER]}"
        print_info "Создание пользователя ${CONFIG[DB_USER]}..."
        
        if sudo -u postgres psql -w -c "CREATE USER \"${CONFIG[DB_USER]}\" WITH PASSWORD '${CONFIG[DB_PASSWORD]}';" 2>&1 | tee -a "$LOG_FILE"; then
            print_success "Пользователь ${CONFIG[DB_USER]} создан"
            log "SUCCESS" "Пользователь ${CONFIG[DB_USER]} создан успешно"
        else
            print_error "Не удалось создать пользователя ${CONFIG[DB_USER]}"
            log "ERROR" "Не удалось создать пользователя ${CONFIG[DB_USER]}"
            return 1
        fi
    fi
    
    # Проверка существования базы данных
    log "INFO" "Проверка существования базы данных ${CONFIG[DB_NAME]}"
    if sudo -u postgres psql -w -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw "${CONFIG[DB_NAME]}"; then
        print_warning "База данных ${CONFIG[DB_NAME]} уже существует"
        log "WARNING" "База данных ${CONFIG[DB_NAME]} уже существует"
    else
        # Создание базы данных
        log "INFO" "Создание базы данных: ${CONFIG[DB_NAME]}"
        print_info "Создание базы данных ${CONFIG[DB_NAME]}..."
        
        if sudo -u postgres psql -w -c "CREATE DATABASE \"${CONFIG[DB_NAME]}\" OWNER \"${CONFIG[DB_USER]}\";" 2>&1 | tee -a "$LOG_FILE"; then
            print_success "База данных ${CONFIG[DB_NAME]} создана"
            log "SUCCESS" "База данных ${CONFIG[DB_NAME]} создана успешно"
        else
            print_error "Не удалось создать базу данных ${CONFIG[DB_NAME]}"
            log "ERROR" "Не удалось создать базу данных ${CONFIG[DB_NAME]}"
            return 1
        fi
    fi
    
    # Настройка прав доступа
    log "INFO" "Настройка прав доступа к базе данных"
    print_info "Настройка прав доступа..."
    
    if sudo -u postgres psql -w -c "GRANT ALL PRIVILEGES ON DATABASE \"${CONFIG[DB_NAME]}\" TO \"${CONFIG[DB_USER]}\";" 2>&1 | tee -a "$LOG_FILE"; then
        log "SUCCESS" "Права доступа настроены"
    else
        print_warning "Возможны проблемы с настройкой прав доступа"
        log "WARNING" "Возможны проблемы с настройкой прав доступа"
    fi
    
    # Настройка аутентификации PostgreSQL
    if ! configure_postgresql_auth; then
        print_error "Не удалось настроить аутентификацию PostgreSQL"
        return 1
    fi
    
    # Проверка подключения к базе данных
    log "INFO" "Проверка подключения к базе данных"
    print_info "Проверка подключения к базе данных..."
    
    if PGPASSWORD="${CONFIG[DB_PASSWORD]}" psql -h localhost -U "${CONFIG[DB_USER]}" -d "${CONFIG[DB_NAME]}" -w -c "SELECT 1;" &>/dev/null; then
        print_success "Подключение к базе данных успешно"
        log "SUCCESS" "Подключение к базе данных ${CONFIG[DB_NAME]} успешно"
        return 0
    else
        print_error "Не удалось подключиться к базе данных"
        log "ERROR" "Не удалось подключиться к базе данных ${CONFIG[DB_NAME]}"
        print_info "Проверьте настройки PostgreSQL: /etc/postgresql/*/main/pg_hba.conf"
        print_info "Попробуйте выполнить вручную:"
        print_info "  sudo nano /etc/postgresql/*/main/pg_hba.conf"
        print_info "  Добавьте строку: host    ${CONFIG[DB_NAME]}    ${CONFIG[DB_USER]}    127.0.0.1/32    scram-sha-256"
        print_info "  sudo systemctl reload postgresql"
        return 1
    fi
}

################################################################################
# ФУНКЦИИ УСТАНОВКИ БОТА
################################################################################

create_system_user() {
    print_step "Создание системного пользователя..."
    
    if id "$SYSTEM_USER" &>/dev/null; then
        print_info "Пользователь $SYSTEM_USER уже существует"
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск создания пользователя"
        return
    fi
    
    useradd -r -m -s /bin/bash -d "$PROJECT_DIR" "$SYSTEM_USER" >> "$LOG_FILE" 2>&1
    
    print_success "Пользователь $SYSTEM_USER создан"
}

clone_repository() {
    print_step "Проверка директории проекта..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск проверки репозитория"
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

setup_permissions() {
    print_step "Настройка прав доступа..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск настройки прав"
        return
    fi
    
    chown -R "$SYSTEM_USER:$SYSTEM_USER" "$PROJECT_DIR"
    chmod -R 755 "$PROJECT_DIR"
    
    print_success "Права доступа настроены"
}

create_virtualenv() {
    print_step "Создание виртуального окружения Python..."
    
    if [[ -d "$PROJECT_DIR/venv" ]]; then
        print_info "Виртуальное окружение уже существует"
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск создания виртуального окружения"
        return
    fi
    
    sudo -u "$SYSTEM_USER" python3 -m venv "$PROJECT_DIR/venv" >> "$LOG_FILE" 2>&1
    
    print_success "Виртуальное окружение создано"
}

install_dependencies() {
    print_step "Установка Python зависимостей..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск установки зависимостей"
        return
    fi
    
    sudo -u "$SYSTEM_USER" bash -c "
        cd '$PROJECT_DIR'
        source venv/bin/activate
        pip install --upgrade pip setuptools wheel >> '$LOG_FILE' 2>&1
        pip install -r requirements.txt >> '$LOG_FILE' 2>&1
    "
    
    print_success "Зависимости установлены"
}

create_directories() {
    print_step "Создание необходимых директорий..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск создания директорий"
        return
    fi
    
    sudo -u "$SYSTEM_USER" mkdir -p "$PROJECT_DIR"/{logs,backups,cache}
    mkdir -p /var/log/2getpro
    chown "$SYSTEM_USER:$SYSTEM_USER" /var/log/2getpro
    
    print_success "Директории созданы"
}

################################################################################
# ФУНКЦИИ ГЕНЕРАЦИИ КОНФИГУРАЦИИ
################################################################################

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
# Конфигурация 2GETPRO v2
# Сгенерировано автоматически: $(date)

# ============================================================================
# ОСНОВНЫЕ НАСТРОЙКИ БОТА
# ============================================================================
BOT_TOKEN=${CONFIG[BOT_TOKEN]}
ADMIN_IDS=${CONFIG[ADMIN_IDS]}

# ============================================================================
# БАЗА ДАННЫХ
# ============================================================================
DB_HOST=${CONFIG[DB_HOST]}
DB_PORT=${CONFIG[DB_PORT]}
DB_NAME=${CONFIG[DB_NAME]}
DB_USER=${CONFIG[DB_USER]}
DB_PASSWORD=${CONFIG[DB_PASSWORD]}

# ============================================================================
# REDIS
# ============================================================================
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
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
EOF

    chown "$SYSTEM_USER:$SYSTEM_USER" "$env_path"
    chmod 600 "$env_path"
    
    print_success "Файл конфигурации создан: $env_path"
}

################################################################################
# ФУНКЦИИ НАСТРОЙКИ SYSTEMD
################################################################################

setup_systemd_service() {
    print_step "Настройка systemd сервиса..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск настройки systemd"
        return
    fi
    
    # Копирование скриптов
    mkdir -p "$PROJECT_DIR/scripts"
    cp "$PROJECT_DIR/infrastructure/systemd/scripts/pre-start.sh" "$PROJECT_DIR/scripts/"
    cp "$PROJECT_DIR/infrastructure/systemd/scripts/graceful-stop.sh" "$PROJECT_DIR/scripts/"
    chmod +x "$PROJECT_DIR/scripts"/*.sh
    
    # Копирование файла сервиса
    cp "$PROJECT_DIR/infrastructure/systemd/2getpro-v2.service" /etc/systemd/system/
    
    # Обновление пути к .env файлу в сервисе
    sed -i "s|EnvironmentFile=.*|EnvironmentFile=$PROJECT_DIR/$ENV_FILE|" /etc/systemd/system/2getpro-v2.service
    
    # Перезагрузка systemd
    systemctl daemon-reload >> "$LOG_FILE" 2>&1
    
    # Включение автозапуска
    systemctl enable 2getpro-v2.service >> "$LOG_FILE" 2>&1
    
    print_success "Systemd сервис настроен"
}

################################################################################
# ФУНКЦИИ ПРИМЕНЕНИЯ МИГРАЦИЙ
################################################################################

apply_migrations() {
    print_step "Применение миграций базы данных..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск применения миграций"
        return
    fi
    
    sudo -u "$SYSTEM_USER" bash -c "
        cd '$PROJECT_DIR'
        source venv/bin/activate
        python db/migrator.py >> '$LOG_FILE' 2>&1
    "
    
    print_success "Миграции применены"
}

################################################################################
# ФУНКЦИИ НАСТРОЙКИ ВЕБ-ХУКОВ
################################################################################

setup_nginx_config() {
    if [[ "${CONFIG[SETUP_WEBHOOKS]}" != "true" ]]; then
        return
    fi
    
    print_step "Настройка Nginx..."
    
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
# ФУНКЦИИ ПРОВЕРКИ УСТАНОВКИ
################################################################################

start_bot_service() {
    print_step "Запуск бота..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Пропуск запуска бота"
        return
    fi
    
    systemctl start 2getpro-v2.service >> "$LOG_FILE" 2>&1
    sleep 5  # Даем время на запуск
    
    if systemctl is-active --quiet 2getpro-v2.service; then
        print_success "Бот успешно запущен"
    else
        print_error "Не удалось запустить бота"
        print_info "Проверьте логи: journalctl -u 2getpro-v2.service -n 50"
        return 1
    fi
}

check_installation() {
    print_header "ПРОВЕРКА УСТАНОВКИ"
    
    local all_ok=true
    
    # Проверка сервиса
    print_step "Проверка статуса сервиса..."
    if systemctl is-active --quiet 2getpro-v2.service; then
        print_success "Сервис активен"
    else
        print_error "Сервис не активен"
        all_ok=false
    fi
    
    # Проверка базы данных
    print_step "Проверка подключения к базе данных..."
    if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "${CONFIG[DB_NAME]}"; then
        print_success "База данных доступна"
    else
        print_error "База данных недоступна"
        all_ok=false
    fi
    
    # Проверка Redis
    print_step "Проверка Redis..."
    if redis-cli ping &> /dev/null; then
        print_success "Redis работает"
    else
        print_error "Redis не отвечает"
        all_ok=false
    fi
    
    # Проверка логов
    print_step "Проверка логов на ошибки..."
    if journalctl -u 2getpro-v2.service -n 20 | grep -qi "error"; then
        print_warning "Обнаружены ошибки в логах"
        all_ok=false
    else
        print_success "Критических ошибок не обнаружено"
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
# ФУНКЦИЯ ОТКАТА ИЗМЕНЕНИЙ
################################################################################

rollback_installation() {
    print_header "ОТКАТ ИЗМЕНЕНИЙ"
    print_warning "Выполняется откат установки..."
    
    # Остановка сервиса
    systemctl stop 2getpro-v2.service 2>/dev/null || true
    systemctl disable 2getpro-v2.service 2>/dev/null || true
    
    # Удаление файлов systemd
    rm -f /etc/systemd/system/2getpro-v2.service
    systemctl daemon-reload
    
    # Удаление директории проекта
    if [[ -d "$PROJECT_DIR" ]]; then
        rm -rf "$PROJECT_DIR"
    fi
    
    # Удаление пользователя
    userdel -r "$SYSTEM_USER" 2>/dev/null || true
    
    print_info "Откат завершен"
}

################################################################################
# ФУНКЦИЯ ВЫВОДА ИТОГОВОЙ ИНФОРМАЦИИ
################################################################################

print_summary() {
    print_header "УСТАНОВКА ЗАВЕРШЕНА"
    
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${NC}  ${WHITE}2GETPRO v2 успешно установлен!${NC}                              ${GREEN}║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo
    
    echo -e "${CYAN}📋 Информация об установке:${NC}"
    echo -e "   Директория: ${WHITE}$PROJECT_DIR${NC}"
    echo -e "   Пользователь: ${WHITE}$SYSTEM_USER${NC}"
    echo -e "   Конфигурация: ${WHITE}$PROJECT_DIR/$ENV_FILE${NC}"
    echo -e "   Логи: ${WHITE}/var/log/2getpro${NC}"
    echo
    
    echo -e "${CYAN}🔐 Данные базы данных:${NC}"
    echo -e "   База данных: ${WHITE}${CONFIG[DB_NAME]}${NC}"
    echo -e "   Пользователь: ${WHITE}${CONFIG[DB_USER]}${NC}"
    echo -e "   Пароль: ${WHITE}${CONFIG[DB_PASSWORD]}${NC}"
    echo -e "   ${YELLOW}⚠ Сохраните эти данные в безопасном месте!${NC}"
    echo
    
    echo -e "${CYAN}🎮 Управление ботом:${NC}"
    echo -e "   Статус:      ${WHITE}systemctl status 2getpro-v2${NC}"
    echo -e "   Запуск:      ${WHITE}systemctl start 2getpro-v2${NC}"
    echo -e "   Остановка:   ${WHITE}systemctl stop 2getpro-v2${NC}"
    echo -e "   Перезапуск:  ${WHITE}systemctl restart 2getpro-v2${NC}"
    echo -e "   Логи:        ${WHITE}journalctl -u 2getpro-v2 -f${NC}"
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
    echo -e "   GitHub: ${WHITE}https://github.com/your-org/2GETPRO_v2${NC}"
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

Автоматический установщик 2GETPRO v2 для Ubuntu 24.04.03 LTS

ОПЦИИ:
    -h, --help              Показать эту справку
    -s, --silent            Тихий режим (без интерактивных запросов)
    -y, --yes               Автоматически отвечать "да" на все вопросы
    -d, --dry-run           Режим проверки без реальных изменений
    -c, --config FILE       Использовать файл конфигурации
    --skip-system-update    Пропустить обновление системы
    --skip-webhooks         Пропустить настройку веб-хуков
    --uninstall             Удалить установленный бот

ПРИМЕРЫ:
    # Интерактивная установка
    sudo $0

    # Тихая установка с автоподтверждением
    sudo $0 --silent --yes

    # Проверка без изменений
    sudo $0 --dry-run

    # Удаление бота
    sudo $0 --uninstall

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
            --uninstall)
                rollback_installation
                exit 0
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
    log "INFO" "Начало установки 2GETPRO v2"
    log "INFO" "=========================================="
    
    # Заголовок
    clear
    echo -e "${CYAN}"
    cat << "EOF"
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║              2GETPRO v2 - Автоматический установщик          ║
║                     Ubuntu 24.04.03 LTS                       ║
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
        echo -e "  • Python 3.11+"
        echo -e "  • PostgreSQL"
        echo -e "  • Redis"
        echo -e "  • Git и системные пакеты"
        if [[ "${CONFIG[SETUP_WEBHOOKS]}" == "true" ]]; then
            echo -e "  • Nginx + SSL сертификат"
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
    print_header "УСТАНОВКА КОМПОНЕНТОВ"
    
    update_system
    install_python
    install_postgresql
    install_redis
    install_git
    install_system_packages
    install_nginx
    
    # Настройка базы данных
    print_header "НАСТРОЙКА БАЗЫ ДАННЫХ"
    setup_database
    
    # Установка бота
    print_header "УСТАНОВКА БОТА"
    
    create_system_user
    clone_repository
    setup_permissions
    create_directories
    create_virtualenv
    install_dependencies
    
    # Генерация конфигурации
    print_header "ГЕНЕРАЦИЯ КОНФИГУРАЦИИ"
    generate_env_file
    
    # Настройка systemd
    print_header "НАСТРОЙКА SYSTEMD"
    setup_systemd_service
    
    # Применение миграций
    print_header "ПРИМЕНЕНИЕ МИГРАЦИЙ"
    apply_migrations
    
    # Настройка веб-хуков
    if [[ "${CONFIG[SETUP_WEBHOOKS]}" == "true" ]]; then
        print_header "НАСТРОЙКА ВЕБ-ХУКОВ"
        setup_nginx_config
        setup_ssl_certificate
    fi
    
    # Запуск бота
    print_header "ЗАПУСК БОТА"
    if ! start_bot_service; then
        print_error "Не удалось запустить бота"
        print_info "Проверьте логи для диагностики проблемы"
        exit 1
    fi
    
    # Проверка установки
    check_installation
    
    # Вывод итоговой информации
    print_summary
    
    log "INFO" "Установка завершена успешно"
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
    
    if [[ "$SKIP_CONFIRMATIONS" == false ]]; then
        read -p "Выполнить откат изменений? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rollback_installation
        fi
    fi
    
    exit $exit_code
}

################################################################################
# ТОЧКА ВХОДА
################################################################################

parse_arguments "$@"
main

exit 0