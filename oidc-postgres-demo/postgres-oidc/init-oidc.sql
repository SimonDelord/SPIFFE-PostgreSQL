-- Initialize database for OIDC authentication demo
-- This script runs when the PostgreSQL container first starts

-- Create the demo database
CREATE DATABASE demo;

-- Connect to demo database
\c demo

-- Create a shared role for all OIDC-authenticated users
-- Users authenticate via OIDC but connect as this shared role
CREATE ROLE oidc_users WITH LOGIN;

-- Create demo table
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create access log table
CREATE TABLE access_log (
    id SERIAL PRIMARY KEY,
    subject VARCHAR(255),
    issuer VARCHAR(255),
    action VARCHAR(100),
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Grant permissions to oidc_users role
GRANT SELECT ON products TO oidc_users;
GRANT ALL ON access_log TO oidc_users;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO oidc_users;

-- Insert sample data
INSERT INTO products (name, price) VALUES 
    ('Widget A', 19.99),
    ('Widget B', 29.99),
    ('Widget C', 39.99);

-- Log that initialization completed
INSERT INTO access_log (subject, issuer, action) VALUES 
    ('system', 'init', 'Database initialized for OIDC authentication');
