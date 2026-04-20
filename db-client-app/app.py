#!/usr/bin/env python3
"""
SPIFFE-Enabled PostgreSQL Client Application

This application demonstrates how to use SPIFFE X.509-SVIDs to authenticate
to a PostgreSQL/EDB database using certificate-based authentication.

The application:
1. Gets X.509-SVID from SPIRE via the Workload API
2. Uses the certificate for mTLS connection to PostgreSQL
3. PostgreSQL maps the certificate CN to a database role
"""

import os
import ssl
import tempfile
from datetime import datetime
from flask import Flask, render_template_string, jsonify
from spiffe import WorkloadApiClient
from cryptography.hazmat.primitives import serialization
from cryptography.x509 import ExtensionOID
from cryptography.x509.general_name import UniformResourceIdentifier

app = Flask(__name__)

# Configuration from environment
DB_HOST = os.environ.get('DB_HOST', 'edb-spiffe-postgres.edb.svc.cluster.local')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'appdb')
# DB_USER is now extracted from the certificate CN by PostgreSQL's 'cert' auth method
# The CN is set via ClusterSPIFFEID's dnsNameTemplates field
# Reference: https://gitea.jamma.life/jmhbnz/talks/src/branch/main/2026-04-03-openshift-ztwim
DB_USER = os.environ.get('DB_USER', 'app_readonly')
DB_SSLMODE = os.environ.get('DB_SSLMODE', 'require')
SPIFFE_ENDPOINT_SOCKET = os.environ.get('SPIFFE_ENDPOINT_SOCKET', 'unix:///spiffe-workload-api/spire-agent.sock')

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>SPIFFE PostgreSQL Client</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .header {
            background: linear-gradient(135deg, #1a5f7a 0%, #2d8f9f 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .header h1 { margin: 0 0 10px 0; }
        .header p { margin: 0; opacity: 0.9; }
        .card {
            background: white;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .card h2 {
            color: #1a5f7a;
            margin-top: 0;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 10px;
        }
        .btn {
            display: inline-block;
            padding: 12px 24px;
            margin: 5px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            text-decoration: none;
            transition: all 0.3s;
        }
        .btn-primary { background-color: #1a5f7a; color: white; }
        .btn-primary:hover { background-color: #0d4a5f; }
        .btn-success { background-color: #28a745; color: white; }
        .btn-success:hover { background-color: #1e7e34; }
        .btn-info { background-color: #17a2b8; color: white; }
        .btn-info:hover { background-color: #117a8b; }
        .btn-warning { background-color: #ffc107; color: #333; }
        .btn-warning:hover { background-color: #d39e00; }
        .result {
            background-color: #f8f9fa;
            border: 1px solid #e0e0e0;
            border-radius: 5px;
            padding: 15px;
            margin-top: 15px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            white-space: pre-wrap;
            overflow-x: auto;
            max-height: 400px;
            overflow-y: auto;
        }
        .success { border-left: 4px solid #28a745; }
        .error { border-left: 4px solid #dc3545; background-color: #fff5f5; }
        .info-box {
            background-color: #e7f3ff;
            border: 1px solid #b8daff;
            border-radius: 5px;
            padding: 15px;
            margin: 10px 0;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 10px;
            text-align: left;
        }
        th { background-color: #1a5f7a; color: white; }
        tr:nth-child(even) { background-color: #f8f9fa; }
        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 15px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-connected { background-color: #d4edda; color: #155724; }
        .status-error { background-color: #f8d7da; color: #721c24; }
        .flow-diagram {
            background-color: #fff;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 20px;
            font-family: monospace;
            white-space: pre;
            overflow-x: auto;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔐 SPIFFE PostgreSQL Client</h1>
        <p>Demonstrating X.509-SVID certificate authentication to PostgreSQL/EDB</p>
    </div>

    <div class="card">
        <h2>📋 Configuration</h2>
        <table>
            <tr><th>Setting</th><th>Value</th></tr>
            <tr><td>Database Host</td><td>{{ db_host }}</td></tr>
            <tr><td>Database Port</td><td>{{ db_port }}</td></tr>
            <tr><td>Database Name</td><td>{{ db_name }}</td></tr>
            <tr><td>SSL Mode</td><td>{{ db_sslmode }}</td></tr>
            <tr><td>SPIFFE Socket</td><td>{{ spiffe_socket }}</td></tr>
        </table>
    </div>

    <div class="card">
        <h2>🔑 SPIFFE Identity</h2>
        <p>Click to fetch your workload's SPIFFE identity from SPIRE:</p>
        <button class="btn btn-primary" onclick="fetchIdentity()">Fetch SPIFFE Identity</button>
        <button class="btn btn-info" onclick="fetchCertDetails()">View Certificate Details</button>
        <div id="identity-result" class="result" style="display:none;"></div>
    </div>

    <div class="card">
        <h2>🗄️ Database Operations</h2>
        <p>Test database connectivity and operations using SPIFFE certificate authentication:</p>
        
        <h3>Connection Test</h3>
        <button class="btn btn-success" onclick="testConnection()">Test Connection</button>
        <div id="connection-result" class="result" style="display:none;"></div>

        <h3>Read Operations (SELECT)</h3>
        <button class="btn btn-info" onclick="queryData()">Query Data</button>
        <div id="query-result" class="result" style="display:none;"></div>

        <h3>Write Operations (INSERT)</h3>
        <button class="btn btn-warning" onclick="insertData()">Insert Record</button>
        <div id="insert-result" class="result" style="display:none;"></div>
    </div>

    <div class="card">
        <h2>📊 Authentication &amp; Authorization Flow</h2>
        <div class="flow-diagram">
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  This App       │     │  SPIRE Agent    │     │    PostgreSQL   │
│  (db-client)    │     │                 │     │                 │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         │  1. Request X.509-SVID                        │
         │ ─────────────────────►│                       │
         │                       │                       │
         │  2. Return Certificate with:                  │
         │     - CN = "app_readonly" (from dnsNameTemplates)
         │     - SAN = spiffe://trust-domain/ns/.../sa/...
         │ ◄─────────────────────│                       │
         │                       │                       │
         │  3. mTLS Connect (cert has CN="app_readonly") │
         │ ─────────────────────────────────────────────►│
         │                       │                       │
         │                       │    4. Verify cert     │
         │                       │       signed by       │
         │                       │       SPIRE CA ✓      │
         │                       │       (AUTHENTICATION)│
         │                       │                       │
         │                       │    5. pg_hba.conf:    │
         │                       │       method = cert   │
         │                       │       Extract CN ✓    │
         │                       │                       │
         │                       │    6. CN="app_readonly"
         │                       │       maps to PG role │
         │                       │       with specific   │
         │                       │       permissions     │
         │                       │       (AUTHORIZATION) │
         │                       │                       │
         │  7. Connection established as "app_readonly"  │
         │ ◄─────────────────────────────────────────────│
         │                       │                       │
        </div>
        <div class="info-box">
            <strong>How it works:</strong> The ClusterSPIFFEID's <code>dnsNameTemplates</code> 
            field sets the certificate CN (Common Name) to the PostgreSQL username. 
            PostgreSQL's <code>cert</code> auth method extracts the CN from the certificate 
            and uses it as the username. This provides both authentication (valid SPIRE-signed cert) 
            AND authorization (CN maps to a PostgreSQL role with specific permissions).
            <br><br>
            <strong>Reference:</strong> <a href="https://gitea.jamma.life/jmhbnz/talks/src/branch/main/2026-04-03-openshift-ztwim" target="_blank">jmhbnz/talks - OpenShift ZTWIM Demo</a>
        </div>
    </div>

    <script>
        async function fetchIdentity() {
            const result = document.getElementById('identity-result');
            result.style.display = 'block';
            result.className = 'result';
            result.textContent = 'Fetching SPIFFE identity...';
            
            try {
                const response = await fetch('/api/identity');
                const data = await response.json();
                result.className = data.error ? 'result error' : 'result success';
                result.textContent = JSON.stringify(data, null, 2);
            } catch (e) {
                result.className = 'result error';
                result.textContent = 'Error: ' + e.message;
            }
        }

        async function fetchCertDetails() {
            const result = document.getElementById('identity-result');
            result.style.display = 'block';
            result.className = 'result';
            result.textContent = 'Fetching certificate details...';
            
            try {
                const response = await fetch('/api/certificate');
                const data = await response.json();
                result.className = data.error ? 'result error' : 'result success';
                result.textContent = JSON.stringify(data, null, 2);
            } catch (e) {
                result.className = 'result error';
                result.textContent = 'Error: ' + e.message;
            }
        }

        async function testConnection() {
            const result = document.getElementById('connection-result');
            result.style.display = 'block';
            result.className = 'result';
            result.textContent = 'Testing database connection...';
            
            try {
                const response = await fetch('/api/db/test');
                const data = await response.json();
                result.className = data.error ? 'result error' : 'result success';
                result.textContent = JSON.stringify(data, null, 2);
            } catch (e) {
                result.className = 'result error';
                result.textContent = 'Error: ' + e.message;
            }
        }

        async function queryData() {
            const result = document.getElementById('query-result');
            result.style.display = 'block';
            result.className = 'result';
            result.textContent = 'Querying data...';
            
            try {
                const response = await fetch('/api/db/query');
                const data = await response.json();
                result.className = data.error ? 'result error' : 'result success';
                result.textContent = JSON.stringify(data, null, 2);
            } catch (e) {
                result.className = 'result error';
                result.textContent = 'Error: ' + e.message;
            }
        }

        async function insertData() {
            const result = document.getElementById('insert-result');
            result.style.display = 'block';
            result.className = 'result';
            result.textContent = 'Inserting record...';
            
            try {
                const response = await fetch('/api/db/insert', { method: 'POST' });
                const data = await response.json();
                result.className = data.error ? 'result error' : 'result success';
                result.textContent = JSON.stringify(data, null, 2);
            } catch (e) {
                result.className = 'result error';
                result.textContent = 'Error: ' + e.message;
            }
        }
    </script>
</body>
</html>
'''


def get_spiffe_client():
    """Create a SPIFFE Workload API client."""
    try:
        return WorkloadApiClient(SPIFFE_ENDPOINT_SOCKET)
    except Exception as e:
        return None


def get_x509_svid():
    """Fetch X.509-SVID from SPIRE."""
    client = get_spiffe_client()
    if not client:
        return None, "Failed to create SPIFFE client"
    
    try:
        x509_source = client.fetch_x509_context()
        if x509_source and x509_source.default_svid:
            return x509_source.default_svid, None
        return None, "No SVID available"
    except Exception as e:
        return None, str(e)


def write_certs_to_temp_files(svid):
    """Write SVID certificate and key to temporary files for psycopg2."""
    import tempfile
    
    cert_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.pem', delete=False)
    key_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.pem', delete=False)
    ca_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.pem', delete=False)
    
    # Write certificate chain
    for cert in svid.cert_chain:
        cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
    cert_file.close()
    
    # Write private key
    key_bytes = svid.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    key_file.write(key_bytes)
    key_file.close()
    
    return cert_file.name, key_file.name


def get_db_connection():
    """Create a database connection using SPIFFE certificate."""
    import psycopg2
    
    svid, error = get_x509_svid()
    if error:
        raise Exception(f"Failed to get SVID: {error}")
    
    # Get the trust bundle for server verification
    client = get_spiffe_client()
    x509_context = client.fetch_x509_context()
    
    # Write certificates to temp files
    cert_file, key_file = write_certs_to_temp_files(svid)
    
    # Write CA bundle
    ca_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.pem', delete=False)
    try:
        # Try different ways to access the bundle depending on library version
        bundle_set = x509_context.x509_bundle_set
        if hasattr(bundle_set, 'bundles'):
            bundles = bundle_set.bundles
            if hasattr(bundles, 'values'):
                # It's a dict
                for bundle in bundles.values():
                    for cert in bundle.x509_authorities:
                        ca_file.write(cert.public_bytes(serialization.Encoding.PEM))
            else:
                # It might be iterable directly
                for bundle in bundles:
                    if hasattr(bundle, 'x509_authorities'):
                        for cert in bundle.x509_authorities:
                            ca_file.write(cert.public_bytes(serialization.Encoding.PEM))
        elif hasattr(bundle_set, 'get_bundle_for_trust_domain'):
            # Get bundle for our trust domain
            trust_domain = str(svid.spiffe_id).split('/')[2]
            bundle = bundle_set.get_bundle_for_trust_domain(trust_domain)
            if bundle:
                for cert in bundle.x509_authorities:
                    ca_file.write(cert.public_bytes(serialization.Encoding.PEM))
    except Exception as e:
        # Fallback: just use the issuer cert from the SVID chain
        if len(svid.cert_chain) > 1:
            for cert in svid.cert_chain[1:]:
                ca_file.write(cert.public_bytes(serialization.Encoding.PEM))
    ca_file.close()
    
    try:
        # Build connection parameters
        conn_params = {
            'host': DB_HOST,
            'port': DB_PORT,
            'dbname': DB_NAME,
            'user': DB_USER,
            'sslmode': DB_SSLMODE,
            'sslcert': cert_file,
            'sslkey': key_file,
        }
        # Only add sslrootcert if using verify-full or verify-ca
        if DB_SSLMODE in ('verify-full', 'verify-ca'):
            conn_params['sslrootcert'] = ca_file.name
        
        conn = psycopg2.connect(**conn_params)
        return conn
    finally:
        # Clean up temp files
        import os
        os.unlink(cert_file)
        os.unlink(key_file)
        if os.path.exists(ca_file.name):
            os.unlink(ca_file.name)


@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        db_host=DB_HOST,
        db_port=DB_PORT,
        db_name=DB_NAME,
        db_sslmode=DB_SSLMODE,
        spiffe_socket=SPIFFE_ENDPOINT_SOCKET
    )


@app.route('/api/identity')
def api_identity():
    """Return the workload's SPIFFE identity."""
    try:
        svid, error = get_x509_svid()
        if error:
            return jsonify({
                "error": "Failed to get SPIFFE identity",
                "message": error,
                "spiffe_available": False
            }), 500
        
        return jsonify({
            "spiffe_id": str(svid.spiffe_id),
            "spiffe_available": True,
            "certificate_count": len(svid.cert_chain),
            "expires_at": svid.cert_chain[0].not_valid_after.isoformat() if svid.cert_chain else None
        })
    except Exception as e:
        return jsonify({
            "error": "Exception occurred",
            "message": str(e),
            "spiffe_available": False
        }), 500


@app.route('/api/certificate')
def api_certificate():
    """Return certificate details."""
    try:
        svid, error = get_x509_svid()
        if error:
            return jsonify({"error": error}), 500
        
        cert = svid.cert_chain[0]
        
        # Extract subject details
        subject_parts = {}
        for attr in cert.subject:
            subject_parts[attr.oid._name] = attr.value
        
        # Extract SAN
        san_uris = []
        try:
            san_ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
            for name in san_ext.value:
                if isinstance(name, UniformResourceIdentifier):
                    san_uris.append(name.value)
        except:
            pass
        
        return jsonify({
            "subject": subject_parts,
            "common_name": subject_parts.get("commonName", "N/A"),
            "san_uris": san_uris,
            "issuer": {attr.oid._name: attr.value for attr in cert.issuer},
            "serial_number": str(cert.serial_number),
            "not_valid_before": cert.not_valid_before.isoformat(),
            "not_valid_after": cert.not_valid_after.isoformat(),
            "spiffe_id": str(svid.spiffe_id)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/db/test')
def api_db_test():
    """Test database connection."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get connection info
        cursor.execute("SELECT current_user, session_user, current_database(), version();")
        result = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "status": "connected",
            "current_user": result[0],
            "session_user": result[1],
            "database": result[2],
            "postgres_version": result[3],
            "authentication": "X.509 Certificate (SPIFFE SVID)",
            "ssl_mode": DB_SSLMODE
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "hint": "Check that the database trusts the SPIRE CA and pg_ident.conf mapping is correct"
        }), 500


@app.route('/api/db/query')
def api_db_query():
    """Query data from the database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, name, created_at, created_by FROM demo_data ORDER BY id;")
        rows = cursor.fetchall()
        
        data = []
        for row in rows:
            data.append({
                "id": row[0],
                "name": row[1],
                "created_at": row[2].isoformat() if row[2] else None,
                "created_by": row[3]
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "status": "success",
            "operation": "SELECT",
            "row_count": len(data),
            "data": data
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "operation": "SELECT",
            "error": str(e)
        }), 500


@app.route('/api/db/insert', methods=['POST'])
def api_db_insert():
    """Insert a record into the database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get SPIFFE ID for the created_by field
        svid, _ = get_x509_svid()
        created_by = str(svid.spiffe_id) if svid else "unknown"
        
        name = f"Record created at {datetime.now().isoformat()}"
        
        cursor.execute(
            "INSERT INTO demo_data (name, created_by) VALUES (%s, %s) RETURNING id;",
            (name, created_by)
        )
        new_id = cursor.fetchone()[0]
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "status": "success",
            "operation": "INSERT",
            "message": f"Record created with ID {new_id}",
            "record": {
                "id": new_id,
                "name": name,
                "created_by": created_by
            }
        })
    except Exception as e:
        error_msg = str(e)
        hint = None
        
        if "permission denied" in error_msg.lower():
            hint = "Your SPIFFE identity is mapped to a read-only role. INSERT requires app_readwrite or app_admin role."
        
        return jsonify({
            "status": "error",
            "operation": "INSERT",
            "error": error_msg,
            "hint": hint
        }), 500


@app.route('/health')
def health():
    return jsonify({"status": "healthy"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
