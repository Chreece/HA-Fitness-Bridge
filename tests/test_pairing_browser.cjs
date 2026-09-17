/* Run the production OAuth client with a deterministic browser/network harness. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const code = fs.readFileSync(require('node:path').join(__dirname,'../custom_components/fitness_bridge/pairing.js'),'utf8');

async function browser({callback=false,badState=false,authFailure=false,pairFailure=false}={}) {
  const calls=[], sent=[], storage=new Map(), nodes={status:{textContent:''},connect:{hidden:true}};
  const location={origin:'https://ha.example',pathname:callback?'/api/fitness_bridge/oauth-callback':'/api/fitness_bridge/setup',
    search:callback?'?code=ha-only-code&state='+(badState?'wrong':'nonce'):'',
    hash:callback?'':'#ticket=fitness-pairing-ticket&fitness_url=https%3A%2F%2Ffitness.example',assign:url=>calls.push(['navigate',url])};
  const pending={fitness:'https://fitness.example',ticket:'fitness-pairing-ticket',state:'nonce',created:Date.now()};
  if(callback)storage.set('fitness_bridge_oauth_pending',JSON.stringify(pending));
  class WebSocket {
    constructor(url){calls.push(['websocket',url]);queueMicrotask(()=>this.onmessage({data:JSON.stringify({type:'auth_required'})}));}
    send(raw){const msg=JSON.parse(raw);sent.push(msg);queueMicrotask(()=>this.onmessage({data:JSON.stringify(msg.type==='auth'?{type:authFailure?'auth_invalid':'auth_ok'}:{id:1,success:!pairFailure,error:{message:'admin required'}})}));}
    close(){calls.push(['close']);}
  }
  const context=vm.createContext({console,URL,URLSearchParams,Uint8Array,Date,JSON,Array,Error,Promise,setTimeout,clearTimeout,
    crypto:webcrypto,location,history:{replaceState:(...args)=>calls.push(['history',args[2]])},
    document:{getElementById:id=>nodes[id]},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    window:{opener:{postMessage:(msg,origin)=>calls.push(['message',msg,origin])}},WebSocket,
    fetch:async(url,options)=>{calls.push(['fetch',url,Object.fromEntries(options.body)]);return {ok:true,json:async()=>({access_token:'ha-access-secret',refresh_token:'ha-refresh-secret'})};},
  });
  await vm.runInContext(code,context);
  return {calls,sent,storage,nodes,context};
}

(async()=>{
  const setup=await browser();assert.equal(setup.nodes.connect.hidden,false);setup.nodes.connect.onclick();
  const pending=JSON.parse(setup.storage.get('fitness_bridge_oauth_pending'));
  assert.equal(pending.state.length,64);
  const authorize=new URL(setup.calls.find(x=>x[0]==='navigate')[1]);
  assert.equal(authorize.origin,'https://ha.example');assert.equal(authorize.pathname,'/auth/authorize');
  assert.equal(authorize.searchParams.get('state'),pending.state);
  assert.equal(authorize.searchParams.get('redirect_uri'),'https://ha.example/api/fitness_bridge/oauth-callback');
  const success=await browser({callback:true});
  assert.equal(success.storage.size,0);
  const fetches=success.calls.filter(x=>x[0]==='fetch');
  assert.equal(fetches[0][1],'/auth/token');assert.equal(fetches[0][2].code,'ha-only-code');
  assert.equal(fetches[1][1],'/auth/revoke');assert.equal(fetches[1][2].token,'ha-refresh-secret');
  const pair=success.sent.find(x=>x.type==='fitness_bridge/pair');
  assert.deepEqual(Object.keys(pair).sort(),['fitness_url','id','ticket','type']);
  assert.ok(!JSON.stringify(pair).includes('ha-access-secret'));
  assert.equal(success.calls.find(x=>x[0]==='message')[2],'https://fitness.example');
  assert.equal(success.calls.find(x=>x[0]==='history')[1],'/api/fitness_bridge/oauth-callback');
  const bad=await browser({callback:true,badState:true});assert.equal(bad.calls.filter(x=>x[0]==='fetch').length,0);assert.equal(bad.storage.size,0);
  const denied=await browser({callback:true,authFailure:true});assert.equal(denied.sent.length,1);assert.ok(denied.calls.some(x=>x[1]==='/auth/revoke'));
  const noadmin=await browser({callback:true,pairFailure:true});assert.ok(noadmin.nodes.status.textContent.includes('admin required'));assert.ok(!noadmin.calls.some(x=>x[0]==='message'));
  console.log('PASS OAuth origin, state, one-use context, token isolation, revocation, denied HA authentication and admin pairing');
})().catch(error=>{console.error(error);process.exitCode=1;});
