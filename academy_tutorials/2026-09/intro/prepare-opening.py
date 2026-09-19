"""Align the short Callan audition without speeding up or cropping the voice."""
import json,math,re,subprocess
from pathlib import Path
from faster_whisper import WhisperModel
ROOT=Path('/home/user/academy-callan')
duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(ROOT/'voice.wav')]))
model=WhisperModel('base',device='cpu',compute_type='int8',cpu_threads=4)
segments,info=model.transcribe(str(ROOT/'voice.wav'),language='en',word_timestamps=True,beam_size=5,initial_prompt='Pro Trader Academy. PROTrader. Chart-analysis workspace. Guided practice.')
words=[{'word':w.word.strip(),'start':round(w.start+.4,3),'end':round(w.end+.4,3)} for s in segments for w in s.words]
def cue(token):
    matches=[w['start'] for w in words if re.sub(r'[^a-z]','',w['word'].lower())==token]
    if not matches: raise ValueError('Missing speech cue: '+token)
    return matches[0]
timing={'duration':max(19,math.ceil(duration+.4+1.5)),'welcome':cue('welcome'),'learn':cue('learn'),'explore':cue('explore'),'then':cue('then'),'voiceDuration':duration,'words':words}
assert all(b-a>=1.5 for a,b in zip([0,timing['welcome'],timing['learn'],timing['then']],[timing['welcome'],timing['learn'],timing['then'],timing['duration']]))
(ROOT/'timing.json').write_text(json.dumps(timing,indent=2))
print('TIMING',json.dumps({k:v for k,v in timing.items() if k!='words'}),flush=True)
print('HEARD',' '.join(w['word'] for w in words),flush=True)
def stamp(t):
    n=round(t*1000);return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02}.{n%1000:03}'
captions=['WEBVTT','']
phrases=[
    (.4,cue('welcome')-.25,'What if your next step was clearer?'),
    (cue('welcome'),cue('learn')-.25,'Welcome to Pro Trader Academy.'),
    (cue('learn'),cue('explore')-.25,'Learn the foundations.'),
    (cue('explore'),cue('then')-.25,'Explore PROTrader,\nyour chart-analysis workspace.'),
    (cue('then'),words[-1]['end']+.3,'Then turn what you learn\ninto guided practice.')
]
for start,end,text in phrases:
    captions.extend([f'{stamp(start)} --> {stamp(end)}',text,''])
(ROOT/'opening.vtt').write_text('\n'.join(captions))
(ROOT/'MUSIC-CREDIT.txt').write_text("'Origami' by Scott Buckley - released under CC-BY 4.0. www.scottbuckley.com.au\nSource: https://www.scottbuckley.com.au/library/origami/\nLicense: https://creativecommons.org/licenses/by/4.0/\nChanges: excerpt, fades, volume reduction and mixing under narration.\nCredit must accompany the film on the website and appear in the description of any YouTube upload.\n")
