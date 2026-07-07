import os
import ssl


def build_verified_ssl_context() -> ssl.SSLContext:
    """Builds a TLS context backed by certifi's CA bundle.

    Shared by every outbound HTTPS call in the backend so we don't fall back to
    ssl._create_unverified_context() (no certificate validation, MITM-able) on
    Render/containers where the system CA bundle can be stale or missing.
    """
    try:
        # pyrefly: ignore [missing-import]
        import certifi
        ca_bundle = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", ca_bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)
        return ssl.create_default_context(cafile=ca_bundle)
    except ImportError:
        print("[ssl_utils] certifi not installed — falling back to the system default "
              "CA bundle. Run: pip install certifi")
        return ssl.create_default_context()


SSL_CONTEXT = build_verified_ssl_context()
