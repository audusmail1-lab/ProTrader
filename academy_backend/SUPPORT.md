# Academy support

Website visitors use Need help. Instructors answer at /#support-inbox. Guests retain access through a seven-day HttpOnly cookie; signed-in conversations belong to their account. Verified students receive a generic email notification when a human replies. Instructor conversations refresh with the Refresh conversations button; open visitor chats poll every five seconds.

## Optional OpenAI activation

Set ACADEMY_SUPPORT_OPENAI_API_KEY securely in the Academy Render environment, then ACADEMY_SUPPORT_AI_ENABLED=true. Never put the key in browser code or Git. ACADEMY_SUPPORT_MODEL defaults to gpt-4.1-mini. Without configuration, the widget provides human messaging.

AI is opt-in, labelled, and limited to public Academy facts. It receives up to eight recent visitor/assistant messages, no private student records or tools. Responses uses store=false; this does not mean all provider retention is disabled. Requests time out after 12 seconds and fall back to human support. Human requests and account issues bypass AI. Rate limits include 300 AI requests per server process per day; they reset on restart and are not a billing cap. Configure OpenAI project budgets and alerts separately.

Conversations remain in the Academy SQLite database and follow the published support retention review; cookie expiry does not delete transcripts. Include support tables in backup and privacy deletion procedures. The instructor list currently shows the latest 100 conversations.

## Validation

Run python3 -m unittest discover -s academy_backend -p 'test_*.py'. Tests use temporary databases and mocked OpenAI responses. Live provider validation requires the configured server credential.
