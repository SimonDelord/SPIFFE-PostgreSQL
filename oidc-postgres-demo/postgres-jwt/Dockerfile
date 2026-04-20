# PostgreSQL 16 with pgjwt extension for JWT validation
# pgjwt allows PostgreSQL to verify and decode JWTs directly
FROM postgres:16

# Install build dependencies for pgjwt
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    postgresql-server-dev-16 \
    && rm -rf /var/lib/apt/lists/*

# Clone and install pgjwt extension
RUN git clone https://github.com/michelp/pgjwt.git /tmp/pgjwt \
    && cd /tmp/pgjwt \
    && make \
    && make install \
    && rm -rf /tmp/pgjwt

# Copy initialization scripts
COPY init-jwt.sql /docker-entrypoint-initdb.d/
