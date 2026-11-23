// اطلاعات قابل تنظیم سایت در فایل config.js قرار دارد.
const cfg = window.SITE_CONFIG || {};
const nav = document.getElementById('nav');
document.getElementById('navToggle').addEventListener('click',()=>nav.classList.toggle('open'));
nav.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>nav.classList.remove('open')));

function applyConfig(){
  document.querySelectorAll('[data-key]').forEach(el=>{
    const key=el.dataset.key;
    if(cfg[key]) el.textContent=cfg[key];
  });
  if(cfg.phone){
    document.querySelectorAll('[data-phone-link]').forEach(a=>a.href='tel:'+cfg.phone.replace(/[^\d+]/g,''));
    document.querySelectorAll('[data-whatsapp]').forEach(a=>a.href='https://wa.me/'+cfg.phone.replace(/\D/g,''));
  }
  if(cfg.projects && cfg.projects.length){
    const grid=document.getElementById('projectGrid');
    grid.innerHTML=cfg.projects.map((p,i)=>`<article class="work-card reveal ${i===0?'work-feature':''}"><div class="work-photo" style="background-image:linear-gradient(#10151022,#10151022),url('${p.image}');background-size:cover;background-position:center"><span>${p.category||'پروژه'}</span></div><div class="work-info"><div><small>${p.category||'پروژه'}</small><h3>${p.title||'نمونه پروژه'}</h3></div><b>${String(i+1).padStart(2,'0')}</b></div></article>`).join('');
  }
}
applyConfig();

const observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('visible');observer.unobserve(e.target)}}),{threshold:.12});
document.querySelectorAll('.reveal').forEach(el=>observer.observe(el));
window.addEventListener('scroll',()=>{const max=document.documentElement.scrollHeight-innerHeight;document.getElementById('progress').style.width=(max?scrollY/max*100:0)+'%'});
document.getElementById('year').textContent=new Date().getFullYear();

document.getElementById('contactForm').addEventListener('submit',e=>{
  e.preventDefault();
  const d=new FormData(e.currentTarget);
  const phone=(cfg.phone||'93700000000').replace(/\D/g,'');
  const msg=`سلام، برای پروژه درخواست مشاوره دارم.\nنام: ${d.get('name')}\nشماره تماس: ${d.get('phone')}\nنوع پروژه: ${d.get('service')}\nتوضیحات: ${d.get('message')}`;
  if(phone && phone!=='93700000000'){window.open('https://wa.me/'+phone+'?text='+encodeURIComponent(msg),'_blank')}
  else document.getElementById('formHelp').textContent='ابتدا شماره واتساپ واقعی را در فایل config.js وارد کنید تا پیام به مقصد درست ارسال شود.';
});
