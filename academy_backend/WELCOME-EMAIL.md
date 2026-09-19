# Student acceptance welcome

When an instructor verifies an applicant, chooses **Accepted** and saves the decision, the Academy queues a personalized welcome email. It includes a classroom button, sign-in guidance, beginner introduction, video guides, class-schedule guidance, the configured app link and the published support email.

The optional **Message for the applicant** appears as a separate instructor note in the email and is also saved in the student's account. Leave it blank to send the standard welcome. Saving an Accepted decision again queues another welcome; it is not a bulk resend tool.

The email has branded HTML and a plain-text alternative. It uses the student's actual name, escapes personal text, uses the configured Academy/app URLs and includes no tracking images or remote fonts. Pending, information-needed and declined decisions retain their existing status notifications.

Deploying this change does not resend messages to existing students or rewrite previously queued emails. Confirmed class details are read in the classroom; the welcome does not promise an automated schedule announcement.

The existing mail queue gains an additive `html_body` column on startup. Both text and HTML are cleared after successful delivery (or reset expiry); failed messages retain their content for the existing manual retry process. Email identity and retry protections are unchanged.

Validation: acceptance-to-outbox integration, optional instructor note, HTML escaping, multipart email, queue-content cleanup and migration of existing mail. Desktop and 390px browser previews were checked. Inbox rendering across all email clients has not been tested.
