const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const emailLink = policy => policy.contactEmail
  ? `<a href="mailto:${esc(policy.contactEmail)}">${esc(policy.contactEmail)}</a>`
  : '<span>Contact address awaiting owner confirmation</span>';
const page = (title, introduction, body, policy) => `<section class="narrow page-heading legal-page"><p class="eyebrow">PRO TRADER ACADEMY</p><h1>${title}</h1><p>${introduction}</p>${policy.published ? `<p class="policy-date">Effective date: ${esc(policy.effectiveDate)}</p>` : '<p class="notice">Preview draft — operator details and policy choices are awaiting confirmation. Applications remain closed.</p>'}<article class="panel legal-content">${body}</article></section>`;

export function telegramLinks(telegram = {}, buttons = false) {
  const destinations = [['support','Chat on Telegram'],['community','Join Telegram Community'],['updates','Get Updates on Telegram']];
  return destinations.filter(([key]) => /^https:\/\/t\.me\/[A-Za-z0-9_+\-]+$/.test(telegram[key] || '')).map(([key,label]) => `<a ${buttons ? 'class="button secondary"' : ''} href="${esc(telegram[key])}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`).join('');
}

export function contact(policy, enrolled, telegram = {}) {
  return page('Contact the academy.', 'Enrollment, account support or a general question—we’ll help you find the next step.', `
    <h2>One address for help</h2>
    <p>For academy support, partnerships and privacy requests, email ${emailLink(policy)}.</p>
    ${policy.responseTarget ? `<p>${esc(policy.responseTarget)}</p>` : ''}
    ${policy.contactEmail ? `<p><a class="button" href="mailto:${esc(policy.contactEmail)}?subject=Pro%20Trader%20Academy%20inquiry">Write an email ↗</a></p>` : ''}
    <p>This opens your email app. Include your name, the email used for your academy account if you have one, and a short description of what you need. You can also copy the address into Gmail or another email service.</p>
    <p>Please leave out passwords, broker keys, bank details and identity documents. If we need to confirm account ownership, we will explain a proportionate way to do that.</p>
    ${telegramLinks(telegram) ? `<h2>Help and community on Telegram</h2><p>Use our private bot for app or enrollment support, follow official updates, or join the educational community. Telegram is optional; email remains available.</p><div class="actions">${telegramLinks(telegram, true)}</div><p>Support requests go privately to the academy operator. Group posts are visible to other members. Keep account information out of the community and read our <a href="#privacy">Privacy Policy</a> before sending a message.</p>` : ''}
    <h2>Questions about a lesson</h2>
    <p>${enrolled ? '<a href="#questions">Use Questions & replies</a>' : '<a href="#login">Sign in to your academy account</a>'} to keep a lesson question and your instructor’s reply together. General support and privacy requests go to the email address above.</p>
    <h2>Your information</h2>
    <p>We use your email and message to respond and keep a record of the request. Read our <a href="#privacy">Privacy Policy</a> before sending personal information.</p>
    <h2>Free for now</h2>
    <p>The current academy offering is free. There is no academy checkout, card requirement or automatic subscription. Class dates and joining information are confirmed separately.</p>
  `, policy);
}

