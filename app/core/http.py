import ssl
import sys


def system_ssl_context() -> ssl.SSLContext | bool:
    if sys.platform != "win32":
        return True
    try:
        import truststore
    except ImportError:
        return True
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
