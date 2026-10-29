"""Destructive-operation boundary checks, deliberately independent of conftest."""
import unittest
from guard import validate

BASE = {'RUN_PARTNER_PILOT_SANDBOX':'1',
    'TEST_DATABASE_URL':'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_partner_pilots_test',
    'UPLOAD_DIR':'/tmp/partner-pilot-sandbox-test-uploads'}


class GuardTest(unittest.TestCase):
    def test_read_configuration_never_implies_ddl_authority(self):
        validate(BASE)
        with self.assertRaises(ValueError): validate(BASE,ddl=True)
        validate({**BASE,'PARTNER_SANDBOX_SQL_WINDOW':'explicit-root-message-id'},ddl=True)

    def test_flag_url_and_upload_are_independently_required(self):
        for name in BASE:
            with self.subTest(name=name),self.assertRaises(ValueError):
                validate({k:v for k,v in BASE.items() if k!=name})

    def test_connection_overrides_remote_and_other_databases_rejected(self):
        raw=BASE['TEST_DATABASE_URL']
        for url in [raw+'?host=remote',raw+'#override',raw.replace('127.0.0.1','10.10.70.53'),
            raw.replace('33546','5432'),raw.replace('api_partner_pilots_test','clearledger_test'),
            raw.replace('api_test_only','anything'),raw.replace('clearledger:','postgres:')]:
            with self.subTest(target='redacted'),self.assertRaises(ValueError):
                validate({**BASE,'TEST_DATABASE_URL':url})

if __name__=='__main__':unittest.main()
