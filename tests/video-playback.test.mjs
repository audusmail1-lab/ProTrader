import test from 'node:test';
import assert from 'node:assert/strict';
import {selectVideoMedia,videoQualityHTML,bindVideoPlayback,releaseVideo} from '../academy/video-player.js';

const film={id:0,url:'https://media.example/720.mp4',poster:'/poster.jpg',width:1280,height:720,sources:[{url:'https://media.example/1080.mp4',width:1920,height:1080,label:'1080p'}]};
class Control extends EventTarget{hidden=true;textContent='';dataset={};value='';}
class Video extends Control{
  readyState=1;duration=60;currentTime=0;paused=true;ended=false;seeking=false;currentSrc=film.url;src=film.url;preload='metadata';loads=0;plays=0;focused=false;removed=[];
  sources=[{removeAttribute:attribute=>this.removed.push(`source:${attribute}`),addEventListener(){},removeEventListener(){}}];
  track=new Control();
  querySelectorAll(selector){return selector==='source'?this.sources:[]}
  querySelector(selector){return selector==='track'?this.track:null}
  getAttribute(name){return name==='src'?this.src:null}
  removeAttribute(name){this.removed.push(name);if(name==='src')this.src=''}
  focus(){this.focused=true}
  pause(){this.paused=true;this.dispatchEvent(new Event('pause'))}
  play(){this.plays++;this.paused=false;this.dispatchEvent(new Event('play'));return Promise.resolve()}
  load(){this.loads++;this.pause();this.readyState=0;this.currentTime=0}
  metadata(){this.readyState=1;this.currentSrc=this.src;this.dispatchEvent(new Event('loadedmetadata'))}
}
function setup(t,options={}){
 const video=new Video(),status=new Control(),error=new Control(),retry=new Control(),chapter=new Control(),quality=new Control();
 chapter.dataset.seek='24';
 const controller=bindVideoPlayback({video,status,error,retry,chapters:[chapter],quality,media:selectVideoMedia(film),...options});
 t.after(()=>controller.dispose());return {video,status,error,retry,chapter,quality,controller};
}

test('new landscape lessons default to 720p on desktop and mobile without inheriting old portrait IDs',()=>{
 for(const mobile of [false,true]){const media=selectVideoMedia(film,{mobile});assert.equal(media.url,film.url);assert.equal(media.portrait,false);assert.equal(media.sources.length,2)}
 assert.match(videoQualityHTML(selectVideoMedia(film)),/1080p/);
 assert.equal(videoQualityHTML(selectVideoMedia({...film,sources:[]})),'');
});

test('existing portrait and landscape format selections remain supported',()=>{
 const old={id:7,formats:{portrait:{url:'/portrait.mp4',poster:'/portrait.jpg'},landscape:{url:'/landscape.mp4',poster:'/landscape.jpg'}}};
 assert.equal(selectVideoMedia(old,{mobile:true}).url,'/portrait.mp4');
 assert.equal(selectVideoMedia(old,{mobile:false}).portrait,false);
 assert.equal(selectVideoMedia({id:2,url:'/existing.mp4'}).portrait,true);
});

test('chapter selection seeks and starts playback immediately when metadata is ready',t=>{
 const {video,chapter}=setup(t);assert.equal(video.plays,0);
 chapter.dispatchEvent(new Event('click'));
 assert.equal(video.currentTime,24);assert.equal(video.plays,1);assert.equal(video.focused,false);assert.equal(video.preload,'auto');
});

test('both chapter controls reveal the video inside its dialog without stealing focus or scrolling the page',t=>{
 for(const attribute of ['seek','videoTime']){
  const {video,chapter}=setup(t),scrolls=[];
  chapter.dataset={[attribute]:'24'};
  const document={activeElement:chapter,defaultView:{matchMedia:()=>({matches:false})}};
  video.ownerDocument=document;
  video.getBoundingClientRect=()=>({top:-800,bottom:-500});
  video.scrollIntoView=()=>assert.fail('the background page must not be scrolled');
  video.closest=()=>({scrollTop:1000,clientTop:1,clientHeight:700,getBoundingClientRect:()=>({top:50}),querySelector:()=>({getBoundingClientRect:()=>({height:60})}),scrollTo:options=>scrolls.push(options)});
  chapter.dispatchEvent(new Event('click'));
  assert.deepEqual(scrolls,[{top:77,behavior:'smooth'}]);
  assert.equal(video.currentTime,24);assert.equal(video.focused,false);assert.equal(document.activeElement,chapter);
 }
});

