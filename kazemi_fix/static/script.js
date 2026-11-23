document.documentElement.classList.add('js-enabled');
const nav = document.getElementById('nav');
const navToggle = document.getElementById('navToggle');
if(nav && navToggle){navToggle.addEventListener('click',()=>nav.classList.toggle('open'));nav.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>nav.classList.remove('open')));}

function observeReveals(root=document){
  const observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('visible');observer.unobserve(e.target)}}),{threshold:.12});
  root.querySelectorAll('.reveal:not(.visible)').forEach(el=>observer.observe(el));
}
function setText(key,value){if(value===undefined||value===null)return;document.querySelectorAll(`[data-key="${key}"]`).forEach(el=>el.textContent=value)}
function applyProjects(projects){
  const grid=document.getElementById('projectGrid');
  if(!grid)return;
  if(!projects || !projects.length){grid.innerHTML='<p class="empty-projects">هنوز نمونه‌کاری ثبت نشده است.</p>';return;}
  grid.innerHTML='';
  projects.forEach((p,i)=>{
    const card=document.createElement('a'); card.href='/project/'+p.id; card.className='work-card reveal'+(i===0?' work-feature':'');
    const photo=document.createElement('div'); photo.className='work-photo';
    if(p.image){photo.style.backgroundImage=`linear-gradient(#10151022,#10151022),url("${p.image}")`;photo.style.backgroundSize='cover';photo.style.backgroundPosition='center'}
    const tag=document.createElement('span');tag.textContent=p.category||'پروژه';photo.appendChild(tag); if(p.is_favorite){const fav=document.createElement('b');fav.className='favorite-tag';fav.textContent='★ محبوب';photo.appendChild(fav)}
    photo.setAttribute('role','img'); photo.setAttribute('aria-label',(p.title||'نمونه‌کار')+' - '+(p.category||'')); const info=document.createElement('div');info.className='work-info';
    const inner=document.createElement('div');const small=document.createElement('small');small.textContent=p.category||'پروژه';const h=document.createElement('h3');h.textContent=p.title||'نمونه پروژه';inner.append(small,h);
    const num=document.createElement('b');num.textContent=String(i+1).padStart(2,'0');info.append(inner,num);card.append(photo,info);grid.appendChild(card);
  });
  observeReveals(grid);
}
async function loadSite(){
  try{
    const response=await fetch('/api/public'); if(!response.ok)throw new Error('api');
    const data=await response.json(); const s=data.settings||{};
    ['company','slogan','heroText','aboutText','quote','experience','projectsCount','phone','address'].forEach(k=>setText(k,s[k]));
    if(s.phone){const digits=s.phone.replace(/\D/g,'');document.querySelectorAll('[data-phone-link]').forEach(a=>a.href='tel:'+digits);document.querySelectorAll('[data-whatsapp]').forEach(a=>a.href='https://wa.me/'+digits)}
    applyProjects(data.projects);
    setupProjectSearch();
  }catch(e){console.warn('بارگذاری اطلاعات سایت انجام نشد:',e)}
}
loadSite();
observeReveals();
const progress=document.getElementById('progress');if(progress)window.addEventListener('scroll',()=>{const max=document.documentElement.scrollHeight-innerHeight;progress.style.width=(max?scrollY/max*100:0)+'%'});
const year=document.getElementById('year');if(year)year.textContent=new Date().getFullYear();

const contactForm=document.getElementById('contactForm');if(contactForm)contactForm.addEventListener('submit',async e=>{
  e.preventDefault(); const form=e.currentTarget; const d=Object.fromEntries(new FormData(form).entries());
  const help=document.getElementById('formHelp'); help.textContent='در حال ثبت درخواست...';
  try{
    const r=await fetch('/api/contact',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
    const result=await r.json(); if(!r.ok)throw new Error(result.error||'خطا در ثبت درخواست');
    help.textContent=result.message;form.reset();
  }catch(err){help.textContent=err.message+'؛ لطفاً دوباره تلاش کنید.'}
});

function setupProjectSearch(){
 const input=document.getElementById('publicProjectSearch'); if(!input)return;
 input.addEventListener('input',()=>{const q=input.value.trim().toLocaleLowerCase();document.querySelectorAll('#projectGrid .work-card').forEach(card=>{card.hidden=!card.textContent.toLocaleLowerCase().includes(q)})});
}
