import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';

const root=new URL('../academy/',import.meta.url);
const revision='20261007-safari1';
const pages=['academy-landing.html','live.html'];
const read=name=>readFileSync(new URL(name,root),'utf8');
const local=url=>!url.startsWith('http:')&&!url.startsWith('https:')&&!url.startsWith('//');

test('public and classroom script/style entrypoints bypass the previously cached release',()=>{
 for(const page of pages){
  const tags=read(page).match(/<(?:script|link)\b[^>]*>/g)||[];
  let count=0;
  for(const tag of tags){
   const url=tag.match(/(?:src|href)=["']([^"']+)["']/)?.[1];
   if(!url||!local(url)||!url.split('?')[0].match(/\.(?:js|css)$/))continue;
   assert.equal(new URL(url,'https://academy.invalid/').searchParams.get('v'),revision,`${page}: ${url}`);count++;
  }
  assert.ok(count>5,`${page} must contain the expected browser assets`);
 }
});

test('the reachable authored module graph also uses new URLs, while API and pinned vendor paths stay stable',()=>{
 const visited=new Set(),pending=[];
 for(const page of pages)for(const match of read(page).matchAll(/<script\b[^>]*src=["']([^"']+)["']/g)){
  if(local(match[1]))pending.push(new URL(match[1].replace(/^\//,''),root));
 }
 while(pending.length){
  const url=pending.pop(),key=url.pathname;if(visited.has(key))continue;visited.add(key);
  const source=readFileSync(url,'utf8');
  if(key.includes('/vendor/'))continue;
  for(const match of source.matchAll(/\b(?:from|import)\s*(?:\(\s*)?["'](\.{1,2}\/[^"'\n]+\.js(?:\?[^"'\n]*)?)["']/g)){
   const dependency=new URL(match[1],url);
   if(dependency.pathname.includes('/vendor/'))assert.equal(dependency.search,'');
   else assert.equal(dependency.searchParams.get('v'),revision,`${url.pathname}: ${match[1]}`);
   pending.push(dependency);
  }
 }
 assert.ok(visited.size>=25,'Both homepage and classroom module chains must be checked');
 assert.match(read('live.js'),/import\('\/api\/materials\.js'\)/);
 assert.match(read('cinematic/alex-support.js'),/WIDGET_URL='\/cinematic\/elevenlabs-widget-0\.18\.3\.js'/);
 assert.match(read('cinematic/alex-support.js'),/styles\.href='\/cinematic\/alex-support\.css\?v=20261007-safari1'/);
});

test('changed compressed modules deliver the same versioned source as their plain counterparts',()=>{
 for(const name of ['alex-support','experience','product-refinement','scene','terminal-preview']){
  const source=readFileSync(new URL(`cinematic/${name}.js`,root));
  const compressed=readFileSync(new URL(`cinematic/${name}.js.gz`,root));
  assert.deepEqual(gunzipSync(compressed),source,name);
 }
});
