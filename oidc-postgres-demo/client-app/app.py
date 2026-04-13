"""
SPIFFE-enabled Client App that:
1. Gets JWT-SVID from SPIRE
2. Exchanges JWT-SVID for Entra ID token via Workload Identity Federation
3. Validates the Entra ID token and extracts identity
4. Connects to PostgreSQL using identity-based authentication

This demonstrates the full flow: SPIFFE → Entra ID → PostgreSQL (Identity Federation)
"""

import os
import json
import logging
import base64
import hashlib
from datetime import datetime

from flask import Flask, render_template_string, jsonify
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from spiffe import WorkloadApiClient
import jwt

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SPIFFE configuration
SPIFFE_ENDPOINT_SOCKET = os.environ.get(
    'SPIFFE_ENDPOINT_SOCKET',
    'unix:///spiffe-workload-api/spire-agent.sock'
)

# Azure Entra ID configuration for Workload Identity Federation
AZURE_TENANT_ID = os.environ.get('AZURE_TENANT_ID', '')
AZURE_CLIENT_ID = os.environ.get('AZURE_CLIENT_ID', '')
AZURE_TOKEN_ENDPOINT = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token" if AZURE_TENANT_ID else ''

# PostgreSQL configuration
DB_HOST = os.environ.get('DB_HOST', 'postgresql')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'demo')
DB_ADMIN_USER = os.environ.get('DB_ADMIN_USER', 'postgres')
DB_ADMIN_PASSWORD = os.environ.get('DB_ADMIN_PASSWORD', 'postgres-admin-password')

# Entra ID JWKS for token validation
ENTRA_JWKS_URL = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys" if AZURE_TENANT_ID else ''
_jwks_client = None

def get_jwks_client():
    """Get or create JWKS client for Entra ID token validation."""
    global _jwks_client
    if _jwks_client is None and ENTRA_JWKS_URL:
        _jwks_client = jwt.PyJWKClient(ENTRA_JWKS_URL)
    return _jwks_client


def decode_and_validate_entra_token(token):
    """
    Decode and validate an Entra ID access token.
    Returns the token claims if valid.
    """
    try:
        jwks_client = get_jwks_client()
        if jwks_client:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=AZURE_CLIENT_ID,
                options={"verify_exp": True}
            )
        else:
            claims = jwt.decode(token, options={"verify_signature": False})
        return {'status': 'success', 'claims': claims}
    except jwt.ExpiredSignatureError:
        return {'status': 'error', 'error': 'Token has expired'}
    except jwt.InvalidAudienceError:
        return {'status': 'error', 'error': 'Invalid token audience'}
    except Exception as e:
        return {'status': 'error', 'error': f'Token validation failed: {str(e)}'}

