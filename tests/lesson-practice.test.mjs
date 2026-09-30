import test from 'node:test';
import assert from 'node:assert/strict';
import {lessonPractice,lessonPracticeHTML,bindLessonPractice} from '../academy/video-player.js';

test('every refreshed lesson has one optional question and useful feedback for every choice',()=>{
 assert.deepEqual(Object.keys(lessonPractice).map(Number),[0,1,2,3,4,5,6,7,8,9]);
 for(const [id,practice] of Object.entries(lessonPractice)){
  assert.ok(practice.question.endsWith('?'));
  assert.ok(practice.answers.length>=2&&practice.answers.length<=3);
  assert.equal(new Set(practice.answers.map(answer=>answer.feedback)).size,practice.answers.length);
  assert.ok(practice.answers.every(answer=>answer.feedback.length>70));
  const html=lessonPracticeHTML(id);
  assert.match(html,/Try what you learned/);assert.match(html,/aria-live="polite"/);
  assert.doesNotMatch(html,/<details[^>]*\sopen|data-score|data-grade|autoplay/);
 }
});

test('fixed-size stop practice preserves target profit and makes the exact changed loss explicit',()=>{
 const practice=lessonPractice[0];
 assert.match(practice.question,/size fixed at 0\.10 lots/);
 assert.match(practice.answers[0].text,/stays the same/);
 assert.match(practice.answers[0].feedback,/target profit stays \$40 before costs/);
 assert.match(practice.answers[0].feedback,/loss from \$20 to \$10/);
 assert.match(practice.answers[1].feedback,/size and target fixed/);
 assert.match(practice.answers[2].feedback,/remains 0\.10 lots/);
});

test('Oracle and Sentinel feedback cannot turn agreement or monitoring into a forecast',()=>{
 const oracle=lessonPractice[6];
 assert.match(oracle.answers[0].text,/same ten checks used by ARIA/);
 assert.match(oracle.answers[0].feedback,/80% agreement/);
 assert.match(oracle.answers[0].feedback,/not an independent confirmation or a win probability/);
 assert.match(oracle.answers[1].feedback,/does not measure the probability/);
 const sentinel=lessonPractice[7];
 assert.match(sentinel.answers[0].text,/configured markets and timeframes using closed candles/);
 assert.match(sentinel.answers[0].feedback,/does not guarantee/);
 assert.match(sentinel.answers[2].feedback,/does not place your broker orders/);
});

test('navigation, review and class questions preserve the scripts’ practical distinctions',()=>{
 assert.match(lessonPractice[3].answers[0].feedback,/Profit alone cannot explain decision quality/);
 assert.match(lessonPractice[4].answers[0].feedback,/phone, use the visible tabs/);
 assert.match(lessonPractice[5].answers[0].feedback,/ticket unchanged/);
 assert.match(lessonPractice[9].answers[0].feedback,/latest update with My classroom/);
 assert.match(lessonPractice[9].answers[0].feedback,/time zone/);
});

test('app access practice distinguishes shared Academy credentials from separate sessions and broker access',()=>{
 const practice=lessonPractice[8];
 assert.match(practice.question,/account.*sign in to PROTrader/);
 assert.match(practice.answers[0].text,/Academy account.*same email and password/);
 assert.match(practice.answers[0].feedback,/app creates its own session/);
 assert.match(practice.answers[0].feedback,/does not open a broker account or connect MetaTrader/);
 assert.match(practice.answers[1].feedback,/PROTrader uses your Academy account/);
 assert.match(practice.answers[2].feedback,/separate sessions/);
 assert.match(practice.answers[2].feedback,/does not require a second account/);
 assert.doesNotMatch(practice.answers.map(answer=>answer.feedback).join(' '),/relevant account|accounts are separate|different password/);
});

test('visitors can explore answers without pausing video, advancing questions or writing account data',t=>{
 class Button extends EventTarget{
  constructor(index){super();this.dataset={practiceAnswer:String(index)};this.attributes={}}
  setAttribute(key,value){this.attributes[key]=value}
 }
 const buttons=lessonPractice[6].answers.map((_,index)=>new Button(index)),feedback={textContent:''};
 const root={querySelectorAll:()=>buttons,querySelector:selector=>{assert.equal(selector,'.practice-feedback');return feedback}};
 t.mock.method(globalThis,'fetch',()=>{throw new Error('Practice must not write account data')});
 bindLessonPractice(root,6);
 buttons[1].dispatchEvent(new Event('click'));
 assert.equal(feedback.textContent,lessonPractice[6].answers[1].feedback);
 assert.equal(buttons[1].attributes['aria-pressed'],'true');
 buttons[0].dispatchEvent(new Event('click'));
 assert.equal(feedback.textContent,lessonPractice[6].answers[0].feedback);
 assert.equal(buttons[1].attributes['aria-pressed'],'false');
 assert.equal(buttons[0].attributes['aria-pressed'],'true');
});
