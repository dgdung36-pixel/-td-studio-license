"""Executable API regression coverage for license lifecycle and privacy controls."""
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import ipaddress

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_TMP = tempfile.TemporaryDirectory(prefix='td-license-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_TMP.name) / 'licenses.sqlite3')
os.environ['APP_ENV'] = 'test'
os.environ['LICENSE_ADMIN_TOKEN'] = 'test-admin-' + 's' * 45
os.environ['ACCESS_LOG_RETENTION_DAYS'] = '30'
os.environ['ADMIN_ALLOWED_ORIGINS'] = 'https://studio-example.github.io'

from fastapi.testclient import TestClient
from app import app
import license_service

ADMIN = {'Authorization': 'Bearer ' + os.environ['LICENSE_ADMIN_TOKEN']}


class LicenseAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_pages_origin_cors_allowlist(self):
        good = self.client.options('/v1/admin/keys', headers={
            'Origin': 'https://studio-example.github.io',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'authorization',
        })
        self.assertEqual(good.status_code, 200, good.text)
        self.assertEqual(good.headers.get('access-control-allow-origin'), 'https://studio-example.github.io')
        bad = self.client.options('/v1/admin/keys', headers={
            'Origin': 'https://untrusted-elsewhere.example',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'authorization',
        })
        self.assertEqual(bad.status_code, 400)
        self.assertNotIn('access-control-allow-origin', bad.headers)

    def create(self, label='Subscriber', days=30, maximum=1):
        response = self.client.post('/v1/admin/keys', headers=ADMIN, json={
            'label': label, 'valid_days': days, 'max_devices': maximum
        })
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data['key_once'].startswith('TD-'))
        return data

    def activate(self, key, device=None):
        if device is None:
            device = str(uuid.uuid4())
        result = self.client.post('/v1/license/activate', json={
            'license_key': key, 'device_id': device, 'privacy_notice_accepted': True
        })
        return result, device

    def test_ip_forwarding_requires_explicit_trusted_peer(self):
        fake = SimpleNamespace(client=SimpleNamespace(host='198.51.100.7'),
                               headers={'x-forwarded-for': '203.0.113.50'})
        with patch.object(license_service, 'TRUSTED_PROXIES', (ipaddress.ip_network('10.0.0.0/8'),)):
            self.assertEqual(license_service.client_ip(fake), '198.51.100.7')
            fake.client.host = '10.0.0.10'
            fake.headers = {'x-forwarded-for': '203.0.113.50, 10.0.0.9'}
            self.assertEqual(license_service.client_ip(fake), '203.0.113.50')
            fake.headers = {'x-forwarded-for': 'spoof, 203.0.113.50, 10.0.0.9'}
            self.assertEqual(license_service.client_ip(fake), '203.0.113.50')
            fake.headers = {'x-forwarded-for': 'spoof, 10.0.0.9'}
            self.assertEqual(license_service.client_ip(fake), '10.0.0.10')

    def test_create_activate_verify_and_ip_audit(self):
        issue = self.create('Case Alpha')
        activated, device = self.activate(issue['key_once'])
        self.assertEqual(activated.status_code, 200, activated.text)
        token = activated.json()['session_token']
        self.assertTrue(len(token) > 40)
        verified = self.client.post('/v1/license/verify', json={'session_token': token, 'device_id': device})
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertTrue(verified.json()['valid'])
        events = self.client.get('/v1/admin/logs', headers=ADMIN).json()['items']
        self.assertTrue(any(item['event'] == 'verify' and item['result'] == 'allowed' for item in events))
        self.assertTrue(all('ip' in item for item in events))
        self.assertNotIn(issue['key_once'], str(self.client.get('/v1/admin/keys', headers=ADMIN).json()))

    def test_rotated_key_invalidates_original_and_session(self):
        issue = self.create('Rotate Beta')
        activation, device = self.activate(issue['key_once'])
        token = activation.json()['session_token']
        changed = self.client.post(f"/v1/admin/keys/{issue['item']['id']}/rotate", headers=ADMIN, json={'reset_devices': True})
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed.json()['key_once'], issue['key_once'])
        self.assertEqual(self.activate(issue['key_once'])[0].status_code, 401)
        self.assertEqual(self.client.post('/v1/license/verify', json={'session_token': token, 'device_id': device}).status_code, 401)
        self.assertEqual(self.activate(changed.json()['key_once'])[0].status_code, 200)

    def test_revoke_and_restore(self):
        issue = self.create('Revoke Gamma')
        item_id = issue['item']['id']
        self.assertEqual(self.client.post(f'/v1/admin/keys/{item_id}/revoke', headers=ADMIN).status_code, 200)
        self.assertEqual(self.activate(issue['key_once'])[0].status_code, 401)
        self.assertEqual(self.client.post(f'/v1/admin/keys/{item_id}/restore', headers=ADMIN).status_code, 200)
        self.assertEqual(self.activate(issue['key_once'])[0].status_code, 200)

    def test_device_limit_and_unbind(self):
        issue = self.create('Limit Delta')
        self.assertEqual(self.activate(issue['key_once'])[0].status_code, 200)
        self.assertEqual(self.activate(issue['key_once'])[0].status_code, 403)
        key_id = issue['item']['id']
        devices = self.client.get(f'/v1/admin/keys/{key_id}/devices', headers=ADMIN).json()['items']
        self.assertEqual(len(devices), 1)
        self.assertEqual(self.client.delete(f"/v1/admin/keys/{key_id}/devices/{devices[0]['id']}", headers=ADMIN).status_code, 200)
        self.assertEqual(self.activate(issue['key_once'])[0].status_code, 200)

    def test_admin_token_required_and_privacy_notice(self):
        self.assertEqual(self.client.get('/v1/admin/keys').status_code, 401)
        self.assertEqual(self.client.get('/v1/admin/keys', headers={'Authorization': 'Bearer wrong'}).status_code, 401)
        self.assertEqual(self.client.post('/v1/license/activate', json={
            'license_key': 'TD-' + 'e' * 35, 'device_id': str(uuid.uuid4()), 'privacy_notice_accepted': False
        }).status_code, 422)
        self.assertEqual(self.client.get('/admin').status_code, 200)
        self.assertEqual(self.client.get('/admin/admin.js').status_code, 200)
        self.assertIn('no-store', self.client.get('/admin').headers['cache-control'])

    def test_delete_key_and_clear_access_logs(self):
        issue = self.create('Erase Epsilon')
        self.assertEqual(self.activate(issue['key_once'])[0].status_code, 200)
        self.assertEqual(self.client.delete(f"/v1/admin/keys/{issue['item']['id']}", headers=ADMIN).status_code, 200)
        self.assertEqual(self.activate(issue['key_once'])[0].status_code, 401)
        wiped = self.client.delete('/v1/admin/logs', headers=ADMIN)
        self.assertGreaterEqual(wiped.json()['deleted_count'], 1)
        self.assertEqual(self.client.get('/v1/admin/logs', headers=ADMIN).json()['items'], [])

    def test_logout_invalidates_session_and_device_id_binding(self):
        issue = self.create('Logout Zeta')
        activated, dev = self.activate(issue['key_once'])
        token = activated.json()['session_token']
        another = str(uuid.uuid4())
        self.assertEqual(self.client.post('/v1/license/verify', json={'session_token': token, 'device_id': another}).status_code, 401)
        self.assertEqual(self.client.post('/v1/license/logout', json={'session_token': token, 'device_id': dev}).status_code, 200)
        self.assertEqual(self.client.post('/v1/license/verify', json={'session_token': token, 'device_id': dev}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
