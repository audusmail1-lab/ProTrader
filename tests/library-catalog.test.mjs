import test from 'node:test';
import assert from 'node:assert/strict';
import {matchingGuides,readLibraryLocation,guideCategories} from '../academy/video-library.js';
import {videos} from '../academy/public-content.js';
import {introVideo} from '../academy/intro-video.js';
import {journeyVideos} from '../academy/journey-videos.js';
const catalog=[...videos,introVideo,...journeyVideos];
test('classroom library exposes every existing public video exactly once',()=>{
 const all=matchingGuides(catalog,'all');
 assert.equal(all.length,10);
 assert.deepEqual(new Set(all.map(v=>v.id)),new Set(catalog.map(v=>v.id)));
 for(const group of guideCategories)assert.ok(group.ids.every(id=>catalog.some(v=>v.id===id)));
});
test('welcome and class attendance remain discoverable by title and category',()=>{
 const start=matchingGuides(catalog,'getting-started');
 assert.ok(start.some(v=>v.id===7)&&start.some(v=>v.id===8)&&start.some(v=>v.id===9));
 assert.equal(matchingGuides(catalog,'all','scheduled class')[0]?.id,9);
 assert.equal(matchingGuides(catalog,'all','Oracle percentage')[0]?.id,6);
});
test('saved search preserves filters and unknown categories fall back safely',()=>{
 assert.deepEqual(readLibraryLocation('#library?category=getting-started&q=Academy'),{category:'getting-started',search:'Academy'});
 assert.equal(readLibraryLocation('#library?category=unknown').category,'all');
 assert.equal(matchingGuides(catalog,'all','no-result-xyz').length,0);
});