export function privacy(policy, telegram = {}) {
  return page('Privacy Policy', 'How the academy uses your information, who helps us run it, and how to contact us about your data.', `
    <h2>1. Who is responsible</h2>
    <p>Pro Trader Academy is operated by ${esc(policy.operatorName || '[operator name pending]')}, at ${esc(policy.operatorAddress || '[contact address pending]')}. This operator decides how academy personal data is used. Contact: ${emailLink(policy)}.</p>
    <p>This notice covers the academy website, applications, classroom and academy emails. The linked Pro Trader app has a separate sign-in system. This notice does not describe broker connections, trading records or other processing inside that app; check its information before using it.</p>
    <h2>2. What the academy collects</h2>
    <ul><li><strong>Applications and accounts:</strong> name, email, experience level, learning difficulty and learning goal; application decisions and instructor messages; and your acknowledgment of the published terms and privacy notice${policy.adultOnly ? ', including confirmation that you are at least 18' : ''}.</li>
    <li><strong>Account security:</strong> a salted password hash, sign-in session records and temporary password-reset records. Your password is not stored as readable text.</li>
    <li><strong>Learning:</strong> saved lesson completion, practice notes, questions, instructor replies and their timestamps.</li>
    <li><strong>Communications:</strong> support emails, notification recipients, delivery status and limited records of account decisions.</li>
    <li><strong>Technical requests:</strong> our service providers receive connection information such as IP address, browser details and requested files when serving the site, videos or fonts. We do not run advertising trackers or audience analytics in the academy.</li></ul>
    <p>The academy does not ask for your phone number, date of birth, card details, broker credentials or financial documents. Avoid putting these in a learning goal, note, question or email.</p>
    <h2>3. Why we use it</h2>
    <p>We use application and learning information to consider your request to join and provide the educational service you request. We use account and delivery records to operate sign-in, send essential notices and protect the service. We use support messages to respond to you.</p>
    <p>Our bases are taking steps at your request and performing our service agreement for applications and learning; legitimate interests in answering inquiries and securing the service, subject to your rights; and legal obligations where applicable. Any optional use requiring consent will be explained separately. Applying does not subscribe you to marketing.</p>
    <p>Required application fields are needed to create an account and review it. You may browse the public introduction and videos without applying. Instructors review applications; admission is not decided solely by an automated system.</p>
    <h2>4. Cookies and storage</h2>
    <p>The academy uses an essential <code>academy_session</code> cookie to keep you signed in. It contains a random identifier, expires after 24 hours and is cleared when you sign out. Blocking it prevents account features from working. Password-reset links expire after 30 minutes and can be used once.</p>
    <p>Account and learning records are stored in a database on our hosted server. Access is restricted, connections use HTTPS, and private backups are access-controlled. No online service can promise absolute security.</p>
    <h2>5. Who receives information</h2>
    <p>The academy operator and authorized instructors handle applications and student conversations. Other students cannot see your account, notes or questions through the academy.</p>
    <ul><li><strong>Render:</strong> hosts the academy service and database in Frankfurt, Germany.</li>
    <li><strong>Resend:</strong> delivers account and teaching notifications using its configured Ireland sending region. It processes recipient addresses, message content and delivery records. Alerts direct you back to your private dashboard instead of including lesson questions or replies.</li>
    <li><strong>Google Gmail:</strong> receives and stores messages sent to our contact inbox. <strong>Google Fonts</strong> serves the site’s fonts.</li>
    <li><strong>Amazon CloudFront:</strong> delivers the video files. <strong>Cloudflare:</strong> provides domain, DNS and website proxy/security services, and forwards messages sent to our domain support address to Gmail. It receives connection and email-routing information needed for those services.</li></ul>
    <p>These providers process the information needed for their functions, including their security and operational records. We do not sell personal data. We may disclose information when legally required or where necessary to protect users and the service.</p>
    <h2>6. International processing</h2>
    <p>Hosting and email delivery involve Germany and Ireland, and providers may use support or infrastructure in other countries. You can contact us for information about the providers and safeguards that apply to your data.</p>
    <h2>7. How long records are kept</h2>
    ${policy.retentionApproved ? `<ul><li>Declined or withdrawn applications: up to 90 days after the final decision or withdrawal.</li><li>Active accounts and learning records: while your account remains open, then up to 90 days after closure. You may request earlier deletion where applicable.</li><li>Resolved support emails: up to 12 months after the request is closed.</li><li>Old backup copies: removed within 30 days of deletion from the active system.</li></ul><p>We review these records monthly. An unresolved request or a specific legal obligation may require limited information to be kept longer; we will explain this when relevant. Providers manage their own operational logs under their service policies.</p>` : '<p>The owner is confirming the retention schedule before applications open. This draft does not yet establish retention periods for new applicants.</p>'}
    <p>Successfully sent notification bodies are cleared from the academy’s email queue. Delivery status remains available to the instructor. An expired password-reset email is not sent.</p>
    <h2>8. Your choices and rights</h2>
    <p>Contact ${emailLink(policy)} to request access, correction, deletion, restriction or a portable copy of applicable records, or to object to processing. Where we rely on consent, you can withdraw it; this does not undo earlier lawful processing. Rights may be subject to legal limits. We may need to verify that a request is yours without collecting more information than necessary.</p>
    <p>You can also raise a concern with the <a href="https://ndpc.gov.ng/" target="_blank" rel="noopener noreferrer">Nigeria Data Protection Commission</a>. Contacting us first is welcome but does not remove your right to complain.</p>
    <h2>9. Age requirements</h2>
    <p>${policy.adultOnly ? 'The current academy intake is for adults aged 18 and over. We ask for age confirmation rather than your full date of birth. Contact us if you believe a child has submitted an application so we can investigate and remove inappropriate records.' : 'Age eligibility is being confirmed before this intake opens. Do not submit a child’s information through this preview.'}</p>
    ${telegramLinks(telegram) ? `<h2>10. Optional Telegram support and community</h2><p>If you use our Telegram bot, we receive your Telegram chat ID and the name, issue category, device/browser, description and optional screenshot you choose to submit. We use these to answer your request and send replies in the same private bot chat. Using Telegram does not create an academy account or subscribe you to marketing.</p><p>Unfinished support drafts are stored for up to 24 hours. Submitted requests are held in a private database on Render and sent to the operator’s Telegram inbox. Closed requests are kept for up to 12 months. Screenshot files remain on Telegram; our database keeps a file reference. We review open requests and inbox copies monthly and apply the same retention schedule. Backup copies follow the deletion schedule above.</p><p>Telegram processes chats, media and connection data under its own <a href="https://telegram.org/privacy" target="_blank" rel="noopener noreferrer">Privacy Policy</a>, including international processing. Bot chats are cloud chats, not end-to-end encrypted secret chats. Community posts and your Telegram profile may be visible to other members according to your Telegram settings. Do not share credentials or sensitive financial information. Email ${emailLink(policy)} for access or deletion requests, including copies in our support inbox.</p>` : ''}
    <h2>${telegramLinks(telegram) ? '11' : '10'}. Updates</h2>
    <p>We will update this page and its effective date when our practices change, and draw attention to material changes through the academy or service email. New optional processing will be explained before it starts.</p>
  `, policy);
}

