/* ThinkSpace AI — auth (prototype: browser-only, replace with a real provider) */
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const store={get(k,d){try{const v=JSON.parse(localStorage.getItem(k));return v??d}catch{return d}},set(k,v){localStorage.setItem(k,JSON.stringify(v))}};
async function hash(p){
  if(window.crypto&&crypto.subtle){const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(p));return [...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('')}
  return btoa(unescape(encodeURIComponent(p)));
}
const Auth={
  session(){return sessionStorage.getItem('ts_session')||localStorage.getItem('ts_session')},
  user(){return store.get('ts_users',{})[this.session()]||null},
  start(email,remember){this.end();(remember?localStorage:sessionStorage).setItem('ts_session',email)},
  end(){sessionStorage.removeItem('ts_session');localStorage.removeItem('ts_session')}
};

const signin=$('#signin'),signup=$('#signup'),message=$('#message');
function showForm(w){signin.classList.toggle('hidden',w!=='signin');signup.classList.toggle('hidden',w!=='signup');message.textContent='';}
$('#toSignup').onclick=e=>{e.preventDefault();showForm('signup')};
$('#toSignin').onclick=e=>{e.preventDefault();showForm('signin')};
$$('.toggle').forEach(b=>b.onclick=()=>{const i=document.getElementById(b.dataset.target);i.type=i.type==='password'?'text':'password';b.textContent=i.type==='password'?'Show':'Hide'});
$('#forgot').onclick=e=>{e.preventDefault();message.textContent='Password reset will be available after a real authentication provider is connected.'};

signup.onsubmit=async e=>{
  e.preventDefault();
  const name=$('#fullName').value.trim(),email=$('#signupEmail').value.trim().toLowerCase(),p=$('#signupPassword').value,c=$('#confirmPassword').value,err=$('#signupErr');
  if(p!==c){err.textContent='Passwords do not match.';return}
  const users=store.get('ts_users',{});
  if(users[email]){err.textContent='An account with this email already exists.';return}
  users[email]={name,email,pass:await hash(p)};store.set('ts_users',users);
  err.textContent='';Auth.start(email,true);enterApp();
};
signin.onsubmit=async e=>{
  e.preventDefault();
  const email=$('#loginEmail').value.trim().toLowerCase(),p=$('#loginPassword').value,err=$('#loginPassErr');
  if(p.length<6){err.textContent='Password must contain at least 6 characters.';return}
  const u=store.get('ts_users',{})[email];
  if(!u||u.pass!==await hash(p)){err.textContent='Incorrect email or password.';return}
  err.textContent='';Auth.start(email,$('#remember').checked);enterApp();
};
