"""Class invitations reuse the Academy welcome email layout and delivery outbox."""
from html import escape
from welcome import email_layout


def class_message(name, title, when, url, origin, kind='scheduled'):
    cancelled = kind == 'cancelled'
    subject = f"Academy class {kind}: {title}"
    opening = {'scheduled': 'You’re invited to your next Pro Trader Academy class.',
               'updated': 'Your class details have changed. Please use the updated information below.',
               'cancelled': 'This class has been cancelled. Please do not use the previous joining link.'}[kind]
    classroom = origin + '/#classroom'
    body = f'Hello {name},\n\n{opening}\n\nTopic: {title}\nDate, time and time zone: {when}\n'
    if not cancelled:
        body += f'Join class: {url}\n\nPlease join a few minutes early and bring your questions.\n'
    body += f'\nView your classroom: {classroom}\nNeed help? {origin}/#contact\n\nWarm regards,\nPro Trader Academy\n\nEducational only; not investment advice. Trading involves risk, and results are never guaranteed.'
    def paragraph(text):
        return f'<p style="margin:0 0 20px;line-height:1.65;overflow-wrap:anywhere">{escape(text)}</p>'
    details = f'<div style="margin:24px 0;padding:20px;background-color:#f1f5e9;border-left:4px solid #809b42"><h2 style="margin:0 0 12px;font-size:21px;color:#1b3020">{escape(title)}</h2><p style="margin:0;line-height:1.65"><strong>Date, time and time zone</strong><br>{escape(when)}</p></div>'
    button = '' if cancelled else f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:6px 0 24px"><tr><td style="background-color:#cbe88a;border-radius:6px"><a href="{escape(url, quote=True)}" style="display:inline-block;padding:16px 22px;color:#142019;font-weight:bold;text-decoration:none">Join class →</a></td></tr></table>'+paragraph('Please join a few minutes early and bring your questions.')+f'<p style="font-size:13px;line-height:1.6;overflow-wrap:anywhere">If the button does not open, copy this link into your browser:<br><a href="{escape(url, quote=True)}" style="color:#28552f">{escape(url)}</a></p>'
    content = paragraph('Hello '+name+',')+paragraph(opening)+details+button+f'<p style="line-height:1.7"><a href="{escape(classroom, quote=True)}" style="color:#28552f">View your classroom</a><br><a href="{escape(origin + "/#contact", quote=True)}" style="color:#28552f">Contact support</a></p>'+paragraph('Warm regards, Pro Trader Academy')
    headline = {'scheduled':'Your next class is confirmed.', 'updated':'Your class has an update.', 'cancelled':'A change to your class schedule.'}[kind]
    return subject, body, email_layout(subject, title+' · '+when, 'CLASS '+kind.upper(), headline, content, origin)
