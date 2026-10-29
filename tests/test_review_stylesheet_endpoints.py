"""Real stylesheet responses must be usable with the app's nosniff policy."""
from pathlib import Path
import re
import unittest

from fastapi.testclient import TestClient
import dashboard


class ReviewStylesheetEndpointTests(unittest.TestCase):
    def test_linked_review_stylesheets_have_css_mime_security_headers_and_real_content(self):
        root = Path(dashboard.__file__).resolve().parent
        html = (root / 'protrader_mobile.html').read_text()
        expected = {
            'lesson-practice.css': '.lp-',
            'oracle-workspace.css': '.ow-',
            'oracle-analyst.css': '.oa-',
        }
        links = re.findall(r'<link\s+[^>]*href="([^"]+\.css(?:\?[^\"]*)?)"', html)
        client = TestClient(dashboard.app)
        for filename, selector in expected.items():
            with self.subTest(filename=filename):
                url = next((url for url in links if url.split('?')[0] == '/static/' + filename), None)
                self.assertIsNotNone(url, 'The page must link the actual stylesheet')
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get('content-type', '').split(';')[0], 'text/css')
                self.assertEqual(response.headers.get('x-content-type-options'), 'nosniff')
                self.assertEqual(response.content, (root / 'static' / filename).read_bytes())
                self.assertIn(selector, response.text)
                self.assertNotIn('<!DOCTYPE html>', response.text)
                conditional = client.get(url, headers={'If-None-Match': response.headers['etag']})
                self.assertEqual(conditional.status_code, 304)
                self.assertEqual(conditional.headers.get('x-content-type-options'), 'nosniff')


if __name__ == '__main__':
    unittest.main()
