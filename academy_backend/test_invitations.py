import unittest
from invitations import class_message

class InvitationTests(unittest.TestCase):
    def test_details_are_escaped_and_plain_text_has_link(self):
        subject,body,html=class_message('A <script>x</script>', 'Charts & <practice>', '3 October, 18:00 WAT', 'https://example.com/join?a=1&b=2', 'https://academy.example')
        self.assertIn('Charts & <practice>',subject)
        self.assertIn('https://example.com/join?a=1&b=2',body)
        self.assertIn('3 October, 18:00 WAT',body)
        self.assertNotIn('<script>',html)
        self.assertIn('Charts &amp; &lt;practice&gt;',html)
        self.assertIn('href="https://example.com/join?a=1&amp;b=2"',html)
        self.assertIn('background-color:#142019',html)
        self.assertIn('Privacy Policy',html)

    def test_cancellation_never_repeats_meeting_link(self):
        subject,body,html=class_message('Learner','Chart class','3 October, 18:00 WAT','https://example.com/old-meeting','https://academy.example','cancelled')
        self.assertIn('cancelled',subject)
        self.assertNotIn('https://example.com/old-meeting',body+html)
        self.assertNotIn('Join class →',html)
