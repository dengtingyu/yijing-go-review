// Check that the 3D view receives only the displayed position's own analysis.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const render=source.slice(source.indexOf('function renderTerrain(){'),source.indexOf("$('view2d').onclick"));
const calls=[];
const context=vm.createContext({terrainView:{update:d=>calls.push(d)},boardView:'3d',turn:1,pv:null,
  active:()=>context.current, current:{size:19,positions:[[0],[1]],analysis:{1:{ownership:[.7],rootInfo:{visits:500}}}}});
vm.runInContext(render,context);const draw=()=>vm.runInContext('renderTerrain()',context);
draw();assert.equal(calls.at(-1).stones,context.current.positions[1]);assert.equal(calls.at(-1).ownership,context.current.analysis[1].ownership);
context.turn=0;draw();assert.equal(calls.at(-1).ownership,undefined);
context.pv={positions:[[2],[3]],step:1};draw();assert.equal(calls.at(-1).stones,context.pv.positions[1]);assert.equal(calls.at(-1).ownership,undefined);assert.match(calls.at(-1).message,/尚未分析/);
context.pv=null;context.current={size:9,positions:[[2]],analysis:{0:{ownership:[-.4],rootInfo:{visits:700}}}};draw();assert.equal(calls.at(-1).size,9);assert.equal(calls.at(-1).visits,700);
const count=calls.length;context.boardView='2d';draw();assert.equal(calls.length,count);
console.log('PASS: 3D navigation, missing analysis, PV isolation, branch data and 2D switching');
