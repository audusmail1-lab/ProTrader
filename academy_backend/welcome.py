"""Acceptance email content. Personal text is always escaped in the HTML version."""
from html import escape


WELCOME_SUBJECT = 'Welcome to Pro Trader Academy — your application is accepted'


def acceptance_message(name, note, origin, app_url='', contact_email=''):
    classroom = origin + '/#classroom'
    introduction = origin + '/#start'
    videos = origin + '/#library'
    contact = origin + '/#contact'
    opening = (
        'Your application has been accepted, and your classroom is ready. '
        'Welcome to Pro Trader Academy.'
    )
    purpose = (
        'We look forward to helping you understand the markets, develop a thoughtful '
        'practice routine and learn to use PROTrader with confidence. You can start '
        'with the basics and build your understanding one step at a time.'
    )
    steps = [
        ('Open your classroom', 'Sign in with the email address and password you used to apply. Your lessons, saved notes and instructor replies are there.', classroom),
        ('Begin with Start here', 'Try the workspace introduction, then continue to your first lesson. No prior trading experience is needed.', introduction),
        ('Explore the short video guides', 'Use these as demonstrations and recaps alongside the lessons. Write down anything you would like to ask in class.', videos),
    ]
    schedule = (
        'Check the Class schedule section in your classroom for confirmed dates, '
        'times, time zones and joining links. If no session is listed yet, the '
        'schedule is still being arranged. You can explore the introduction and '
        'available materials while you wait.'
    )
    app_copy = (
        'When you are ready, explore the PROTrader app in your browser. Follow your '
        'instructor’s setup guidance and confirm paper practice mode before entering '
        'any order. Academy access does not create a broker account.'
    )
    help_copy = (
        'For a lesson question, use Questions & replies in your classroom. '
        'For sign-in or technical help, visit our Contact page.'
    )
    closing = 'Take your time, ask questions and focus on understanding each step. We look forward to learning with you.'
    disclaimer = 'Educational only; not investment advice. Trading involves risk, and results are never guaranteed.'
    paragraphs = [f'Hello {name},', opening, purpose]
    if note:
        paragraphs += ['A NOTE FROM YOUR INSTRUCTOR', note]
    paragraphs += ['YOUR FIRST STEPS']
    paragraphs += [f'{i}. {title}\n{description}\n{url}' for i, (title, description, url) in enumerate(steps, 1)]
    paragraphs += ['YOUR NEXT CLASS', schedule]
    if app_url:
        paragraphs += ['YOUR PRACTICE WORKSPACE', app_copy, app_url]
    paragraphs += ['WE’RE HERE TO HELP', help_copy, contact]
    if contact_email:
        paragraphs += ['Email: ' + contact_email]
    paragraphs += [closing, 'Warm regards,\nPro Trader Academy', disclaimer]
    body = '\n\n'.join(paragraphs)

    def paragraph(text):
        return f'<p style="margin:0 0 20px;line-height:1.65;overflow-wrap:anywhere">{escape(text)}</p>'

    def section(title, text):
        return f'<h2 style="margin:28px 0 12px;font-size:19px;line-height:1.4;color:#1b3020">{escape(title)}</h2>{paragraph(text)}'

    note_html = ''
    if note:
        safe_note = escape(note).replace('\n', '<br>')
        note_html = f'<div style="margin:24px 0;padding:20px;background-color:#f1f5e9;border-left:4px solid #809b42"><h2 style="margin:0 0 10px;font-size:17px;color:#1b3020">A note from your instructor</h2><p style="margin:0;line-height:1.65;overflow-wrap:anywhere">{safe_note}</p></div>'
    steps_html = ''.join(
        f'<li style="margin:0 0 20px;padding-left:4px"><a href="{escape(url, quote=True)}" style="color:#28552f;font-weight:bold;text-decoration:underline">{escape(title)}</a><br>{escape(description)}</li>'
        for title, description, url in steps
    )
    app_html = ''
    if app_url:
        app_html = section('Your practice workspace', app_copy) + f'<p style="margin:0 0 20px"><a href="{escape(app_url, quote=True)}" style="color:#28552f;text-decoration:underline">Open Trading App →</a></p>'
    support_html = f'<a href="{escape(contact, quote=True)}" style="color:#28552f;text-decoration:underline">Contact support</a>'
    if contact_email:
        support_html += f'<br><a href="mailto:{escape(contact_email, quote=True)}" style="color:#28552f;text-decoration:underline;overflow-wrap:anywhere">{escape(contact_email)}</a>'
    content = f'''{paragraph('Hello ' + name + ',')}{paragraph(opening)}{paragraph(purpose)}
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:6px 0 24px"><tr><td style="background-color:#cbe88a;border-radius:6px"><a href="{escape(classroom, quote=True)}" style="display:inline-block;padding:16px 22px;color:#142019;font-weight:bold;text-decoration:none">Open your classroom →</a></td></tr></table>
{note_html}
<h2 style="margin:28px 0 14px;font-size:19px;color:#1b3020">Your first steps</h2>
<ol style="margin:0;padding-left:24px;line-height:1.65">{steps_html}</ol>
{section('Your next class', schedule)}{app_html}{section('We’re here to help', help_copy)}
<p style="margin:0 0 24px;line-height:1.7">{support_html}</p>
{paragraph(closing)}<p style="margin:0;line-height:1.65">Warm regards,<br><strong>Pro Trader Academy</strong></p>'''
    html = email_layout(WELCOME_SUBJECT, 'Your classroom is ready. Here are your first steps at Pro Trader Academy.', 'APPLICATION ACCEPTED', 'Your learning journey starts here.', content, origin)
    return WELCOME_SUBJECT, body, html


def email_layout(subject, preheader, label, headline, content, origin):
    """Shared welcome/invitation frame; content is trusted, pre-escaped markup."""
    disclaimer = 'Educational only; not investment advice. Trading involves risk, and results are never guaranteed.'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background-color:#f3f4f0;color:#30372f;font-family:Arial,Helvetica,sans-serif;font-size:16px">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f0"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;background-color:#ffffff;border:1px solid #e0e5da">
<tr><td style="padding:32px 24px;background-color:#142019;color:#ffffff">
<p style="margin:0 0 22px;color:#cbe88a;font-size:13px;font-weight:bold;letter-spacing:2px">PRO TRADER ACADEMY</p>
<p style="margin:0 0 10px;color:#cbe88a;font-size:13px;letter-spacing:1px">{escape(label)}</p>
<h1 style="margin:0;font-size:32px;line-height:1.2;color:#ffffff">{escape(headline)}</h1>
</td></tr>
<tr><td style="padding:28px 24px">
{content}
</td></tr>
<tr><td style="padding:20px 24px;background-color:#f5f7f1;font-size:12px;line-height:1.65;color:#4e584d">{escape(disclaimer)}<br><a href="{escape(origin + '/#privacy', quote=True)}" style="color:#28552f">Privacy Policy</a> · <a href="{escape(origin + '/#terms', quote=True)}" style="color:#28552f">Terms of Use</a></td></tr>
</table></td></tr></table>
</body></html>'''
