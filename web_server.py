"""Liter-ally Trash: one dashboard for classification, rewards, bins, and the rover."""
import argparse
import os
import socket
import ssl
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
from classifier_service import Service
from lid import RemoteLid

ROOT = Path(__file__).resolve().parent
CA_CERT = ROOT / "ca.pem"


def lan_ip():
    """Return this machine's Wi-Fi/LAN address, or None if offline."""
    # Ask the OS for the Wi-Fi address first; a VPN can hijack the default route.
    for cmd in (["ipconfig", "getifaddr", "en0"], ["hostname", "-I"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout.split()
        except (OSError, subprocess.SubprocessError):
            continue
        if out:
            return out[0]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            # No packets are sent; this only picks the outbound interface.
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return None


# The local CA may only sign certificates for this machine and private networks,
# so trusting it cannot be abused to impersonate real websites.
CA_CONSTRAINTS = ",".join(
    f"permitted;{name}" for name in ("DNS:localhost", "IP:127.0.0.0/255.0.0.0", "IP:10.0.0.0/255.0.0.0",
                                     "IP:172.16.0.0/255.240.0.0", "IP:192.168.0.0/255.255.0.0"))


def openssl(*args):
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def ensure_ca(ca, ca_key):
    """Create the local certificate authority that devices trust once."""
    if ca.exists() and ca_key.exists():
        return
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
            "-keyout", ca_key, "-out", ca, "-subj", "/O=Liter-ally Trash/CN=Liter-ally Trash Local CA",
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", f"nameConstraints=critical,{CA_CONSTRAINTS}")
    ca_key.chmod(0o600)
    print(f"Created a local certificate authority: {ca}", flush=True)


def ensure_cert(ip, cert, key, ca, ca_key):
    """Sign a certificate for localhost and ip with the local CA unless a valid one exists."""
    if cert.exists() and key.exists():
        verified = subprocess.run(["openssl", "verify", "-CAfile", ca, cert], capture_output=True).returncode == 0
        covers = not ip or subprocess.run(["openssl", "x509", "-in", cert, "-noout", "-checkip", ip],
                                          capture_output=True).returncode == 0
        # Renew a month before expiry.
        fresh = subprocess.run(["openssl", "x509", "-in", cert, "-noout", "-checkend", str(30 * 86400)],
                               capture_output=True).returncode == 0
        if verified and covers and fresh:
            return
    names = "DNS:localhost,IP:127.0.0.1" + (f",IP:{ip}" if ip else "")
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
            "-keyout", key, "-out", cert, "-CA", ca, "-CAkey", ca_key, "-subj", "/O=Liter-ally Trash",
            "-addext", "basicConstraints=critical,CA:FALSE",
            "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
            "-addext", "extendedKeyUsage=serverAuth",
            "-addext", f"subjectAltName={names}")
    key.chmod(0o600)
    print(f"Created a certificate for {names}", flush=True)


def main():
    load_dotenv(ROOT / "BRH_Test" / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="use 127.0.0.1 for this machine only")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--camera", default=os.getenv("CLASSIFIER_CAMERA", "0"),
                        help="camera number, or a stream URL such as http://<pi-ip>:8080/stream.mjpg")
    parser.add_argument("--cert", help="TLS certificate (PEM) to serve HTTPS")
    parser.add_argument("--key", help="TLS private key (PEM) for --cert")
    parser.add_argument("--http", action="store_true", help="serve plain HTTP (other devices cannot use their own camera)")
    parser.add_argument("--lid-host", default=os.getenv("LID_HOST") or None, help="IP address of the Pi running lid_server.py (default: broadcast to the network)")
    parser.add_argument("--lid-port", type=int, default=int(os.getenv("LID_PORT", "5006")))
    lids = parser.add_mutually_exclusive_group()
    lids.add_argument("--no-lid", dest="lid_enabled", action="store_false", help="do not send lid commands")
    lids.add_argument("--enable-lid", dest="lid_enabled", action="store_true", help="enable live recognition bin-lid commands")
    parser.set_defaults(lid_enabled=os.getenv("CLASSIFIER_LID_ENABLED", "false").lower() == "true")
    parser.add_argument("--init-db", action="store_true", help="initialize the TigerData account and collection tables, then exit")
    parser.add_argument("--no-model-load", action="store_true", help="load recognition on demand from the dashboard")
    args = parser.parse_args()
    if bool(args.cert) != bool(args.key):
        parser.error("--cert and --key must be used together")
    from BRH_Test.website import create_app
    if args.init_db:
        app = create_app({"CLASSIFIER_AUTOLOAD": False})
        try:
            app.extensions["database"].initialize()
            print("Liter-ally Trash database initialized.", flush=True)
        finally:
            app.extensions["classifier"].close()
            app.extensions["rover"].close()
        return
    ip = lan_ip() if args.host == "0.0.0.0" else None
    if not args.http and not args.cert:
        # Browsers only allow camera access over HTTPS, so phones and laptops on
        # the Wi-Fi need it to use their own camera.
        args.cert, args.key = ROOT / "cert.pem", ROOT / "key.pem"
        try:
            ensure_ca(CA_CERT, ROOT / "ca-key.pem")
            ensure_cert(ip, args.cert, args.key, CA_CERT, ROOT / "ca-key.pem")
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"Could not create a certificate ({error}); serving HTTP.", flush=True)
            args.cert = args.key = None
    with socket.socket() as probe:
        # macOS lets 0.0.0.0 and 127.0.0.1 share a port, hiding an old server on localhost.
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            sys.exit(f"Port {args.port} is already in use; stop the other server or pass --port.")
    lid = RemoteLid(args.lid_host, args.lid_port) if args.lid_enabled else None
    service = Service(int(args.camera) if args.camera.isdigit() else args.camera, lid)
    app = create_app({"CLASSIFIER_AUTOLOAD": not args.no_model_load and os.getenv("CLASSIFIER_AUTOLOAD", "true").lower() == "true"}, classifier_service=service)
    scheme = "http"
    context = None
    if args.cert:
        # HTTPS lets other devices on the network use their own browser camera.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        scheme = "https"
        app.config["SESSION_COOKIE_SECURE"] = True
    from werkzeug.serving import make_server
    from flask import send_file
    if CA_CERT.exists():
        @app.get("/ca.crt")
        def ca_certificate():
            return send_file(CA_CERT, mimetype="application/x-x509-ca-cert")
    server = make_server(args.host, args.port, app, threaded=True, ssl_context=context)
    print(f"Liter-ally Trash: {scheme}://localhost:{args.port}", flush=True)
    print("Accounts: " + ("TigerData" if app.extensions["database"].is_tiger else "local development"), flush=True)
    if ip:
        print(f"On your Wi-Fi:  {scheme}://{ip}:{args.port}", flush=True)
    if scheme == "https" and CA_CERT.exists():
        print(f"To skip the certificate warning, install {scheme}://{ip or 'localhost'}:{args.port}/ca.crt "
              "once on each device (see README).", flush=True)
    elif args.host not in ("127.0.0.1", "localhost"):
        print(f"On your network: {scheme}://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.extensions["classifier"].close()
        app.extensions["rover"].close()
        if lid:
            lid.close()
        server.server_close()


if __name__ == "__main__":
    main()
