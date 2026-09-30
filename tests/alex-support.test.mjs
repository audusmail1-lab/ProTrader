import test from 'node:test';
import assert from 'node:assert/strict';
import {alexErrorMessage} from '../academy/cinematic/alex-support.js';

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
