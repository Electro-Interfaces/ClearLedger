"""Read-only source approval wrapper; no imports from the package before hash validation."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
APPROVED = {
    '__init__.py': 'e0fef5357ac1b25431474416a569994d118e4907d83fde1e6460bfb334dc7fea',
    'catalog.py': '6460f815ecb53436981c3633769a5792642824923197f5cf15277c31f356a242',
    'errors.py': 'f746049fc8579a22f3d15c0c0764dc3db30ac74754c43c2851ba75eb6045504b',
    'journal.py': '16394ef23a5074c5c42c7780b30e15389c5eb4e6b03fb79a0afc1539db18fe39',
    'manifest.json': 'ef4189a61f162c81dda01b6602eae3a362c242e95ee954c6c971db9ff6404116',
    'manifest.py': '55e5d7caca47c6bbd243f1e02e9e8a764b163067b16cd8eb41052967e4c78a09',
    'revisions/0001_contract.json': '19450cd978b88df859aa6f4d33ad745f48fb4f0b55a17850aa875e75b66a0194',
    'revisions/0001_product_api_budgets.sql': '98da0597f9e4d6a3d21326a310496b790753a5d9e766cfec8005d84641dd2ac9',
    'revisions/__init__.py': '1a89417e8d0ed0684ad1055568dacea57b108b38b20ba76470871e5faad2c146',
    'revisions/catalog_v1.py': 'ae3c42d51a7e7e37ee293b2c64f73addd421cf792b63af6bed6c36b1ed5f24f5',
    'revisions/journal_v1.sql': 'c872f3746c0df17c03bb6c87db8b8bebd22713bc326fca83b43e3aa9f8dfed5a',
    'runner.py': '375a6f68ca9024895e463584b7f79201b48500ab527d9cdcab16fdc0b2f41504',
    'tests/__init__.py': 'b75801b2fdeac6f92ffe4796227b1c5ea85419d8f938040221e6e3924b492db5',
    'tests/run_postgres.py': '3f0f1b4081caaf000ec2f30d648080d3012a13ed9f38d3bed41fe9b83b173968',
    'tests/test_pure.py': '635291c1e14b3c6a18ab8371a53d7e7ff63be48e51f0b1cd1b5d2e16bb8722fc',
}
APPROVED_BUNDLE = '43388867cac2ed59171a32ce7bd6389d3b649017cc5f1eef26c26d007db19e6c'


def verify_approval():
    actual={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
        and p!=ROOT/'tests/approved_postgres.py'}
    digest=hashlib.sha256(('\n'.join(name+'\0'+sha for name,sha in actual.items())+'\n').encode()).hexdigest()
    if actual!=APPROVED or digest!=APPROVED_BUNDLE:
        raise RuntimeError('Approved source bundle mismatch')


def main():
    try:
        if sys.argv[1:]!=['--execute-approved-contract-tests']:
            raise RuntimeError('Exact approved argument required')
        verify_approval()
    except Exception:
        print(json.dumps({'ok':False,'code':2,'phase':'source_approval'},sort_keys=True))
        return 2
    import runpy
    target=ROOT/'tests/run_postgres.py'
    sys.argv=[str(target),'--execute-approved-contract-tests']
    runpy.run_path(str(target),run_name='__main__')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