test('reduced-motion chapter activation reveals immediately, including before metadata is available',t=>{
 const {video,chapter}=setup(t),scrolls=[];video.readyState=0;
 video.ownerDocument={defaultView:{matchMedia:query=>{assert.equal(query,'(prefers-reduced-motion: reduce)');return {matches:true}}}};
 video.getBoundingClientRect=()=>({top:-800,bottom:-500});
 video.closest=()=>({scrollTop:1000,clientTop:1,clientHeight:700,getBoundingClientRect:()=>({top:50}),querySelector:()=>null,scrollTo:options=>scrolls.push(options)});
 chapter.dispatchEvent(new Event('click'));
 assert.deepEqual(scrolls,[{top:137,behavior:'auto'}]);assert.equal(video.currentTime,0);
 video.metadata();assert.equal(video.currentTime,24);assert.equal(scrolls.length,1);
});

test('visible films and playback lifecycle events do not cause unnecessary scrolling',t=>{
 const {video,chapter,retry,quality}=setup(t),scrolls=[];
 video.getBoundingClientRect=()=>({top:150,bottom:450});
 video.closest=()=>({scrollTop:0,clientTop:1,clientHeight:700,getBoundingClientRect:()=>({top:50}),querySelector:()=>({getBoundingClientRect:()=>({height:60})}),scrollTo:options=>scrolls.push(options)});
 chapter.dispatchEvent(new Event('click'));assert.deepEqual(scrolls,[]);
 video.getBoundingClientRect=()=>({top:-800,bottom:-500});
 retry.dispatchEvent(new Event('click'));video.metadata();
 quality.value='1';quality.dispatchEvent(new Event('change'));video.metadata();
 video.dispatchEvent(new Event('playing'));assert.deepEqual(scrolls,[]);
});

test('chapter selection before metadata queues the requested time instead of dropping the click',t=>{
 const {video,chapter}=setup(t);video.readyState=0;
 chapter.dispatchEvent(new Event('click'));assert.equal(video.currentTime,0);
 video.metadata();assert.equal(video.currentTime,24);assert.equal(video.paused,false);
});

test('buffering offers recovery after a bounded wait and hides it on resumed playback',async t=>{
 const {video,status,error}=setup(t,{stallMs:5});
 video.dispatchEvent(new Event('waiting'));
 await new Promise(resolve=>setTimeout(resolve,12));
 assert.equal(error.hidden,false);assert.match(status.textContent,/Retry from this point/);
 video.dispatchEvent(new Event('playing'));
 assert.equal(error.hidden,true);assert.match(status.textContent,/captions/);
});

test('retry and quality changes preserve position and intended play or pause state',t=>{
 const {video,retry,quality}=setup(t);video.currentTime=17;
 retry.dispatchEvent(new Event('click'));video.metadata();
 assert.equal(video.currentTime,17);assert.equal(video.paused,false);
 video.currentTime=31;video.pause();quality.value='1';quality.dispatchEvent(new Event('change'));video.metadata();
 assert.equal(video.src,'https://media.example/1080.mp4');assert.equal(video.currentTime,31);assert.equal(video.paused,true);
});

test('disposing aborts the previous media and removes old playback handlers',t=>{
 const {video,status,controller}=setup(t);controller.dispose();const message=status.textContent;
 assert.deepEqual(video.removed,['src','source:src']);assert.equal(video.loads,1);
 video.dispatchEvent(new Event('playing'));assert.equal(status.textContent,message);
 controller.dispose();assert.equal(video.loads,1);
});

test('standalone release cancels loading from both direct and nested sources',()=>{
 const video=new Video();releaseVideo(video);assert.equal(video.paused,true);assert.equal(video.loads,1);assert.equal(video.src,'');assert.ok(video.removed.includes('source:src'));
});
