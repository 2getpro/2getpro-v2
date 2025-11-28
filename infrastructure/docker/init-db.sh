#!/bin/bash
set -e

# Скрипт инициализации базы данных PostgreSQL
# Создаёт БД если она не существует

echo "Проверка существования базы данных..."

# Получаем имя базы данных из переменной окружения
DB_NAME="${POSTGRES_DB:-user}"

# Проверяем существование БД
if psql -U "$POSTGRES_USER" -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo "База данных '$DB_NAME' уже существует"
else
    echo "Создание базы данных '$DB_NAME'..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
        CREATE DATABASE "$DB_NAME";
        GRANT ALL PRIVILEGES ON DATABASE "$DB_NAME" TO "$POSTGRES_USER";
EOSQL
    echo "База данных '$DB_NAME' успешно создана"
fi

echo "Инициализация завершена"