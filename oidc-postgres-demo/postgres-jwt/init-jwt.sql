-- PostgreSQL JWT Validation Setup for Entra ID
-- This enables PostgreSQL to validate Entra ID access tokens directly
-- and provide authorization via Row-Level Security (RLS)

-- Create the demo database
CREATE DATABASE demo;
\c demo

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pgjwt;

-- Store Entra ID JWKS (public keys) - will be populated by the app
CREATE TABLE jwt_keys (
    kid VARCHAR(100) PRIMARY KEY,
    key_data TEXT NOT NULL,
    key_type VARCHAR(10) DEFAULT 'RSA',
    algorithm VARCHAR(20) DEFAULT 'RS256',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

-- Store the current session's validated token claims
CREATE TABLE current_session (
    session_id TEXT PRIMARY KEY DEFAULT current_setting('app.session_id', true),
    token_sub TEXT,
    token_oid TEXT,
    token_appid TEXT,
    token_name TEXT,
    token_roles TEXT[],
    token_iss TEXT,
    token_aud TEXT,
    validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Products table with RLS
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    category VARCHAR(50),
    restricted BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Access log
CREATE TABLE access_log (
    id SERIAL PRIMARY KEY,
    token_sub TEXT,
    token_appid TEXT,
    action VARCHAR(100),
    details TEXT,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Function to validate an Entra ID JWT
-- Returns the decoded payload if valid, NULL if invalid
CREATE OR REPLACE FUNCTION validate_entra_token(token TEXT, expected_audience TEXT)
RETURNS JSONB AS $$
DECLARE
    header JSONB;
    payload JSONB;
    token_parts TEXT[];
    decoded_header TEXT;
    decoded_payload TEXT;
    token_iss TEXT;
    token_aud TEXT;
    token_exp BIGINT;
    now_epoch BIGINT;
BEGIN
    -- Split token into parts
    token_parts := string_to_array(token, '.');
    IF array_length(token_parts, 1) != 3 THEN
        RAISE NOTICE 'Invalid token format';
        RETURN NULL;
    END IF;
    
    -- Decode header and payload (base64url decode)
    decoded_header := convert_from(
        decode(
            replace(replace(token_parts[1], '-', '+'), '_', '/') || 
            repeat('=', (4 - length(token_parts[1]) % 4) % 4),
            'base64'
        ),
        'UTF8'
    );
    
    decoded_payload := convert_from(
        decode(
            replace(replace(token_parts[2], '-', '+'), '_', '/') || 
            repeat('=', (4 - length(token_parts[2]) % 4) % 4),
            'base64'
        ),
        'UTF8'
    );
    
    header := decoded_header::JSONB;
    payload := decoded_payload::JSONB;
    
    -- Extract and validate claims
    token_iss := payload->>'iss';
    token_aud := payload->>'aud';
    token_exp := (payload->>'exp')::BIGINT;
    now_epoch := EXTRACT(EPOCH FROM NOW())::BIGINT;
    
    -- Check issuer (must be from our Entra ID tenant)
    IF token_iss NOT LIKE 'https://login.microsoftonline.com/%' AND 
       token_iss NOT LIKE 'https://sts.windows.net/%' THEN
        RAISE NOTICE 'Invalid issuer: %', token_iss;
        RETURN NULL;
    END IF;
    
    -- Check audience
    IF token_aud != expected_audience THEN
        RAISE NOTICE 'Invalid audience: % (expected %)', token_aud, expected_audience;
        RETURN NULL;
    END IF;
    
    -- Check expiration
    IF token_exp < now_epoch THEN
        RAISE NOTICE 'Token expired at %, current time %', token_exp, now_epoch;
        RETURN NULL;
    END IF;
    
    -- Note: Full signature verification requires fetching JWKS from Entra ID
    -- For this demo, we verify the claims but trust the token structure
    -- In production, implement full RS256 signature verification
    
    RETURN payload;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to set the current session token and validate it
CREATE OR REPLACE FUNCTION set_session_token(token TEXT, audience TEXT DEFAULT 'f63d6f2e-f780-4568-a69a-93a07cd8c5db')
RETURNS BOOLEAN AS $$
DECLARE
    payload JSONB;
    session_id TEXT;
BEGIN
    -- Validate the token
    payload := validate_entra_token(token, audience);
    
    IF payload IS NULL THEN
        RAISE EXCEPTION 'Invalid or expired token';
    END IF;
    
    -- Generate session ID
    session_id := gen_random_uuid()::TEXT;
    
    -- Set session variables
    PERFORM set_config('app.session_id', session_id, false);
    PERFORM set_config('app.token_sub', COALESCE(payload->>'sub', ''), false);
    PERFORM set_config('app.token_oid', COALESCE(payload->>'oid', ''), false);
    PERFORM set_config('app.token_appid', COALESCE(payload->>'appid', payload->>'azp', ''), false);
    PERFORM set_config('app.token_name', COALESCE(payload->>'name', payload->>'preferred_username', 'unknown'), false);
    PERFORM set_config('app.token_iss', COALESCE(payload->>'iss', ''), false);
    PERFORM set_config('app.token_validated', 'true', false);
    
    -- Log the access
    INSERT INTO access_log (token_sub, token_appid, action, details)
    VALUES (
        payload->>'sub',
        COALESCE(payload->>'appid', payload->>'azp'),
        'TOKEN_VALIDATED',
        jsonb_build_object(
            'iss', payload->>'iss',
            'aud', payload->>'aud',
            'exp', payload->>'exp'
        )::TEXT
    );
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to check if current session has a valid token
CREATE OR REPLACE FUNCTION is_token_validated()
RETURNS BOOLEAN AS $$
BEGIN
    RETURN current_setting('app.token_validated', true) = 'true';
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to get current token's app ID
CREATE OR REPLACE FUNCTION current_token_appid()
RETURNS TEXT AS $$
BEGIN
    RETURN current_setting('app.token_appid', true);
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to get current token's subject
CREATE OR REPLACE FUNCTION current_token_sub()
RETURNS TEXT AS $$
BEGIN
    RETURN current_setting('app.token_sub', true);
END;
$$ LANGUAGE plpgsql STABLE;

-- Enable Row-Level Security on products table
ALTER TABLE products ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Allow SELECT only if token is validated
CREATE POLICY products_select_policy ON products
    FOR SELECT
    USING (is_token_validated());

-- RLS Policy: Allow INSERT/UPDATE/DELETE only for specific app IDs (admin apps)
-- For demo: Allow any validated token to read, but restrict writes
CREATE POLICY products_modify_policy ON products
    FOR ALL
    USING (
        is_token_validated() AND 
        current_token_appid() IN ('admin-app-id-here')  -- Restrict writes to admin apps
    );

-- Create a role for the client app
CREATE ROLE jwt_client WITH LOGIN PASSWORD 'jwt-client-password';

-- Grant necessary permissions
GRANT USAGE ON SCHEMA public TO jwt_client;
GRANT SELECT, INSERT ON products TO jwt_client;
GRANT SELECT, INSERT ON access_log TO jwt_client;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO jwt_client;
GRANT EXECUTE ON FUNCTION validate_entra_token(TEXT, TEXT) TO jwt_client;
GRANT EXECUTE ON FUNCTION set_session_token(TEXT, TEXT) TO jwt_client;
GRANT EXECUTE ON FUNCTION is_token_validated() TO jwt_client;
GRANT EXECUTE ON FUNCTION current_token_appid() TO jwt_client;
GRANT EXECUTE ON FUNCTION current_token_sub() TO jwt_client;

-- Insert sample data
INSERT INTO products (name, price, category, restricted) VALUES 
    ('Widget A', 19.99, 'electronics', false),
    ('Widget B', 29.99, 'electronics', false),
    ('Widget C', 39.99, 'electronics', false),
    ('Secret Widget', 999.99, 'classified', true),
    ('Premium Widget', 149.99, 'premium', true);

-- Log initialization
INSERT INTO access_log (token_sub, token_appid, action, details)
VALUES ('system', 'init', 'DATABASE_INITIALIZED', 'PostgreSQL JWT validation setup complete');
