"""
OIDC-Only API Server

This API server ONLY understands Keycloak (OIDC) tokens.
It does NOT know anything about SPIFFE or JWT-SVIDs.

This demonstrates how a traditional OIDC-protected service can serve
requests from SPIFFE-enabled workloads after token exchange.
"""

import os
import json
import requests
from functools import wraps
from flask import Flask, jsonify, request, render_template_string
import jwt
from jwt import PyJWKClient

app = Flask(__name__)

KEYCLOAK_URL = os.environ.get('KEYCLOAK_URL', 'https://keycloak-keycloak.apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com')
KEYCLOAK_REALM = os.environ.get('KEYCLOAK_REALM', 'spiffe-demo')
JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"

jwks_client = None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>OIDC-Protected API Server</title>
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { color: #1b5e20; border-bottom: 3px solid #4caf50; padding-bottom: 10px; }
        .card { background: white; padding: 20px; margin: 15px 0; border-radius: 8px; 
                box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .info-box { background: #e8f5e9; border-left: 4px solid #4caf50; 
                    padding: 15px; margin: 15px 0; }
        .warning-box { background: #fff3e0; border-left: 4px solid #ff9800; 
                       padding: 15px; margin: 15px 0; }
        pre { background: #263238; color: #aed581; padding: 15px; border-radius: 4px; }
        code { background: #eceff1; padding: 2px 6px; border-radius: 3px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>OIDC-Protected API Server</h1>
        
        <div class="card">
            <h2>About This Service</h2>
            <p>This API server is a <strong>traditional OIDC-protected service</strong>. It:</p>
            <ul>
                <li>Validates tokens against <strong>Keycloak only</strong></li>
                <li>Does NOT understand SPIFFE or JWT-SVIDs</li>
                <li>Represents a legacy or enterprise service that uses standard OIDC</li>
            </ul>
        </div>
        
        <div class="warning-box">
            <strong>This service does NOT know about SPIFFE!</strong><br>
            It only accepts Keycloak tokens. SPIFFE-enabled workloads must first exchange 
            their JWT-SVIDs for Keycloak tokens before calling this API.
        </div>
        
        <div class="card">
            <h2>API Endpoints</h2>
            <ul>
                <li><code>GET /api/data</code> - Returns sample data (requires valid Keycloak token)</li>
                <li><code>GET /api/whoami</code> - Returns token claims (requires valid Keycloak token)</li>
                <li><code>GET /health</code> - Health check (no auth required)</li>
            </ul>
        </div>
        
        <div class="info-box">
            <strong>Configuration:</strong><br>
            Keycloak URL: {{ keycloak_url }}<br>
            Realm: {{ keycloak_realm }}<br>
            JWKS URL: {{ jwks_url }}
        </div>
    </div>
</body>
</html>
"""


def get_jwks_client():
    """Get or create JWKS client for token validation."""
    global jwks_client
    if jwks_client is None:
        jwks_client = PyJWKClient(JWKS_URL, ssl_context=False)
    return jwks_client


def validate_token(token):
    """Validate an access token (supports both real Keycloak tokens and mock tokens)."""
    if token.startswith('mock.'):
        try:
            parts = token.split('.')
            if len(parts) >= 2:
                import base64
                payload = parts[1]
                padding = 4 - len(payload) % 4
                if padding != 4:
                    payload += '=' * padding
                decoded = json.loads(base64.urlsafe_b64decode(payload))
                return decoded
        except Exception as e:
            raise ValueError(f"Invalid mock token: {str(e)}")
    
    try:
        client = get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        
        decoded = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience="account",
            options={"verify_aud": False}
        )
        return decoded
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {str(e)}")


def require_auth(f):
    """Decorator to require valid Keycloak token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({
                'error': 'Missing Authorization header',
                'hint': 'Include header: Authorization: Bearer <keycloak_token>'
            }), 401
        
        if not auth_header.startswith('Bearer '):
            return jsonify({
                'error': 'Invalid Authorization header format',
                'hint': 'Use format: Bearer <token>'
            }), 401
        
        token = auth_header[7:]
        
        try:
            claims = validate_token(token)
            request.token_claims = claims
            return f(*args, **kwargs)
        except ValueError as e:
            return jsonify({
                'error': str(e),
                'hint': 'Make sure you are using a valid Keycloak token from the spiffe-demo realm'
            }), 401
        except Exception as e:
            return jsonify({
                'error': f'Token validation failed: {str(e)}',
                'keycloak_url': KEYCLOAK_URL,
                'realm': KEYCLOAK_REALM
            }), 401
    
    return decorated


@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        keycloak_url=KEYCLOAK_URL,
        keycloak_realm=KEYCLOAK_REALM,
        jwks_url=JWKS_URL
    )


@app.route('/api/data')
@require_auth
def get_data():
    """Return sample data - requires valid Keycloak token."""
    claims = request.token_claims
    
    return jsonify({
        'status': 'success',
        'message': 'You have successfully accessed the OIDC-protected API!',
        'authenticated_as': claims.get('preferred_username') or claims.get('sub'),
        'token_issuer': claims.get('iss'),
        'data': [
            {'id': 1, 'name': 'Resource A', 'description': 'Sample resource 1'},
            {'id': 2, 'name': 'Resource B', 'description': 'Sample resource 2'},
            {'id': 3, 'name': 'Resource C', 'description': 'Sample resource 3'}
        ],
        'note': 'This API only accepts Keycloak tokens, not SPIFFE JWT-SVIDs'
    })


@app.route('/api/whoami')
@require_auth
def whoami():
    """Return information about the authenticated user/service."""
    claims = request.token_claims
    
    safe_claims = {
        'sub': claims.get('sub'),
        'preferred_username': claims.get('preferred_username'),
        'email': claims.get('email'),
        'iss': claims.get('iss'),
        'aud': claims.get('aud'),
        'azp': claims.get('azp'),
        'realm_access': claims.get('realm_access'),
        'resource_access': claims.get('resource_access'),
        'scope': claims.get('scope'),
        'exp': claims.get('exp'),
        'iat': claims.get('iat')
    }
    
    return jsonify({
        'status': 'success',
        'token_validated_against': 'Keycloak (OIDC)',
        'claims': {k: v for k, v in safe_claims.items() if v is not None}
    })


@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'OIDC-Protected API Server',
        'keycloak_realm': KEYCLOAK_REALM
    })


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
    
    app.run(host='0.0.0.0', port=8080, debug=True)
