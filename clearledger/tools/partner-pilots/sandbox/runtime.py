"""Закрытые файлы и краткоживущие сертификаты fixture; без импорта Ядра."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import ipaddress
import json
import os

HERE = Path(__file__).resolve().parent
PRIVATE = HERE.parents[2] / '.artifacts' / 'partner-pilot-sandbox'


def private_dir():
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    PRIVATE.chmod(0o700)
    return PRIVATE


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
    temporary.replace(path)
    path.chmod(0o600)


def prepare():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    root = private_dir()
    path = root / 'owner-state.json'
    if path.exists():
        return json.loads(path.read_text())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic Partner Pilot CA')])
    at = datetime.now(timezone.utc)
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(at-timedelta(minutes=5))
        .not_valid_after(at+timedelta(days=3)).add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
        .add_extension(x509.KeyUsage(True,False,False,False,False,True,True,False,False),True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),False)
        .sign(key, hashes.SHA256()))
    def save(target, data):
        fd = os.open(root/target, os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream: stream.write(data)
    save('ca.pem', ca.public_bytes(serialization.Encoding.PEM))
    save('ca.key', key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    from cryptography.x509.oid import ExtendedKeyUsageOID
    for label in ('issuer','callback'):
        leaf = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,label+' synthetic loopback')]))
            .issuer_name(name).public_key(leaf.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(at-timedelta(minutes=5)).not_valid_after(at+timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1' if label=='issuer' else '127.0.0.2'))]),False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf.public_key()),False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),False).sign(key,hashes.SHA256()))
        save(label+'.pem',cert.public_bytes(serialization.Encoding.PEM))
        save(label+'.key',leaf.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    state={'status':'tls-ready-awaiting-sql-window', 'caPath':str(root/'ca.pem'),
        'callbackCertPath':str(root/'callback.pem'),'callbackKeyPath':str(root/'callback.key')}
    write_json(path,state)
    return state
