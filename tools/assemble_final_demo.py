"""Assemble actual browser capture with Russian narration; no generated UI frames."""
import json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'output/winning/video'
chapters=json.loads((folder/'narration.json').read_text())
segments=json.loads((folder/'segments.json').read_text())
font=ROOT/'backend/designer/assets/fonts/Play-Regular.ttf'
clips=[];timeline=[];offset=0
for segment in segments:
    i=segment['chapter'];chapter=chapters[i]
    source=folder/'recording.webm';start=segment['start']
    original=segment['end']-segment['start']
    if segment.get('pieces'):
        parts=segment['pieces'];source=folder/f'trimmed-{i:02}.mkv'
        filters=';'.join(f'[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{j}]' for j,(a,b) in enumerate(parts))
        filters+=';'+''.join(f'[v{j}]' for j in range(len(parts)))+f'concat=n={len(parts)}:v=1:a=0[out]'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(folder/'recording.webm'),'-filter_complex',filters,'-map','[out]','-an','-c:v','libx264','-preset','fast','-crf','18',str(source)],check=True)
        start=0;original=sum(b-a for a,b in parts)
    duration=max(original,chapter['seconds']+1)
    # Short action sequences are slowed down for readability, never accelerated.
    factor=duration/original
    label=folder/f'{i:02}-title.txt';label.write_text(chapter['title'])
    subtitle=folder/'disclosure.txt';subtitle.write_text('Локальная версия · синтетические данные · синтетическая озвучка · паузы ожидания сокращены')
    vf=f"setpts={factor}*PTS,fps=30,pad=1440:1010:0:0:color=0x101827,drawtext=fontfile='{font}':textfile='{label}':fontcolor=white:fontsize=28:x=36:y=922,drawtext=fontfile='{font}':textfile='{subtitle}':fontcolor=0xA7BCD5:fontsize=18:x=36:y=969"
    target=folder/f'clip-{i:02}.mp4';clips.append(target)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(start),'-t',str(original),'-i',str(source),'-i',str(folder/f'{i:02}.aiff'),'-vf',vf,'-af','apad','-t',str(duration),'-c:v','libx264','-preset','fast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',str(target)],check=True)
    timeline.append({'start':round(offset,3),'duration':round(duration,3),'title':chapter['title']});offset+=duration
    print(f'Chapter {i+1}: {duration:.1f}s',flush=True)
(folder/'concat.txt').write_text('\n'.join(f"file '{p}'" for p in clips))
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(folder/'concat.txt'),'-c','copy','-movflags','+faststart',str(ROOT/'output/winning/Демонстрация-Слайд.mp4')],check=True)
(folder/'timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
print(f'Total: {offset:.1f}s',flush=True)
