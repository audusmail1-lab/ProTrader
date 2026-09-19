import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from server import Academy
from welcome import acceptance_message


class WelcomeTests(unittest.TestCase):
    def test_personal_text_is_literal_and_optional_sections_are_omitted(self):
        _, body, html = acceptance_message('A & B <img src=x>', '<script>alert(1)</script>\nSecond line', 'https://academy.example.com')
        self.assertIn('Hello A & B <img src=x>,', body)
        self.assertNotIn('<img', html)
        self.assertNotIn('<script>', html)
        self.assertIn('A &amp; B &lt;img src=x&gt;', html)
        self.assertIn('&lt;/script&gt;<br>Second line', html)
        self.assertNotIn('mailto:', html)
        self.assertNotIn('Open Trading App', html)
        _, body, html = acceptance_message('Sample Learner', '', 'https://academy.example.com')
        self.assertNotIn('A note from your instructor', html)
        self.assertNotIn('A NOTE FROM YOUR INSTRUCTOR', body)
        self.assertIn('schedule is still being arranged', body)

    def test_existing_mail_survives_html_column_migration(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ACADEMY_MAIL_ENABLED':'false'}):
            db = sqlite3.connect(Path(directory)/'academy.sqlite3')
            db.execute("CREATE TABLE mail(id INTEGER PRIMARY KEY,recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT DEFAULT 'queued',error TEXT DEFAULT '',created REAL NOT NULL,delivery_key TEXT)")
            db.execute("INSERT INTO mail VALUES(1,'student@example.com','Existing update','Saved body','queued','',1,'stable-key')")
            db.commit(); db.close()
            app = Academy(directory,'https://academy.example.com')
            with app.db() as db:
                row = db.execute('SELECT body,html_body,delivery_key,status FROM mail').fetchone()
                self.assertEqual(tuple(row),('Saved body','','stable-key','queued'))
                self.assertEqual(db.execute('SELECT count(*) FROM mail').fetchone()[0],1)


if __name__ == '__main__':
    unittest.main()
