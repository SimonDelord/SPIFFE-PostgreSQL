"""
API Server that validates OIDC tokens (from Entra ID) and queries PostgreSQL.

Flow:
1. Client sends request with Authorization: Bearer <entra_id_token>
2. API Server validates the token against Entra ID OIDC endpoints
3. If valid, API Server queries PostgreSQL and returns data
4. Access is logged to the database
"""

import os
import json
import logging
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import jwt
from jwt import PyJWKClient

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment variables
AZURE_TENANT_ID = os.environ.get('AZURE_TENANT_ID', '')
AZURE_CLIENT_ID = os.environ.get('AZURE_CLIENT_ID', '')
AZURE_ISSUER = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/v2.0" if AZURE_TENANT_ID else ''
AZURE_JWKS_URL = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys" if AZURE_TENANT_ID else ''

# PostgreSQL configuration
DB_HOST = os.environ.get('DB_HOST', 'postgresql')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'demo')
DB_USER = os.environ.get('DB_USER', 'apiserver')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'apiserver-secret-password')

# JWKS client for token validation
jwks_client = None


def get_db_connection():
    """Create a database connection."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


def init_jwks_client():
    """Initialize the JWKS client for Entra ID."""
    global jwks_client
    if AZURE_JWKS_URL and not jwks_client:
        try:
            jwks_client = PyJWKClient(AZURE_JWKS_URL)
            logger.info(f"JWKS client initialized for {AZURE_JWKS_URL}")
        except Exception as e:
            logger.error(f"Failed to initialize JWKS client: {e}")


def validate_entra_id_token(token):
    """
    Validate an Entra ID access token.
    
    Returns:
        tuple: (is_valid, claims_or_error)
    """
    if not AZURE_TENANT_ID or not AZURE_CLIENT_ID:
        return False, "Entra ID not configured (missing AZURE_TENANT_ID or AZURE_CLIENT_ID)"
    
    init_jwks_client()
    
    if not jwks_client:
        return False, "JWKS client not available"
    
    try:
        # Get the signing key from JWKS
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        
        # Decode and validate the token
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=AZURE_CLIENT_ID,
            issuer=AZURE_ISSUER,
            options={
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
            }
        )
        
        return True, claims
        
    except jwt.ExpiredSignatureError:
        return False, "Token has expired"
    except jwt.InvalidAudienceError:
        return False, f"Invalid audience (expected: {AZURE_CLIENT_ID})"
    except jwt.InvalidIssuerError:
        return False, f"Invalid issuer (expected: {AZURE_ISSUER})"
    except jwt.InvalidTokenError as e:
        return False, f"Invalid token: {str(e)}"
    except Exception as e:
        return False, f"Token validation error: {str(e)}"


def log_access(subject, issuer, action):
    """Log access to the database."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO access_log (subject, issuer, action) VALUES (%s, %s, %s)",
            (subject, issuer, action)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log access: {e}")


def require_auth(f):
    """Decorator to require OIDC authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return jsonify({
                'error': 'unauthorized',
                'message': 'Missing or invalid Authorization header'
            }), 401
        
        token = auth_header[7:]  # Remove 'Bearer ' prefix
        
        is_valid, result = validate_entra_id_token(token)
        
        if not is_valid:
            return jsonify({
                'error': 'unauthorized',
                'message': result
            }), 401
        
        # Token is valid, add claims to request context
        request.token_claims = result
        request.token_subject = result.get('sub', 'unknown')
        request.token_issuer = result.get('iss', 'unknown')
        
        return f(*args, **kwargs)
    
    return decorated


@app.route('/')
def index():
    """Home page with API info."""
    return jsonify({
        'service': 'OIDC PostgreSQL API Server',
        'description': 'API Server that validates Entra ID tokens and provides access to PostgreSQL data',
        'endpoints': {
            '/': 'This info page',
            '/health': 'Health check',
            '/config': 'Current configuration',
            '/api/products': 'Get products (requires Entra ID token)',
            '/api/products/<id>': 'Get specific product (requires Entra ID token)',
            '/api/access-log': 'Get access log (requires Entra ID token)'
        },
        'authentication': 'Bearer token (Entra ID access token)',
        'entra_id_configured': bool(AZURE_TENANT_ID and AZURE_CLIENT_ID)
    })


@app.route('/health')
def health():
    """Health check endpoint."""
    db_status = 'healthy'
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.close()
        conn.close()
    except Exception as e:
        db_status = f'unhealthy: {str(e)}'
    
    return jsonify({
        'status': 'healthy',
        'database': db_status,
        'entra_id_configured': bool(AZURE_TENANT_ID and AZURE_CLIENT_ID),
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/config')
def config():
    """Show current configuration (safe values only)."""
    return jsonify({
        'azure_tenant_id': AZURE_TENANT_ID[:8] + '...' if AZURE_TENANT_ID else 'not configured',
        'azure_client_id': AZURE_CLIENT_ID[:8] + '...' if AZURE_CLIENT_ID else 'not configured',
        'azure_issuer': AZURE_ISSUER or 'not configured',
        'azure_jwks_url': AZURE_JWKS_URL or 'not configured',
        'db_host': DB_HOST,
        'db_name': DB_NAME
    })


@app.route('/api/products')
@require_auth
def get_products():
    """Get all products (requires authentication)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM products ORDER BY id')
        products = cur.fetchall()
        cur.close()
        conn.close()
        
        # Log access
        log_access(
            request.token_subject,
            request.token_issuer,
            'GET /api/products'
        )
        
        return jsonify({
            'authenticated_as': request.token_subject,
            'issuer': request.token_issuer,
            'products': [dict(p) for p in products],
            'count': len(products)
        })
        
    except Exception as e:
        return jsonify({
            'error': 'database_error',
            'message': str(e)
        }), 500


@app.route('/api/products/<int:product_id>')
@require_auth
def get_product(product_id):
    """Get a specific product (requires authentication)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM products WHERE id = %s', (product_id,))
        product = cur.fetchone()
        cur.close()
        conn.close()
        
        if not product:
            return jsonify({
                'error': 'not_found',
                'message': f'Product {product_id} not found'
            }), 404
        
        # Log access
        log_access(
            request.token_subject,
            request.token_issuer,
            f'GET /api/products/{product_id}'
        )
        
        return jsonify({
            'authenticated_as': request.token_subject,
            'issuer': request.token_issuer,
            'product': dict(product)
        })
        
    except Exception as e:
        return jsonify({
            'error': 'database_error',
            'message': str(e)
        }), 500


@app.route('/api/access-log')
@require_auth
def get_access_log():
    """Get access log (requires authentication)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM access_log ORDER BY timestamp DESC LIMIT 50')
        logs = cur.fetchall()
        cur.close()
        conn.close()
        
        # Log this access too
        log_access(
            request.token_subject,
            request.token_issuer,
            'GET /api/access-log'
        )
        
        return jsonify({
            'authenticated_as': request.token_subject,
            'issuer': request.token_issuer,
            'access_log': [dict(l) for l in logs],
            'count': len(logs)
        })
        
    except Exception as e:
        return jsonify({
            'error': 'database_error',
            'message': str(e)
        }), 500


if __name__ == '__main__':
    logger.info(f"Starting API Server")
    logger.info(f"Entra ID configured: {bool(AZURE_TENANT_ID and AZURE_CLIENT_ID)}")
    if AZURE_TENANT_ID:
        logger.info(f"Tenant ID: {AZURE_TENANT_ID[:8]}...")
        logger.info(f"JWKS URL: {AZURE_JWKS_URL}")
    
    app.run(host='0.0.0.0', port=8080, debug=False)
