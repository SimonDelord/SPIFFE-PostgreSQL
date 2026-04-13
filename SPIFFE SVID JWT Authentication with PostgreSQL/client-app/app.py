"""
SPIFFE JWT-SVID to OIDC Token Exchange Demo

This application demonstrates how a SPIFFE-enabled workload can:
1. Obtain a JWT-SVID from SPIRE
2. Exchange it for an OIDC-style token (via mock exchange or Keycloak)
3. Use that token to call an OIDC-protected API
"""

import os
import json
import time
import base64
import hashlib
import requests
from flask import Flask, jsonify, render_template_string
from spiffe import WorkloadApiClient
import jwt as pyjwt

app = Flask(__name__)

SPIFFE_ENDPOINT_SOCKET = os.environ.get('SPIFFE_ENDPOINT_SOCKET', 'unix:///spiffe-workload-api/spire-agent.sock')
KEYCLOAK_URL = os.environ.get('KEYCLOAK_URL', 'https://keycloak-keycloak.apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com')
KEYCLOAK_REALM = os.environ.get('KEYCLOAK_REALM', 'spiffe-demo')
KEYCLOAK_CLIENT_ID = os.environ.get('KEYCLOAK_CLIENT_ID', 'spiffe-workload')
KEYCLOAK_CLIENT_SECRET = os.environ.get('KEYCLOAK_CLIENT_SECRET', 'spiffe-workload-secret')
API_SERVER_URL = os.environ.get('API_SERVER_URL', 'http://api-server.spiffe-jwt-demo.svc.cluster.local:8080')
SPIRE_IDP_ALIAS = os.environ.get('SPIRE_IDP_ALIAS', 'spire-oidc')
SPIRE_OIDC_URL = os.environ.get('SPIRE_OIDC_URL', 'https://oidc-discovery.apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com')
USE_MOCK_EXCHANGE = os.environ.get('USE_MOCK_EXCHANGE', 'true').lower() == 'true'

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>SPIFFE JWT-SVID Token Exchange Demo</title>
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #1a237e; border-bottom: 3px solid #3f51b5; padding-bottom: 10px; }
        h2 { color: #303f9f; margin-top: 30px; }
        .card { background: white; padding: 20px; margin: 15px 0; border-radius: 8px; 
                box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .btn { padding: 12px 24px; margin: 5px; border: none; border-radius: 4px; 
               cursor: pointer; font-size: 14px; font-weight: 500; }
        .btn-primary { background: #3f51b5; color: white; }
        .btn-success { background: #4caf50; color: white; }
        .btn-info { background: #2196f3; color: white; }
        .btn:hover { opacity: 0.9; transform: translateY(-1px); }
        pre { background: #263238; color: #aed581; padding: 15px; border-radius: 4px; 
              overflow-x: auto; font-size: 13px; }
        .success { color: #2e7d32; }
        .error { color: #c62828; }
        .flow-diagram { background: #eceff1; padding: 20px; border-radius: 8px; 
                        font-family: monospace; white-space: pre; overflow-x: auto; }
        .info-box { background: #e3f2fd; border-left: 4px solid #2196f3; 
                    padding: 15px; margin: 15px 0; }
        .warning-box { background: #fff3e0; border-left: 4px solid #ff9800; 
                       padding: 15px; margin: 15px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>SPIFFE JWT-SVID Token Exchange Demo</h1>
        
        <div class="card">
            <h2>How It Works</h2>
            <div class="flow-diagram">
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   This App      │     │  SPIRE Agent    │     │  Token Exchange │     │   API Server    │
│  (SPIFFE        │     │                 │     │  Service        │     │   (OIDC Only)   │
│   enabled)      │     │                 │     │  (IdP)          │     │                 │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │                       │
         │  1. Request JWT-SVID  │                       │                       │
         │ ─────────────────────►│                       │                       │
         │                       │                       │                       │
         │  2. Return JWT-SVID   │                       │                       │
         │ ◄─────────────────────│                       │                       │
         │                       │                       │                       │
         │  3. Exchange JWT-SVID for OIDC Token          │                       │
         │ ─────────────────────────────────────────────►│                       │
         │                       │                       │                       │
         │                       │  4. Validate JWT-SVID │                       │
         │                       │◄──────────────────────│                       │
         │                       │  (via SPIRE OIDC)     │                       │
         │                       │──────────────────────►│                       │
         │                       │                       │                       │
         │  5. Return OIDC Access Token                  │                       │
         │ ◄─────────────────────────────────────────────│                       │
         │                       │                       │                       │
         │  6. Call API with OIDC Token                                          │
         │ ─────────────────────────────────────────────────────────────────────►│
         │                       │                       │                       │
         │  7. API Response                                                      │
         │ ◄─────────────────────────────────────────────────────────────────────│
            </div>
        </div>
        
        <div class="warning-box">
            <strong>Mode:</strong> {{ exchange_mode }}<br>
            {{ exchange_note }}
        </div>
        
        <div class="card">
            <h2>Step 1: Get JWT-SVID from SPIRE</h2>
            <p>Request a JWT-SVID from the SPIRE Agent via the Workload API.</p>
            <button class="btn btn-primary" onclick="fetchJwtSvid()">Get JWT-SVID</button>
            <div id="jwt-svid-result"></div>
        </div>
        
        <div class="card">
            <h2>Step 2: Exchange JWT-SVID for OIDC Token</h2>
            <p>Exchange the JWT-SVID for an OIDC-style access token.</p>
            <button class="btn btn-success" onclick="exchangeToken()">Exchange Token</button>
            <div id="exchange-result"></div>
        </div>
        
        <div class="card">
            <h2>Step 3: Call API with OIDC Token</h2>
            <p>Use the OIDC access token to call the OIDC-protected API.</p>
            <button class="btn btn-info" onclick="callApi()">Call API</button>
            <div id="api-result"></div>
        </div>
        
        <div class="card">
            <h2>Full Flow: JWT-SVID → Token Exchange → API</h2>
            <p>Execute the complete flow.</p>
            <button class="btn btn-primary" onclick="fullFlow()">Run Full Flow</button>
            <div id="full-flow-result"></div>
        </div>
        
        <div class="info-box">
            <strong>Configuration:</strong><br>
            SPIRE OIDC URL: {{ spire_oidc_url }}<br>
            Keycloak URL: {{ keycloak_url }}<br>
            Realm: {{ keycloak_realm }}<br>
            API Server: {{ api_server_url }}
        </div>
    </div>
    
    <script>
        async function fetchJwtSvid() {
            const resultDiv = document.getElementById('jwt-svid-result');
            resultDiv.innerHTML = '<p>Fetching JWT-SVID...</p>';
            try {
                const response = await fetch('/api/jwt-svid');
                const data = await response.json();
                resultDiv.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
            } catch (error) {
                resultDiv.innerHTML = '<p class="error">Error: ' + error.message + '</p>';
            }
        }
        
        async function exchangeToken() {
            const resultDiv = document.getElementById('exchange-result');
            resultDiv.innerHTML = '<p>Exchanging token...</p>';
            try {
                const response = await fetch('/api/exchange');
                const data = await response.json();
                resultDiv.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
            } catch (error) {
                resultDiv.innerHTML = '<p class="error">Error: ' + error.message + '</p>';
            }
        }
        
        async function callApi() {
            const resultDiv = document.getElementById('api-result');
            resultDiv.innerHTML = '<p>Calling API...</p>';
            try {
                const response = await fetch('/api/call-api');
                const data = await response.json();
                resultDiv.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
            } catch (error) {
                resultDiv.innerHTML = '<p class="error">Error: ' + error.message + '</p>';
            }
        }
        
        async function fullFlow() {
            const resultDiv = document.getElementById('full-flow-result');
            resultDiv.innerHTML = '<p>Running full flow...</p>';
            try {
                const response = await fetch('/api/full-flow');
                const data = await response.json();
                resultDiv.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
            } catch (error) {
                resultDiv.innerHTML = '<p class="error">Error: ' + error.message + '</p>';
            }
        }
    </script>
</body>
</html>
"""


def get_jwt_svid(aud=None):
    """Fetch a JWT-SVID from SPIRE."""
    try:
        client = WorkloadApiClient(SPIFFE_ENDPOINT_SOCKET)
        if aud is None:
            aud = SPIRE_OIDC_URL
        
        jwt_svid = client.fetch_jwt_svid(audience={aud})
        return {
            'status': 'success',
            'spiffe_id': str(jwt_svid.spiffe_id),
            'audience': aud,
            'token': jwt_svid.token,
            'token_preview': jwt_svid.token[:50] + '...' if len(jwt_svid.token) > 50 else jwt_svid.token
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': f'Error fetching JWT SVID: {str(e)}'
        }


def validate_jwt_svid(jwt_svid_token):
    """Validate a JWT-SVID against the SPIRE OIDC Discovery Provider."""
    try:
        jwks_url = f"{SPIRE_OIDC_URL}/keys"
        jwks_response = requests.get(jwks_url, verify=False, timeout=5)
        jwks = jwks_response.json()
        
        header = pyjwt.get_unverified_header(jwt_svid_token)
        kid = header.get('kid')
        
        key = None
        for k in jwks.get('keys', []):
            if k.get('kid') == kid:
                key = k
                break
        
        if not key:
            return False, "Key not found in JWKS"
        
        from jwt import PyJWKClient
        jwks_client = PyJWKClient(jwks_url, ssl_context=False)
        signing_key = jwks_client.get_signing_key_from_jwt(jwt_svid_token)
        
        decoded = pyjwt.decode(
            jwt_svid_token,
            signing_key.key,
            algorithms=["RS256", "ES256", "ES384"],
            options={"verify_aud": False}
        )
        return True, decoded
    except Exception as e:
        return False, str(e)


def mock_token_exchange(jwt_svid_token, spiffe_id):
    """
    Simulate token exchange by validating JWT-SVID and issuing an OIDC-style token.
    This demonstrates what Keycloak/Entra ID would do.
    """
    valid, result = validate_jwt_svid(jwt_svid_token)
    
    if not valid:
        return {
            'status': 'error',
            'error': f'JWT-SVID validation failed: {result}'
        }
    
    now = int(time.time())
    oidc_token_payload = {
        'iss': f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
        'sub': spiffe_id,
        'aud': 'api-server',
        'exp': now + 3600,
        'iat': now,
        'azp': 'spiffe-workload',
        'scope': 'openid profile email',
        'original_issuer': SPIRE_OIDC_URL,
        'original_sub': result.get('sub'),
        'token_type': 'Bearer',
        'exchanged_from': 'JWT-SVID'
    }
    
    token_str = base64.urlsafe_b64encode(
        json.dumps(oidc_token_payload).encode()
    ).decode().rstrip('=')
    
    mock_token = f"mock.{token_str}.signature"
    
    return {
        'status': 'success',
        'method': 'mock_token_exchange',
        'access_token': mock_token,
        'token_type': 'Bearer',
        'expires_in': 3600,
        'original_svid_validated': True,
        'original_claims': result,
        'note': 'This is a mock token demonstrating the exchange pattern. In production, Keycloak/Entra ID would issue a real signed token.'
    }


def keycloak_token_exchange(jwt_svid_token):
    """
    Exchange a JWT-SVID for a Keycloak access token using RFC 8693 Token Exchange.
    """
    token_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    
    data = {
        'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
        'client_id': KEYCLOAK_CLIENT_ID,
        'client_secret': KEYCLOAK_CLIENT_SECRET,
        'subject_token': jwt_svid_token,
        'subject_token_type': 'urn:ietf:params:oauth:token-type:jwt',
        'subject_issuer': SPIRE_IDP_ALIAS,
        'requested_token_type': 'urn:ietf:params:oauth:token-type:access_token'
    }
    
    try:
        response = requests.post(token_url, data=data, verify=False)
        
        if response.status_code == 200:
            token_data = response.json()
            return {
                'status': 'success',
                'method': 'keycloak_token_exchange',
                'access_token': token_data.get('access_token'),
                'token_type': token_data.get('token_type'),
                'expires_in': token_data.get('expires_in'),
                'token_preview': token_data.get('access_token', '')[:50] + '...'
            }
        else:
            return {
                'status': 'error',
                'method': 'keycloak_token_exchange',
                'http_status': response.status_code,
                'error': response.text
            }
    except Exception as e:
        return {
            'status': 'error',
            'method': 'keycloak_token_exchange',
            'error': str(e)
        }


def exchange_token(jwt_svid_token, spiffe_id):
    """Exchange JWT-SVID for an OIDC token."""
    if USE_MOCK_EXCHANGE:
        return mock_token_exchange(jwt_svid_token, spiffe_id)
    else:
        result = keycloak_token_exchange(jwt_svid_token)
        if result['status'] == 'error':
            return mock_token_exchange(jwt_svid_token, spiffe_id)
        return result


def call_api_with_token(access_token):
    """Call the OIDC-protected API with the token."""
    try:
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        response = requests.get(f"{API_SERVER_URL}/api/data", headers=headers, verify=False, timeout=5)
        
        if response.status_code == 200:
            return {
                'status': 'success',
                'data': response.json()
            }
        else:
            return {
                'status': 'error',
                'http_status': response.status_code,
                'error': response.text
            }
    except requests.exceptions.ConnectionError:
        return {
            'status': 'error',
            'error': 'Cannot connect to API server',
            'hint': f'Make sure the API server is running at {API_SERVER_URL}'
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }


@app.route('/')
def index():
    exchange_mode = "Mock Token Exchange" if USE_MOCK_EXCHANGE else "Keycloak Token Exchange"
    exchange_note = ("Using mock exchange to demonstrate the pattern. "
                    "The JWT-SVID is validated against SPIRE OIDC and a mock OIDC token is issued.") if USE_MOCK_EXCHANGE else (
                    "Using Keycloak for real token exchange (RFC 8693).")
    
    return render_template_string(
        HTML_TEMPLATE,
        keycloak_url=KEYCLOAK_URL,
        keycloak_realm=KEYCLOAK_REALM,
        spire_oidc_url=SPIRE_OIDC_URL,
        api_server_url=API_SERVER_URL,
        exchange_mode=exchange_mode,
        exchange_note=exchange_note
    )


@app.route('/api/jwt-svid')
def api_jwt_svid():
    result = get_jwt_svid()
    return jsonify(result)


@app.route('/api/exchange')
def api_exchange():
    jwt_result = get_jwt_svid()
    if jwt_result['status'] != 'success':
        return jsonify({
            'status': 'error',
            'step': 'get_jwt_svid',
            'error': jwt_result.get('error')
        })
    
    exchange_result = exchange_token(jwt_result['token'], jwt_result['spiffe_id'])
    exchange_result['jwt_svid_spiffe_id'] = jwt_result['spiffe_id']
    return jsonify(exchange_result)


@app.route('/api/call-api')
def api_call():
    jwt_result = get_jwt_svid()
    if jwt_result['status'] != 'success':
        return jsonify({
            'status': 'error',
            'step': 'get_jwt_svid',
            'error': jwt_result.get('error')
        })
    
    exchange_result = exchange_token(jwt_result['token'], jwt_result['spiffe_id'])
    if exchange_result['status'] != 'success':
        return jsonify({
            'status': 'error',
            'step': 'token_exchange',
            'error': exchange_result.get('error')
        })
    
    api_result = call_api_with_token(exchange_result['access_token'])
    return jsonify(api_result)


@app.route('/api/full-flow')
def api_full_flow():
    """Execute the complete flow and return all results."""
    results = {
        'steps': []
    }
    
    jwt_result = get_jwt_svid()
    results['steps'].append({
        'step': 1,
        'name': 'Get JWT-SVID from SPIRE',
        'result': {k: v for k, v in jwt_result.items() if k != 'token'}
    })
    
    if jwt_result['status'] != 'success':
        results['final_status'] = 'failed'
        results['failed_at'] = 'get_jwt_svid'
        return jsonify(results)
    
    exchange_result = exchange_token(jwt_result['token'], jwt_result['spiffe_id'])
    results['steps'].append({
        'step': 2,
        'name': 'Exchange JWT-SVID for OIDC Token',
        'result': {k: v for k, v in exchange_result.items() if k != 'access_token' and k != 'original_claims'}
    })
    
    if exchange_result['status'] != 'success':
        results['final_status'] = 'failed'
        results['failed_at'] = 'token_exchange'
        return jsonify(results)
    
    api_result = call_api_with_token(exchange_result['access_token'])
    results['steps'].append({
        'step': 3,
        'name': 'Call API with OIDC Token',
        'result': api_result
    })
    
    results['final_status'] = 'success' if api_result['status'] == 'success' else 'failed'
    if api_result['status'] != 'success':
        results['failed_at'] = 'api_call'
    
    return jsonify(results)


@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    app.run(host='0.0.0.0', port=8080, debug=True)