export function terms(policy) {
  return page('Terms of Use', 'The terms for using the academy’s learning materials, account and instructor support.', `
    <h2>1. The academy service</h2><p>Pro Trader Academy, operated by ${esc(policy.operatorName || '[operator name pending]')}, provides educational lessons, guided simulated exercises and instructor support. These terms cover the academy. Separate terms may apply to the linked trading app, brokers or class-meeting services.</p>
    <h2>2. Joining and account access</h2><p>${policy.adultOnly ? 'You must be at least 18 to apply. ' : ''}Provide accurate application details, use an email address you control and keep your password private. Applying does not guarantee acceptance or reserve a class place. Classroom access opens after instructor review and verification of email ownership. Contact us if your account may have been accessed without permission.</p>
    <h2>3. Free access</h2><p>The current academy offering is free. We do not collect academy payments or card details, and there is no automatic paid renewal. If we offer paid services later, pricing and any payment or refund terms will be shown before you choose to purchase. You will not be charged merely because you already have an academy account.</p>
    <h2>4. Learning and trading risk</h2><p>Lessons, videos, examples and replies are for education. They are not personalized investment advice, trade instructions or a promise of profit. Practice outcomes do not predict live results. Read the <a href="#risk">Trading Risk Disclaimer</a> before using the material.</p>
    <h2>5. Respectful and lawful use</h2><p>Do not misuse accounts, harass others, submit unlawful content, attempt unauthorized access or interfere with security. Do not upload passwords, broker keys or financial documents. You are responsible for the material you submit and must have permission to share it.</p>
    <h2>6. Learning materials</h2><p>You may use the lessons and supplied downloads for your own learning. Academy branding and original materials belong to the operator or their licensors; third-party rights remain with their owners. Ask for permission before selling or redistributing protected materials. This does not limit uses permitted by law. You retain your rights in your own notes and questions and allow us to store and use them to provide the service.</p>
    <h2>7. Availability and changes</h2><p>Class times and joining details will be confirmed in your classroom. Content, schedules and features may change, and maintenance or provider outages can interrupt access. We will communicate material service changes where reasonably possible. Materials may contain errors; tell us if something needs correcting.</p>
    <h2>8. Responsibility and legal rights</h2><p>You make your own trading decisions and should check information independently. We do not guarantee accuracy, uninterrupted access or any trading result. To the extent permitted by applicable law, we exclude liability for indirect or consequential loss caused by reliance on educational examples. Nothing in these terms excludes liability or consumer and data-protection rights that cannot lawfully be excluded.</p>
    <h2>9. Suspension and closure</h2><p>We may restrict access to address misuse, protect accounts or comply with law. Where appropriate, we will explain the reason and how to raise a concern. You can request account closure at ${emailLink(policy)}. Record handling is explained in the <a href="#privacy">Privacy Policy</a>.</p>
    <h2>10. Changes and contact</h2><p>We will date updates to these terms and notify account holders of material changes. Where agreement is needed, we will ask for it. For questions or concerns, contact ${emailLink(policy)}.</p>
  `, policy);
}

export function risk(policy) {
  return page('Trading Risk Disclaimer', 'Learn the process. Understand the risk before making a financial decision.', `
    <h2>Education, with no promise of returns</h2><p>Pro Trader Academy provides educational content, examples and tools for learning. The academy does not provide personalized investment advice, portfolio management, brokerage services or guarantees of profit.</p>
    <h2>Live trading can lose money</h2><p>Trading and investing carry risk, including loss of capital. Leverage can magnify losses. Examples, historical results and case studies do not predict future outcomes. You are responsible for deciding whether any activity is suitable for you and for checking the rules and risks of any app or broker you use.</p>
    <h2>Practice is a simulation</h2><p>The academy’s supplied charts and tickets use fictional examples. They cannot place orders or move money. Simulated results leave out some real-world conditions, costs and execution differences. Confirm the mode and account before taking any action in a separate trading app.</p>
    <h2>Ask for the right kind of help</h2><p>Your instructor can explain a lesson or workflow. For advice about your own finances, seek a suitably qualified professional. Do not share broker passwords, access keys or financial documents with the academy.</p>
  `, policy);
}
