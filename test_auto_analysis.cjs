const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const names = ['play', 'playMove', 'active', 'currentPlayer', 'cancel', 'setButtons', 'analyze', 'poll', 'scheduleAuto', 'goto', 'returnOriginal', 'exitTrial', 'toggleTrial'];
const functions = source.split('\n').filter(line => names.some(name => line.startsWith(`function ${name}(`) || line.startsWith(`async function ${name}(`))).join('\n');
const requests = [], pending = new Map(), elements = new Map();
let seq = 0, replayGate=null;
const context = vm.createContext({
  console, Object, Number, Promise, clearTimeout, setTimeout,
  $: id => { if (!elements.has(id)) elements.set(id, {value:'400',checked:true}); return elements.get(id); },
  render(){}, toast(){}, scheduleSave(){}, async save(){},
  async api(path, data) {
    requests.push({path, data});
    if (path === 'replay') {if(replayGate)await replayGate;return JSON.parse(JSON.stringify(data));}
    if (path === 'analyze') return {id: String(++seq)};
    if (path === 'cancel') return {ok:true};
    if (path.startsWith('job/')) return new Promise(resolve => pending.set(path, resolve));
    throw Error(path);
  }
});
vm.runInContext(`let game={moves:[],initialPlayer:'B',analysis:{0:{rootInfo:{winrate:.4}}}}, branch=null, turn=0, editing=false, branchMode=true, pv=null, job=null, busy=false, pollTimer, playQueue=Promise.resolve(),autoTimer,autoGeneration=0,trialOrigin=null,branchSession=0;\n${functions}`, context);
const run = s => vm.runInContext(s, context);
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  // Terminal engine errors are job results, not transient HTTP failures to retry forever.
  const apiSource=source.split('\n').find(line=>line.startsWith('async function api('));
  const errorContext=vm.createContext({fetch:async()=>({ok:true,json:async()=>({done:true,error:'engine stopped'})})});
  vm.runInContext(apiSource,errorContext);
  const failure=await vm.runInContext("api('job/failed')",errorContext);
  assert.equal(failure.error,'engine stopped');
  await assert.rejects(vm.runInContext("api('import',{})",errorContext),/engine stopped/);
  // Rapid clicks must stay in order, cancel previous searches, and keep accepting moves.
  await Promise.all([run("play('Q16')"), run("play('D16')")]);
  assert.equal(run('branch.moves.length'), 2);
  assert.equal(run('branch.moves[0][0]'), 'B');
  assert.equal(run('branch.moves[1][0]'), 'W');
  assert.equal(requests.filter(r => r.path === 'analyze').length, 2);
  assert.equal(requests.find(r => r.path === 'cancel').data.id, '1');
  assert.equal(run('job.id'), '2');
  assert.equal(elements.get('branch').disabled, false);
  // A cancelled query returning late must not finish or overwrite the new query.
  pending.get('job/1')({results:{1:{old:true}}, done:true, completed:1});
  await flush();
  assert.equal(run('job.id'), '2');
  assert.equal(run('busy'), true);
  pending.get('job/2')({results:{2:{rootInfo:{winrate:.6}}}, done:true, completed:1, stopReason:'评价已稳定，自动暂停'});
  await flush();
  assert.equal(run('busy'), false);
  assert.match(elements.get('task').textContent,/稳定/);
  assert.equal(elements.get('autoAnalysis').checked,true);
  assert.equal(run('branch.analysis[2].rootInfo.winrate'), .6);
  assert.equal(run('branch.analysis[0].rootInfo.winrate'), .4);
  // Passing also auto-analyzes; replacing a continuation drops stale future results.
  run('turn=1');
  await run("play('pass')");
  assert.equal(run('branch.moves[1][1]'), 'pass');
  assert.equal(run('branch.analysis[2]'), undefined);
  assert.equal(run('job.auto'), true);
  await run('cancel()');
  assert.equal(run('job'), null);
  assert.equal(run('busy'), false);
  assert.equal(requests.filter(r=>r.path==='analyze').every(r=>r.data.continuous===true),true);
  // Moving the record slider automatically starts a continuous query for the latest turn.
  run('branchMode=false; turn=0');
  run('goto(1)');
  await new Promise(resolve=>setTimeout(resolve,250));
  await run('playQueue');
  assert.equal(run('job.turn'),1);
  assert.equal(run('job.auto'),true);
  await run('cancel()');
  // Browsing during a whole-game query must keep that batch running.
  run("job={id:'whole',all:true}; busy=true");
  const before=requests.length;
  run('goto(0)');
  await new Promise(resolve=>setTimeout(resolve,250));
  assert.equal(requests.length,before);
  await run('cancel()');
  // Whole-game review fills missing positions, then keeps thinking on the selected one.
  run('branch=null; game={moves:[["B","Q16"]],initialPlayer:"B",analysis:{0:{rootInfo:{visits:403}}}}; turn=0');
  await run('analyze(true)');
  const batch=requests.filter(r=>r.path==='analyze').at(-1);
  assert.deepEqual(Array.from(batch.data.turns),[1]);
  assert.equal(batch.data.continuous,false);
  const batchId=run('job.id');
  pending.get('job/'+batchId)({results:{1:{rootInfo:{visits:403}}},done:true,completed:1,total:1});
  await flush();
  await new Promise(resolve=>setTimeout(resolve,250));
  await run('playQueue');
  assert.equal(run('job.auto'),true);
  assert.equal(run('job.turn'),0);
  await run('cancel()');
  // Exiting returns to the entry position, even after branching and browsing backwards.
  elements.get('autoAnalysis').checked=false;
  run('game={moves:Array.from({length:100},(_,i)=>[i%2?"W":"B","pass"]),initialPlayer:"B",analysis:{}}; branch=null; branchMode=false;turn=30');
  const original=run('JSON.stringify(game.moves)');
  await run('toggleTrial()');
  await run("play('Q16')");
  await run("play('D16')");
  assert.equal(run('turn'),32);
  run('goto(5)');
  await run('exitTrial(false)');
  assert.equal(run('turn'),30);
  assert.equal(run('branch'),null);
  assert.equal(run('branchMode'),false);
  assert.equal(run('JSON.stringify(game.moves)'),original);
  // The mode button itself also ends the trial, and each new trial gets a new origin.
  run('turn=3');
  await run('toggleTrial()');
  await run("play('pass')");
  await run('toggleTrial()');
  assert.equal(run('turn'),3);
  run('turn=12');
  await run('toggleTrial()');
  run('goto(45)');
  await run('exitTrial(false)');
  assert.equal(run('turn'),12);
  // Outstanding/queued clicks must not recreate a trial after it has been closed.
  run('turn=8');
  await run('toggleTrial()');
  let release;
  replayGate=new Promise(resolve=>release=resolve);
  const first=run("play('Q16')"),second=run("play('D16')");
  await flush();
  await run('exitTrial(false)');
  release();replayGate=null;
  await Promise.all([first,second]);
  assert.equal(run('turn'),8);
  assert.equal(run('branch'),null);
  assert.equal(run('JSON.stringify(game.moves)'),original);
  // With auto analysis on, returning restarts analysis on the saved original position.
  elements.get('autoAnalysis').checked=true;
  run('turn=20');
  await run('toggleTrial()');
  await run("play('Q16')");
  await run('exitTrial()');
  await new Promise(resolve=>setTimeout(resolve,250));
  await run('playQueue');
  assert.equal(run('job.turn'),20);
  assert.equal(run('job.g===game'),true);
  assert.equal(run('branch'),null);
  await run('cancel()');
  console.log('PASS: trial origin restoration, toggle exit, repeated trials, late clicks, restored analysis and existing auto analysis');
})().catch(e => {console.error(e);process.exitCode=1});
