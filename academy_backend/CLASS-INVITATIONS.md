# Automatic class invitations

In Teaching → Class schedule, enter the confirmed date, time and time zone for the lesson, paste its HTTPS meeting link, then choose Save schedule & send invitations. Both fields are required for a scheduled class; leave both empty for unused lessons. Clearing both fields on an existing class sends a cancellation.

Each new or changed session queues one personalized multipart email per accepted, email-verified student. Pending applicants and unverified accounts are excluded. The existing SMTP worker sends the outbox automatically. The UI reports messages queued, not inbox delivery. Delivery errors remain visible in Notification outbox with a retry action.

Invitations reuse the welcome email frame, including the dark green header, green call-to-action, footer and plain-text alternative. The message includes the lesson topic, the entered date/time/time zone, a Join class button, a copyable meeting URL, classroom and support links. Cancellations omit the old meeting link.

The schedule and email queue are saved in one database transaction. Unchanged schedules produce no duplicate invitations, including retries of a successful save. This remains the existing seven-lesson schedule; it does not add recurrence, calendar attachments or timed reminders. Dates are instructor-entered text and must include the time zone.

Validation: python3 -m unittest discover -s academy_backend -p 'test_*.py'. Fixtures use isolated databases and do not send real student email.
