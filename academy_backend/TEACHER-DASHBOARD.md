# Teaching desk

Teacher-only routes:
- /#teaching: overview with real pending applications, accepted/unverified students, questions/support awaiting replies, and failed emails.
- /#teaching/students: search, filters, pagination, individual decisions, selected-student acceptance review. Email verification remains separate. Bulk decisions run individually; partial failure reports the completed count and stops. No real applicants are automatically approved by deployment.
- /#teaching/classes: individually editable sessions with custom topics or lesson links, date/time/time zone, and meeting URL. Africa/Lagos is the initial time zone. Repeated sessions of a lesson are supported.
- /#teaching/inbox and /#teaching/inbox/support: lesson and support conversations. Reply drafts survive internal tab switches in memory, and clear on sign-out or page reload. Refresh is explicit to avoid overwriting drafts.
- /#teaching/email: latest 200 outbox messages, filters by class/status, failed-message retry, SMTP test control. Sent means SMTP accepted, not confirmed delivery.

New scheduling uses /api/class-save and /api/class-cancel. Records retain id/version, local time, IANA time zone and UTC startsAt. Server validation rejects invalid/ambiguous DST times and stale edits. New class ids are generated before saving so retrying a saved request does not duplicate invitations. Schedule edits and notification queue insertion commit together. Cancellation retains the record in the teacher list, omits it from the student schedule and sends a cancellation email.

Existing text-date schedules are retained with legacy ids until edited. They display their original time text with a date-confirmation label. The old bulk /api/schedule endpoint refuses writes after individually identified records exist, protecting classes from stale dashboard clients. Class-mail associations cover messages created by the new scheduler; older emails remain in All emails.

Attendance, cohorts, assessed mastery and broker performance metrics are not included. Completion reflects student-marked lesson practice. Tests use temporary databases, never real student records.