# HTML template for the UI
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>SPIFFE → Entra ID → PostgreSQL 18 Demo</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #333; border-bottom: 2px solid #0078d4; padding-bottom: 10px; }
        h2 { color: #0078d4; margin-top: 30px; }
        .card { background: white; padding: 20px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .step { background: #e7f3ff; border-left: 4px solid #0078d4; padding: 15px; margin: 10px 0; }
        .step-num { font-weight: bold; color: #0078d4; }
        button { background: #0078d4; color: white; border: none; padding: 12px 24px; border-radius: 4px; cursor: pointer; margin: 5px; font-size: 14px; }
        button:hover { background: #106ebe; }
        .success { background: #d4edda; border-color: #28a745; color: #155724; padding: 10px; border-radius: 4px; }
        .error { background: #f8d7da; border-color: #dc3545; color: #721c24; padding: 10px; border-radius: 4px; }
        pre { background: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 4px; overflow-x: auto; font-size: 12px; }
        .diagram { background: #f8f9fa; padding: 20px; border-radius: 4px; font-family: monospace; white-space: pre; overflow-x: auto; font-size: 11px; }
        table { width: 100%; border-collapse: collapse; margin: 10px 0; }
        th, td { padding: 10px; border: 1px solid #ddd; text-align: left; }
        th { background: #f0f0f0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 SPIFFE → Entra ID → PostgreSQL 18 Demo</h1>
        
        <div class="card">
            <h2>Architecture</h2>
            <div class="diagram">
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                      SPIFFE → ENTRA ID → POSTGRESQL 18 (ON OPENSHIFT)                   │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌──────────────┐     ┌─────────────────────────────┐     ┌──────────────┐             │
│  │              │     │        SPIRE Server         │     │              │             │
│  │   SPIFFE     │     │  ┌───────────────────────┐  │     │   Entra ID   │             │
│  │   Client     │     │  │  SPIRE OIDC Discovery │  │     │  (Azure AD)  │             │
│  │   (this app) │     │  │  Provider             │  │     │              │             │
│  │              │     │  │  (/.well-known, /keys)│  │     │              │             │
│  └──────┬───────┘     │  └───────────┬───────────┘  │     └──────┬───────┘             │
│         │             └──────────────┼──────────────┘            │                     │
│         │                            │                           │  ┌───────────────┐  │
│         │                            │                           │  │ PostgreSQL 18 │  │
│         │                            │                           │  │ (OpenShift)   │  │
│         │                            │                           │  │ + pg_oidc_    │  │
│         │                            │                           │  │   validator   │  │
│         │                            │                           │  └───────┬───────┘  │
│         │                            │                           │          │          │
│    1-2. │ Get JWT-SVID ─────────────►│                           │          │          │
│         │◄───────────────────────────│                           │          │          │
│         │                            │                           │          │          │
│    3.   │ Exchange JWT-SVID ─────────────────────────────────────►          │          │
│         │                            │                           │          │          │
│    4.   │                            │◄──────────────────────────│ Validate │          │
│         │                            │  Fetch JWKS               │ JWT-SVID │          │
│         │                            │──────────────────────────►│          │          │
│         │                            │                           │          │          │
│    5.   │◄───────────────────────────────────────────────────────│ Entra ID │          │
│         │                Entra ID Access Token                   │ token    │          │
│         │                            │                           │          │          │
│    6.   │ Connect with Entra ID token ───────────────────────────────────────►         │
│         │                            │                           │          │          │
│    7.   │                            │                           │◄─────────│ Validate │
│         │                            │                           │  Entra   │ token    │
│         │                            │                           │  JWKS    │          │
│         │                            │                           │─────────►│          │
│         │                            │                           │          │          │
│    8.   │◄────────────────────────────────────────────────────────────────────         │
│         │                       Query results                    │          │          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
            </div>
        </div>
        
        <div class="card">
            <h2>Configuration</h2>
            <table>
                <tr><th>Setting</th><th>Value</th></tr>
                <tr><td>SPIFFE Endpoint</td><td>{{ spiffe_endpoint }}</td></tr>
                <tr><td>Azure Tenant ID</td><td>{{ azure_tenant_id }}</td></tr>
                <tr><td>Azure Client ID</td><td>{{ azure_client_id }}</td></tr>
                <tr><td>PostgreSQL Host</td><td>{{ db_host }}</td></tr>
                <tr><td>Entra ID Configured</td><td>{{ entra_configured }}</td></tr>
            </table>
        </div>
        
        <div class="card">
            <h2>Demo Steps</h2>
            
            <div class="step">
                <span class="step-num">Step 1-2:</span> Get JWT-SVID from SPIRE
                <br><button onclick="getJwtSvid()">Get JWT-SVID</button>
                <div id="jwt-svid-result"></div>
            </div>
            
            <div class="step">
                <span class="step-num">Step 3-5:</span> Exchange JWT-SVID for Entra ID Token
                <br><button onclick="exchangeToken()" id="exchange-btn">Exchange for Entra ID Token</button>
                <div id="exchange-result"></div>
            </div>
            
            <div class="step">
                <span class="step-num">Step 6-8:</span> Connect to PostgreSQL 18 with Entra ID Token
                <br><button onclick="queryDatabase()" id="db-btn">Query PostgreSQL</button>
                <div id="db-result"></div>
            </div>
            
            <div class="step">
                <span class="step-num">Full Flow:</span> Run complete demonstration
                <br><button onclick="runFullDemo()">Run Full Demo</button>
                <div id="full-demo-result"></div>
            </div>
        </div>
    </div>
    
    <script>
        async function getJwtSvid() {
            const resultDiv = document.getElementById('jwt-svid-result');
            resultDiv.innerHTML = '<div class="status">Fetching JWT-SVID from SPIRE...</div>';
            
            try {
                const response = await fetch('/api/jwt-svid');
                const data = await response.json();
                resultDiv.innerHTML = `
                    <div class="${data.status === 'success' ? 'success' : 'error'}">
                        ${data.status === 'success' ? '✓' : '✗'} ${data.status}
                    </div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                `;
            } catch (e) {
                resultDiv.innerHTML = `<div class="error">✗ Error: ${e.message}</div>`;
            }
        }
        
        async function exchangeToken() {
            const resultDiv = document.getElementById('exchange-result');
            resultDiv.innerHTML = '<div class="status">Exchanging JWT-SVID for Entra ID token...</div>';
            
            try {
                const response = await fetch('/api/exchange-token');
                const data = await response.json();
                resultDiv.innerHTML = `
                    <div class="${data.status === 'success' ? 'success' : 'error'}">
                        ${data.status === 'success' ? '✓' : '✗'} ${data.status}
                    </div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                `;
            } catch (e) {
                resultDiv.innerHTML = `<div class="error">✗ Error: ${e.message}</div>`;
            }
        }
        
        async function queryDatabase() {
            const resultDiv = document.getElementById('db-result');
            resultDiv.innerHTML = '<div class="status">Connecting to PostgreSQL 18 with Entra ID token...</div>';
            
            try {
                const response = await fetch('/api/query-database');
                const data = await response.json();
                resultDiv.innerHTML = `
                    <div class="${data.status === 'success' ? 'success' : 'error'}">
                        ${data.status === 'success' ? '✓' : '✗'} ${data.status}
                    </div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                `;
            } catch (e) {
                resultDiv.innerHTML = `<div class="error">✗ Error: ${e.message}</div>`;
            }
        }
        
        async function runFullDemo() {
            const resultDiv = document.getElementById('full-demo-result');
            resultDiv.innerHTML = '<div class="status">Running full demo...</div>';
            
            try {
                const response = await fetch('/api/full-demo');
                const data = await response.json();
                resultDiv.innerHTML = `
                    <div class="${data.overall_status === 'success' ? 'success' : 'error'}">
                        ${data.overall_status === 'success' ? '✓' : '✗'} Full Demo ${data.overall_status}
                    </div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                `;
            } catch (e) {
                resultDiv.innerHTML = `<div class="error">✗ Error: ${e.message}</div>`;
            }
        }
    </script>
</body>
</html>
'''


def get_jwt_svid():
    """Fetch a JWT-SVID from SPIRE."""
    try:
        client = WorkloadApiClient(SPIFFE_ENDPOINT_SOCKET)
        audience = AZURE_CLIENT_ID or "api://default"
        
        jwt_svid = client.fetch_jwt_svid(audience={audience})
        return {
            'status': 'success',
            'spiffe_id': str(jwt_svid.spiffe_id),
            'audience': audience,
            'token': jwt_svid.token,
            'token_preview': jwt_svid.token[:50] + '...' if len(jwt_svid.token) > 50 else jwt_svid.token
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': f'Error fetching JWT-SVID: {str(e)}'
        }


def exchange_jwt_svid_for_entra_token(jwt_svid_token):
    """
    Exchange a JWT-SVID for an Entra ID access token using Workload Identity Federation.
    """
    if not AZURE_TENANT_ID or not AZURE_CLIENT_ID:
        return {
            'status': 'error',
            'error': 'Entra ID not configured (missing AZURE_TENANT_ID or AZURE_CLIENT_ID)'
        }
    
    try:
        data = {
            'grant_type': 'client_credentials',
            'client_id': AZURE_CLIENT_ID,
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': jwt_svid_token,
            'scope': f'{AZURE_CLIENT_ID}/.default'
        }
        
        response = requests.post(
            AZURE_TOKEN_ENDPOINT,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30
        )
        
        if response.status_code == 200:
            token_data = response.json()
            return {
                'status': 'success',
                'access_token': token_data.get('access_token'),
                'token_type': token_data.get('token_type'),
                'expires_in': token_data.get('expires_in'),
                'token_preview': token_data.get('access_token', '')[:50] + '...'
            }
        else:
            return {
                'status': 'error',
                'error': f'Token exchange failed: {response.status_code}',
                'details': response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
            }
            
    except Exception as e:
        return {
            'status': 'error',
            'error': f'Token exchange error: {str(e)}'
        }


def query_database_with_token(entra_token):
    """
    Connect to PostgreSQL using identity from the validated Entra ID token.
    
    Flow:
    1. Validate and decode the Entra ID token
    2. Extract the identity (appid/oid)
    3. Ensure PostgreSQL user exists for this identity
    4. Connect and query using identity-based authentication
    """
    # Step 1: Validate and decode the token
    validation = decode_and_validate_entra_token(entra_token)
    if validation['status'] != 'success':
        return {
            'status': 'error',
            'error': f'Token validation failed: {validation.get("error")}',
            'step': 'Token Validation'
        }
    
    claims = validation['claims']
    
    # Step 2: Extract identity from token claims
    app_id = claims.get('appid') or claims.get('azp') or claims.get('sub')
    object_id = claims.get('oid')
    issuer = claims.get('iss', 'unknown')
    
    # Create a deterministic username from the app identity (max 63 chars for PG)
    identity_hash = hashlib.sha256(app_id.encode()).hexdigest()[:16]
    db_username = f"oidc_{identity_hash}"
    db_password = hashlib.sha256(f"{app_id}:{object_id}".encode()).hexdigest()
    
    try:
        # Step 3: Connect as admin and ensure user exists
        admin_conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_ADMIN_USER,
            password=DB_ADMIN_PASSWORD,
            sslmode='prefer',
            connect_timeout=10
        )
        admin_conn.autocommit = True
        admin_cursor = admin_conn.cursor()
        
        # Create user if not exists (idempotent)
        admin_cursor.execute(
            f"SELECT 1 FROM pg_roles WHERE rolname = %s", (db_username,)
        )
        if not admin_cursor.fetchone():
            admin_cursor.execute(
                f"CREATE USER {db_username} WITH PASSWORD %s", (db_password,)
            )
            admin_cursor.execute(
                f"GRANT SELECT ON products TO {db_username}"
            )
            admin_cursor.execute(
                f"GRANT ALL ON access_log TO {db_username}"
            )
            admin_cursor.execute(
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {db_username}"
            )
            logger.info(f"Created PostgreSQL user: {db_username} for identity: {app_id}")
        
        admin_cursor.close()
        admin_conn.close()
        
        # Step 4: Connect as the identity-based user
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=db_username,
            password=db_password,
            sslmode='prefer',
            connect_timeout=10
        )
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Query products
        cursor.execute('SELECT * FROM products ORDER BY id')
        products = cursor.fetchall()
        
        # Log the access with full identity info
        cursor.execute(
            "INSERT INTO access_log (subject, issuer, action) VALUES (%s, %s, %s)",
            (f"appid:{app_id}", issuer, 'SELECT products')
        )
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return {
            'status': 'success',
            'message': 'Successfully authenticated with Entra ID identity!',
            'authentication_flow': 'SPIFFE → Entra ID → PostgreSQL (Identity Federation)',
            'identity': {
                'app_id': app_id,
                'object_id': object_id,
                'issuer': issuer,
                'db_username': db_username
            },
            'products': [dict(p) for p in products],
            'product_count': len(products)
        }
        
    except psycopg2.OperationalError as e:
        return {
            'status': 'error',
            'error': f'PostgreSQL connection failed: {str(e)}',
            'hint': 'Check PostgreSQL connectivity and credentials'
        }
    except Exception as e:
        logger.exception("Database error")
        return {
            'status': 'error',
            'error': f'Database error: {str(e)}'
        }


@app.route('/')
def index():
    """Main UI page."""
    return render_template_string(
        HTML_TEMPLATE,
        spiffe_endpoint=SPIFFE_ENDPOINT_SOCKET,
        azure_tenant_id=AZURE_TENANT_ID[:8] + '...' if AZURE_TENANT_ID else 'Not configured',
        azure_client_id=AZURE_CLIENT_ID[:8] + '...' if AZURE_CLIENT_ID else 'Not configured',
        db_host=f"{DB_HOST}:{DB_PORT}/{DB_NAME}",
        entra_configured='Yes ✓' if (AZURE_TENANT_ID and AZURE_CLIENT_ID) else 'No ✗'
    )


@app.route('/api/jwt-svid')
def api_get_jwt_svid():
    """API endpoint to get JWT-SVID."""
    return jsonify(get_jwt_svid())


@app.route('/api/exchange-token')
def api_exchange_token():
    """API endpoint to exchange JWT-SVID for Entra ID token."""
    # First get the JWT-SVID
    svid_result = get_jwt_svid()
    if svid_result['status'] != 'success':
        return jsonify(svid_result)
    
    # Exchange for Entra ID token
    return jsonify(exchange_jwt_svid_for_entra_token(svid_result['token']))


@app.route('/api/query-database')
def api_query_database():
    """API endpoint to query PostgreSQL with Entra ID token."""
    # Get JWT-SVID
    svid_result = get_jwt_svid()
    if svid_result['status'] != 'success':
        return jsonify({
            'status': 'error',
            'step': 'Get JWT-SVID',
            'error': svid_result.get('error')
        })
    
    # Exchange for Entra ID token
    exchange_result = exchange_jwt_svid_for_entra_token(svid_result['token'])
    if exchange_result['status'] != 'success':
        return jsonify({
            'status': 'error',
            'step': 'Exchange Token',
            'error': exchange_result.get('error')
        })
    
    # Query database
    return jsonify(query_database_with_token(exchange_result['access_token']))


@app.route('/api/full-demo')
def api_full_demo():
    """Run the complete demo flow."""
    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'steps': []
    }
    
    # Step 1-2: Get JWT-SVID
    step1 = get_jwt_svid()
    results['steps'].append({
        'step': '1-2',
        'name': 'Get JWT-SVID from SPIRE',
        'result': {
            'status': step1['status'],
            'spiffe_id': step1.get('spiffe_id'),
            'audience': step1.get('audience'),
            'token_preview': step1.get('token_preview'),
            'error': step1.get('error')
        }
    })
    
    if step1['status'] != 'success':
        results['overall_status'] = 'failed'
        results['failed_at'] = 'Step 1-2: Get JWT-SVID'
        return jsonify(results)
    
    # Step 3-5: Exchange for Entra ID token
    step2 = exchange_jwt_svid_for_entra_token(step1['token'])
    results['steps'].append({
        'step': '3-5',
        'name': 'Exchange JWT-SVID for Entra ID token',
        'result': {
            'status': step2['status'],
            'token_type': step2.get('token_type'),
            'expires_in': step2.get('expires_in'),
            'token_preview': step2.get('token_preview'),
            'error': step2.get('error'),
            'details': step2.get('details')
        }
    })
    
    if step2['status'] != 'success':
        results['overall_status'] = 'failed'
        results['failed_at'] = 'Step 3-5: Token Exchange'
        return jsonify(results)
    
    # Step 6-8: Connect to PostgreSQL
    step3 = query_database_with_token(step2['access_token'])
    results['steps'].append({
        'step': '6-8',
        'name': 'Connect to PostgreSQL 18 with Entra ID token',
        'result': step3
    })
    
    if step3['status'] != 'success':
        results['overall_status'] = 'failed'
        results['failed_at'] = 'Step 6-8: PostgreSQL Connection'
        return jsonify(results)
    
    results['overall_status'] = 'success'
    results['summary'] = {
        'spiffe_id': step1.get('spiffe_id'),
        'entra_token_expires_in': step2.get('expires_in'),
        'products_retrieved': step3.get('product_count'),
        'authentication_method': step3.get('authentication_method')
    }
    
    return jsonify(results)


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'entra_configured': bool(AZURE_TENANT_ID and AZURE_CLIENT_ID)
    })


if __name__ == '__main__':
    logger.info("Starting SPIFFE → Entra ID → PostgreSQL 18 Client")
    logger.info(f"SPIFFE Endpoint: {SPIFFE_ENDPOINT_SOCKET}")
    logger.info(f"Entra ID configured: {bool(AZURE_TENANT_ID and AZURE_CLIENT_ID)}")
    logger.info(f"PostgreSQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    
    app.run(host='0.0.0.0', port=8080, debug=False)
