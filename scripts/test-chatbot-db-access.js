// node scripts/test-chatbot-db-access.js
const http = require('http');

function postJSON(path, payload){
  return new Promise((resolve, reject)=>{
    const data = Buffer.from(JSON.stringify(payload));
    const req = http.request({
      hostname:'localhost', port:5000, path, method:'POST',
      headers:{'Content-Type':'application/json','Content-Length':data.length}
    }, res=>{
      let body=''; res.on('data',d=>body+=d); res.on('end',()=>resolve({status:res.statusCode, body}));
    });
    req.on('error', reject); req.write(data); req.end();
  });
}

(async ()=>{
  try{
    let sid = null;

    function logAndSet(r){
      console.log(r.status, r.body);
      const parsed = JSON.parse(r.body);
      if (parsed.session_id) sid = parsed.session_id;
    }

    console.log('1) greet');
    let r = await postJSON('/api/chat',{message:'hi', session_id:sid}); logAndSet(r);

    console.log('\n2) categories');
    r = await postJSON('/api/chat',{message:'what types of properties do you have?', session_id:sid}); logAndSet(r);

    console.log('\n3) galle under 80M (plural apartments should parse)');
    r = await postJSON('/api/chat',{message:'show me apartments in galle under 80M', session_id:sid}); logAndSet(r);

    console.log('\n4) set budget then city/type (same session)');
    r = await postJSON('/api/chat',{message:'my budget is 50M', session_id:sid}); logAndSet(r);
    r = await postJSON('/api/chat',{message:'apartments in colombo 5', session_id:sid}); logAndSet(r);

    console.log('\n5) investments');
    r = await postJSON('/api/chat',{message:'most budget friendly investment plan', session_id:sid}); logAndSet(r);

  }catch(e){ console.error(e); process.exit(1); }
})();
