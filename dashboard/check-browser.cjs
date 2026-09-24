const {chromium}=require('/home/timkay/work/fly-v-cloudflare/node_modules/playwright');
const fs=require('fs');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome'});
 const page=await browser.newPage({viewport:{width:1200,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('https://blink.timkay.com',{waitUntil:'networkidle'});
 await page.waitForSelector('#stations .station-row');
 console.log('Public rows:',await page.locator('#stations .station-row').count());
 async function checkColumns(){
   const columns=await page.locator('.station-row').evaluateAll(rows=>rows.map(r=>['.station-id','.status','.status-duration','.station-eta','.station-stats'].map(s=>{const n=r.querySelector(s);return n?Math.round(n.getBoundingClientRect().left):null;})));
   for(let i=0;i<5;i++)assert.ok(new Set(columns.map(c=>c[i]).filter(x=>x!==null)).size<=1,`Column ${i} must align across both lists`);
 }
 await checkColumns();
 const priority=await page.locator('#priority .station-row').evaluateAll(rows=>rows.map(r=>({id:r.dataset.station,status:r.querySelector('.status').textContent})));
 let previousRank=-1;
 for(const r of priority){
   assert.match(r.status,/^Connected/);
   assert.equal(await page.locator(`#stations [data-station="${r.id}"]`).count(),1);
 }
 console.log('Private history hidden:',await page.locator('#private').isHidden());
 assert.equal(await page.locator('#charging').count(),0);
 assert.equal(await page.getByText('Your charging',{exact:true}).count(),0);
 for(const button of await page.locator('.station-row .status-button').all())assert.ok(await button.isDisabled());
 for(const row of await page.locator('#stations .station-row').all()){
   if(await row.locator('.status.available').count()){
     const unproven=await row.evaluate(r=>r.classList.contains('unproven'));
     if(unproven)assert.equal(await row.locator('.status').evaluate(s=>getComputedStyle(s).color),'rgb(255, 207, 126)');
   }
 }
 await page.waitForResponse(r=>r.url().endsWith('/api/status')&&r.status()===200,{timeout:12000});
 console.log('Automatic polling verified');
 await page.setViewportSize({width:390,height:844});
 await checkColumns();
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile page should not overflow');
 await page.screenshot({path:'.build/dashboard-mobile.png',fullPage:true});
 await page.setViewportSize({width:1200,height:1000});
 await page.screenshot({path:'.build/dashboard-public.png',fullPage:true});
 const key=fs.readFileSync('.secrets/admin-key.txt','utf8').trim();
 await page.evaluate(k=>localStorage.setItem('blink-admin',k),key);
 await page.reload({waitUntil:'networkidle'});
 await page.waitForSelector('#private:visible');
 console.log('Authenticated sessions:',await page.locator('#sessions .session').count());
 const availableCount=await page.locator('#stations .status.available').count();
 assert.equal(await page.locator('#stations .unproven').count() + await page.locator('#stations .status.available').count() - await page.locator('#stations .unproven .status.available').count(),availableCount);
 const guard=await page.evaluate(async()=>{
   const r=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+localStorage.getItem('blink-admin')},body:JSON.stringify({station:'BAE000000',id:crypto.randomUUID()})});
   return {status:r.status,data:await r.json()};
 });
 assert.equal(guard.status,409);console.log('Nonexistent station start rejected:',guard.status);
 assert.equal(await page.locator('#stations .station-row').count(),19);
 assert.ok(await page.locator('#sessions .session').count()>=3);
 console.log('Browser errors:',errors);
 await page.screenshot({path:'.build/dashboard-private.png',fullPage:true});
 await browser.close();if(errors.length)process.exitCode=1;
})();
