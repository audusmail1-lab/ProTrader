import test from 'node:test';
import assert from 'node:assert/strict';
import {alexErrorMessage,refineAlexAgentStagePrefixes} from '../academy/cinematic/alex-support.js';
import {readFileSync} from 'node:fs';

test('voice setup failures offer text fallback without exposing infrastructure',()=>{
 for(const raw of ['Not allowed by CSP','Failed to load rawAudioProcessor worklet module','Internal server error request_abc123']){
  const copy=alexErrorMessage(raw,'voice');
  assert.match(copy,/Text Alex/);
  assert.doesNotMatch(copy,/CSP|rawAudio|request_abc|server error|ElevenLabs/);
 }
});
test('microphone refusal gives a relevant recovery action',()=>{
 assert.match(alexErrorMessage('NotAllowedError: Permission denied','voice'),/Allow it in your browser/);
 assert.match(alexErrorMessage('Requested device not found','voice'),/Microphone access is unavailable/);
});
test('network failure keeps the conversation available and offers retry',()=>{
 assert.match(alexErrorMessage('Failed to fetch'),/connection.*try again.*conversation is still here/);
});
test('unknown text failures offer Academy support and never echo raw errors',()=>{
 const copy=alexErrorMessage('<script>private diagnostic</script>');
 assert.match(copy,/Academy team/);
 assert.doesNotMatch(copy,/private diagnostic|script/);
});

const text=data=>({nodeType:3,data});
const element=(tagName,...childNodes)=>({nodeType:1,tagName,childNodes,get firstElementChild(){return childNodes.find(node=>node.nodeType===1)}});
const content=node=>node.nodeType===3?node.data:node.childNodes.map(content).join('');
const agentRoot=(...messages)=>({querySelectorAll(selector){assert.equal(selector,'.pr-8 > .markdown');return messages}});

test('known agent delivery prefixes are removed without replacing inline markup or later paragraphs',()=>{
 const greeting=text('[warmly] Hello '),emphasis=element('STRONG',text('there')),later=element('P',text('[calmly] is quoted later in this response.'));
 const message=element('DIV',element('P',greeting,emphasis,text(' — read [ARIA] first.')),later);
 assert.equal(refineAlexAgentStagePrefixes(agentRoot(message)),1);
 assert.equal(content(message),'Hello there — read [ARIA] first.[calmly] is quoted later in this response.');
 assert.equal(message.firstElementChild.childNodes[1],emphasis);
 assert.equal(refineAlexAgentStagePrefixes(agentRoot(message)),0);
});

test('the agent-only selector leaves visitor bubbles, technical brackets, code and links intact',()=>{
 const visitor=element('DIV',text('[warmly] Please explain [RSI].'));
 const protectedContent=[
  element('DIV',element('P',text('[RSI 14] is a setting.'))),
  element('DIV',element('P',text('[bullish] is my tag.'))),
  element('DIV',element('P',text('The label [warmly] is an audio direction.'))),
  element('DIV',element('P',element('CODE',text('[warmly]')),text(' is a literal value.'))),
  element('DIV',element('P',element('A',text('[calmly]')),text(' is the link label.'))),
  element('DIV',element('PRE',text('[warmly] code sample'))),
  element('DIV',element('BLOCKQUOTE',element('P',text('[warmly] quoted example'))))
 ];
 const before=protectedContent.map(content);
 assert.equal(refineAlexAgentStagePrefixes(agentRoot(...protectedContent)),0);
 assert.deepEqual(protectedContent.map(content),before);
 assert.equal(content(visitor),'[warmly] Please explain [RSI].');
});

test('split and consecutive allowed cues are handled without deleting the reply or arbitrary tags',()=>{
 const message=element('DIV',element('P',text(' [warm'),element('EM',text('ly]')),text(' [CALMLY]  Read [EMA 20] with the chart.')));
 assert.equal(refineAlexAgentStagePrefixes(agentRoot(message)),3);
 assert.equal(content(message),'Read [EMA 20] with the chart.');
 const arbitrary=element('DIV',element('P',text('[warmly] [custom instruction] Keep this text.')));
 refineAlexAgentStagePrefixes(agentRoot(arbitrary));
 assert.equal(content(arbitrary),'[custom instruction] Keep this text.');
});

test('streaming updates clean complete prefixes and then stop mutating unchanged replies',()=>{
 const node=text('[warm'),root=agentRoot(element('DIV',element('P',node)));
 assert.equal(refineAlexAgentStagePrefixes(root),0);
 node.data='[warmly]';assert.equal(refineAlexAgentStagePrefixes(root),1);assert.equal(node.data,'');
 node.data='[warmly] Welcome';assert.equal(refineAlexAgentStagePrefixes(root),1);assert.equal(node.data,'Welcome');
 assert.equal(refineAlexAgentStagePrefixes(root),0);
 node.data='[warmly] Welcome to the Academy.';refineAlexAgentStagePrefixes(root);
 assert.equal(node.data,'Welcome to the Academy.');assert.equal(refineAlexAgentStagePrefixes(root),0);
});

test('the pinned widget keeps the reviewed agent renderer separate from visitor bubbles',()=>{
 const widget=readFileSync(new URL('../academy/cinematic/elevenlabs-widget-0.18.3.js',import.meta.url),'utf8');
 const renderer=widget.slice(widget.indexOf('function N2('),widget.indexOf('function P2('));
 assert.match(renderer,/className:`pr-8`/);
 assert.match(widget,/e\.role===`agent`\?z\(N2,\{entry:e\}\):z\(F2,\{entry:e\}\)/);
 // Native stripping deliberately excludes text-chat entries in this release.
 assert.match(renderer,/r=!e\.isText,i=n\.value\.strip_audio_tags&&r/);
});
