#!/bin/sh
echo "=== QuickTrack Entrypoint ==="
echo "Esperando o banco de dados PostgreSQL..."

python - <<END
import time
import os
import psycopg2

max_retries = 30
retry = 0

while retry < max_retries:
    try:
        conn = psycopg2.connect(
            dbname=os.environ.get('DB_NAME', 'quicktrack_homolog'),
            user=os.environ.get('DB_USER', 'quicktrack'),
            password=os.environ.get('DB_PASSWORD', ''),
            host=os.environ.get('DB_HOST', 'qt_homolog_postgres'),
            port=int(os.environ.get('DB_PORT', 5432)),
            connect_timeout=5
        )
        conn.close()
        print("Conexão estabelecida com sucesso!")
        break
    except Exception as e:
        retry += 1
        print(f"Tentativa {retry}/{max_retries} - Aguardando PostgreSQL: {e}")
        time.sleep(2)

if retry >= max_retries:
    print("ERRO: Não foi possível conectar ao banco de dados.")
    exit(1)
END

echo "Banco pronto!"

# ============================================================
# SETUP AUTOMÁTICO (apenas no container backend principal)
# A variável RUN_SETUP=true é definida SOMENTE no service backend
# do docker-compose.yml. Celery workers/beat NÃO a possuem.
# ============================================================
if [ "$RUN_SETUP" = "true" ]; then
    echo ">>> Rodando migrações do banco de dados..."
    python manage.py migrate --noinput

    echo ">>> Coletando arquivos estáticos..."
    python manage.py collectstatic --noinput

    echo ">>> Configurando superusuário privado..."
    python manage.py setup_private_admin

    echo "=== Setup completo! ==="
fi

echo "Executando comando: $@"
exec "$@"
