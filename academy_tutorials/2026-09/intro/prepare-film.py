"""Download authorised production inputs, align Callan and mix a licensed score.

Runs only in the Higgsfield media sandbox. No production account data is used.
"""
import difflib, hashlib, json, re, subprocess, textwrap, urllib.request, zipfile
from pathlib import Path
from faster_whisper import WhisperModel

ROOT=Path('/home/user/academy-film'); ROOT.mkdir(exist_ok=True)
def run(*a): return subprocess.check_output(list(a),text=True)
def get(url,path):
    urllib.request.urlretrieve(url,path)
def stamp(t):
    n=round(t*1000);return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02}.{n%1000:03}'
def tokens(s): return re.findall(r"[a-z0-9]+",s.lower())

dur=87
opening=json.loads((ROOT/'opening-checkpoint.json').read_text())
jobs=json.loads((ROOT/'voice-jobs.json').read_text())['jobs']
spec=[
 (1,0,18,opening['audio'],['What if your next step was clearer?','Welcome to Pro Trader Academy.','Learn the foundations.','Explore PROTrader, your chart-analysis workspace.','Then turn what you learn into guided practice.']),
 (3,18,12,jobs[0]['result_url'],['Start with ARIA.','It explains market conditions','and the checks behind a setup,','so you can understand the reasoning—','including when the conditions say wait.']),
 (4,30,15,jobs[1]['result_url'],['Oracle summarises those same checks.','In this example, eight out of nine agree:','about eighty-nine percent confluence.','That is a count of matching conditions,','not a win probability.']),
 (5,45,9,jobs[2]['result_url'],['Compare the output with the chart','and your own reasoning.','The tools support your review.','You stay in control.']),
 (6,54,13,jobs[3]['result_url'],['In the Academy, follow a guided lesson,','practise with a supplied example,','and save your notes.','Ask a question whenever you need help.','Your instructor replies in the same thread.']),
 (7,67,9,jobs[4]['result_url'],['New here? Choose Start Here.','Build your foundations first,','then open a short guide','when you need a specific tool.']),
 (8,76,11,jobs[5]['result_url'],['Pro Trader Academy.','Understand the tools.','Build your process.','Your first step starts here.'])
]
model=WhisperModel('base',device='cpu',compute_type='int8',cpu_threads=4)
timeline=[]; captions=[]; asr=[]
for ix,at,window,url,phrases in spec:
    wav=ROOT/f'voice-{ix}.wav';get(url,wav)
    length=float(run('ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(wav)))
    assert length+.4 < window, (ix,length,window)
    segs,info=model.transcribe(str(wav),language='en',word_timestamps=True,beam_size=5,initial_prompt='Pro Trader Academy. PROTrader. ARIA. Oracle. Confluence. Chart-analysis workspace.')
    words=[{'word':w.word.strip(),'start':w.start,'end':w.end} for s in segs for w in s.words]
    heard=[]; timed=[]
    for w in words:
        ts=tokens(w['word']);heard.extend(ts);timed.extend([w]*len(ts))
    expected=[t for p in phrases for t in tokens(p)]
    matcher=difflib.SequenceMatcher(None,expected,heard,autojunk=False)
    matched={i+k:j+k for i,j,n in matcher.get_matching_blocks() for k in range(n)}
    ratio=matcher.ratio()
    assert ratio>.84, (ix,'Review speech discrepancy',ratio,heard)
    def locate(n):
        if n in matched:return timed[matched[n]]['start']
        later=[k for k in matched if k>n]
        return timed[matched[min(later)]]['start'] if later else words[-1]['end']
    offset=0; starts=[]
    for phrase in phrases:
        starts.append(at+.4+locate(offset));offset+=len(tokens(phrase))
    for j,p in enumerate(phrases):
        start=starts[j];end=(starts[j+1]-.08 if j+1<len(starts) else at+.4+words[-1]['end']+.25)
        assert end>start,(ix,p,start,end)
        captions.append({'start':round(start,3),'end':round(end,3),'text':p})
    item={'index':ix,'at':at,'dur':window,'audioDuration':length,'audioLead':.4,'phrases':phrases,'starts':starts,'words':words,'alignmentRatio':round(ratio,4)}
    timeline.append(item);asr.append({'index':ix,'recognized':' '.join(w['word'] for w in words),'alignmentRatio':round(ratio,4)})
    print('SPEECH',ix,round(length,3),round(ratio,3),asr[-1]['recognized'],flush=True)

(ROOT/'timing.json').write_text(json.dumps({'duration':dur,'scenes':timeline,'captions':captions},indent=2))
(ROOT/'asr-review.json').write_text(json.dumps(asr,indent=2))
vtt=['WEBVTT','']
for c in captions:vtt.extend([f"{stamp(c['start'])} --> {stamp(c['end'])}",textwrap.fill(c['text'],width=43),''])
(ROOT/'intro.vtt').write_text('\n'.join(vtt))
# Normalize every take separately for consistent voice levels; preserve its speed.
inputs=[];filters=[]
for n,(ix,at,*_) in enumerate(spec):
    inputs+=['-i',str(ROOT/f'voice-{ix}.wav')]
    filters.append(f'[{n}:a]loudnorm=I=-18:TP=-2:LRA=7,aresample=48000,adelay={int((at+.4)*1000)}:all=1[a{n}]')
filters.append(''.join(f'[a{n}]' for n in range(len(spec)))+f'amix=inputs={len(spec)}:normalize=0,apad,atrim=duration={dur}[voice]')
subprocess.run(['ffmpeg','-v','error','-y',*inputs,'-filter_complex',';'.join(filters),'-map','[voice]','-ac','2',str(ROOT/'voice-track.wav')],check=True)
get('https://www.scottbuckley.com.au/library/wp-content/uploads/2019/09/sb_neon_nomelody.mp3',ROOT/'music.mp3')
# Leave the pulse audible in transitions; duck it automatically while Callan speaks.
mix=f'[0:a]asplit=2[voice][control];[1:a]atrim=start=32:duration={dur},asetpts=PTS-STARTPTS,volume=0.32,afade=t=in:d=1,afade=t=out:st={dur-2.5}:d=2.5[m];[m][control]sidechaincompress=threshold=0.018:ratio=5:attack=15:release=380:makeup=1[duck];[voice][duck]amix=inputs=2:normalize=0,loudnorm=I=-17:TP=-1.5:LRA=8,aresample=48000[out]'
subprocess.run(['ffmpeg','-v','error','-y','-i',str(ROOT/'voice-track.wav'),'-i',str(ROOT/'music.mp3'),'-filter_complex',mix,'-map','[out]','-ac','2','-t',str(dur),str(ROOT/'mix.wav')],check=True)
(ROOT/'MUSIC-CREDIT.txt').write_text("'Neon' (No Melody) by Scott Buckley - released under CC-BY 4.0. www.scottbuckley.com.au\nSource: https://www.scottbuckley.com.au/library/neon/\nLicense: https://creativecommons.org/licenses/by/4.0/\nChanges: excerpt from 00:32, fades, volume reduction and sidechain ducking beneath narration.\nCredit accompanies the website player and must appear in the description of any YouTube upload. Do not submit the soundtrack to Content ID or redistribute it alone.\n")
print('READY',dur,'seconds',len(captions),'caption cues',flush=True)
