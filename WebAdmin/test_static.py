"""Static Pages + API integration checks, not a substitute for hosted tests."""
from pathlib import Path
import re
import unittest

HERE = Path(__file__).parent
ROOT = HERE.parent


class PagesChecks(unittest.TestCase):
    def test_static_website_uses_relative_paths(self):
        html = (HERE / 'index.html').read_text()
        javascript = (HERE / 'admin.js').read_text()
        for name in ['admin.css', 'admin.js', 'config.js']:
            self.assertIn('./' + name, html)
            self.assertTrue((HERE / name).is_file())
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        accessed = set(re.findall(r"\$\('([^']+)'\)", javascript))
        self.assertEqual(set(), accessed - ids)
        self.assertIn('window.TDS_CONFIG', javascript)
        self.assertNotIn('localStorage', javascript.replace('localStorage, cookies, URLs or build artifacts.', ''))

    def test_pages_workflow_and_backend_are_separate(self):
        workflow = (ROOT / '.github/workflows/deploy-admin-pages.yml').read_text()
        self.assertIn('actions/upload-pages-artifact@v3', workflow)
        self.assertIn('actions/deploy-pages@v4', workflow)
        self.assertIn('AOV_LICENSE_SERVER_URL', workflow)
        self.assertNotIn('LICENSE_ADMIN_TOKEN:', workflow)
        c = (ROOT / 'OnlineService/app.py').read_text()
        self.assertIn('ADMIN_ALLOWED_ORIGINS', c)
        self.assertIn('CORSMiddleware', c)

if __name__ == '__main__':
    unittest.main()
