"""Assemble narration, captions and diagnostic evidence for rendered tutorials.

Run in the Higgsfield sandbox after render.jsx. Upload descriptors are supplied
separately at runtime and deliberately never included in the production archive.
"""
import json
import math
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path('/home/user/academy-phase1')


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def stamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'


def finish():
    videos = json.loads((ROOT/'timed-manifest.json').read_text())
    reports = []
    (ROOT/'captions').mkdir(exist_ok=True)
    for v in videos:
        vid = v['id']
        chunks = []
        captions = ['WEBVTT', '']
        for i, s in enumerate(v['shots']):
            output = ROOT/f'audio/chunk-{vid}-{i}.wav'
            length = s['audio_to']-s['audio_from']
            assert 0 < length < s['dur']
            af = (f"atrim=start={s['audio_from']}:end={s['audio_to']},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.02,afade=t=out:st={max(0,length-.04)}:d=0.04,"
                  f"adelay={round(s['audio_lead']*1000)}:all=1,apad,atrim=duration={s['dur']}")
            run(['ffmpeg','-v','error','-y','-i',str(ROOT/f'audio/{vid}.wav'),
                 '-af',af,'-ar','48000','-ac','1',str(output)])
            chunks.append(f"file '{output}'")
            words = s['narration'].split()
            group_size = math.ceil(len(words) / math.ceil(len(words) / 7))
            groups = [words[j:j+group_size] for j in range(0,len(words),group_size)]
            count = 0
            for group in groups:
                start = s['at']+s['audio_lead']+length*count/len(words)
                count += len(group)
                end = s['at']+s['audio_lead']+length*count/len(words)
                captions.extend([f'{stamp(start)} --> {stamp(end)} line:92% position:50% size:90%', ' '.join(group), ''])
        concat = ROOT/f'audio/concat-{vid}.txt'
        concat.write_text('\n'.join(chunks))
        audio = ROOT/f'audio/assembled-{vid}.wav'
        run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(audio)])
        output = ROOT/f'tutorial-{vid}.mp4'
        run(['ffmpeg','-v','error','-y','-i',str(ROOT/f'silent-{vid}.mp4'),'-i',str(audio),
             '-map','0:v:0','-map','1:a:0','-c:v','copy','-af','loudnorm=I=-16:TP=-2:LRA=11',
             '-c:a','aac','-b:a','160k','-ar','48000','-ac','2','-t',str(v['duration']),
             '-movflags','+faststart',str(output)])
        (ROOT/f'captions/tutorial-{vid}.vtt').write_text('\n'.join(captions))
        probe=json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]).stdout)
        run(['ffmpeg','-v','error','-xerror','-i',str(output),'-f','null','-'])
        loud=run(['ffmpeg','-hide_banner','-i',str(output),'-af','loudnorm=I=-16:TP=-2:LRA=11:print_format=json','-f','null','-']).stderr
        metrics=json.loads(loud[loud.rfind('{'):])
        video=next(s for s in probe['streams'] if s['codec_type']=='video')
        sound=next(s for s in probe['streams'] if s['codec_type']=='audio')
        assert (video['width'],video['height'])==(1080,1920)
        assert abs(float(probe['format']['duration'])-v['duration'])<.1
        assert sound['sample_rate']=='48000'
        assert -18<float(metrics['input_i'])<-14
        reports.append({'id':vid,'duration':v['duration'],'bytes':output.stat().st_size,
                        'dimensions':[video['width'],video['height']], 'fps':video['r_frame_rate'],
                        'audio_sample_rate':sound['sample_rate'],'all_frames_decoded':True,
                        'loudness':metrics,'speech_boundaries':v['boundary_checks'],
                        'minimum_scene_hold':min(s['dur'] for s in v['shots'])})
        print('QUALITY_PASS',vid,v['duration'],output.stat().st_size,flush=True)
    (ROOT/'quality-report.json').write_text(json.dumps(reports,indent=2))
    with zipfile.ZipFile(ROOT/'production-review.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in ['timed-manifest.json','quality-report.json','render.jsx','prepare.py','finish.py']:
            z.write(ROOT/name,name)
        for folder in ['frames','captions']:
            for p in sorted((ROOT/folder).glob('*')):z.write(p,p.relative_to(ROOT))
    return videos


if __name__=='__main__':
    finish()
