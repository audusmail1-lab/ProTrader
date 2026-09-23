# Automatic class invitations

In Teaching → Classes, choose Schedule class. Pick a lesson or custom topic, choose the date, time and time zone, paste its HTTPS meeting link, then choose Schedule & send invitations. Edit a class to update details or explicitly cancel it.

Each new or changed session queues one personalized multipart email per accepted, email-verified student. Pending applicants and unverified accounts are excluded. The existing SMTP worker sends the outbox automatically. The UI reports messages queued, not inbox delivery. Delivery errors remain visible in Notification outbox with a retry action.

Invitations reuse the welcome email frame, including the dark green header, green call-to-action, footer and plain-text alternative. The message includes the lesson topic, the entered date/time/time zone, a Join class button, a copyable meeting URL, classroom and support links. Cancellations omit the old meeting link.

The schedule and email queue are saved in one database transaction. Unchanged schedules produce no duplicate invitations, including retries of a successful save. The scheduler supports multiple sessions per lesson and custom topics with structured dates and IANA time zones. It does not add automatic recurrence, calendar attachments or timed reminders.

Validation: python3 -m unittest discover -s academy_backend -p 'test_*.py'. Fixtures use isolated databases and do not send real student email.
