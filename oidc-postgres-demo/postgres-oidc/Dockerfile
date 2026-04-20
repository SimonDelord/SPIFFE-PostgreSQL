# PostgreSQL 18 with pg_oidc_validator for native OIDC authentication
FROM postgres:18

# Install required packages
RUN apt-get update && apt-get install -y \
    wget \
    libpq-oauth \
    && rm -rf /var/lib/apt/lists/*

# Download and install pg_oidc_validator from Percona
RUN wget -q https://github.com/Percona-Lab/pg_oidc_validator/releases/download/latest/pg-oidc-validator-pgdg18.deb \
    && dpkg -i pg-oidc-validator-pgdg18.deb \
    && rm pg-oidc-validator-pgdg18.deb

# Copy initialization scripts
COPY init-oidc.sql /docker-entrypoint-initdb.d/

# The configuration will be mounted via ConfigMap
