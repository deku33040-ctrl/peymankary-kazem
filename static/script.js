document.documentElement.classList.add('js-enabled');
const nav = document.getElementById('nav'), navToggle = document.getElementById('navToggle');
if (nav && navToggle) {
  navToggle.addEventListener('click', () => nav.classList.toggle('open'));
  nav.querySelectorAll('a').forEach(a => a.addEventListener('click', () => nav.classList.remove('open')));
}

const observer = new IntersectionObserver(entries => entries.forEach(e => {
  if (e.isIntersecting) { e.target.classList.add('visible'); observer.unobserve(e.target); }
}), { threshold: .12 });
document.querySelectorAll('.reveal').forEach(el => observer.observe(el));

const progress = document.getElementById('progress');
if (progress) addEventListener('scroll', () => {
  const max = document.documentElement.scrollHeight - innerHeight;
  progress.style.width = (max ? scrollY / max * 100 : 0) + '%';
});

const contactForm = document.getElementById('contactForm');
if (contactForm) contactForm.addEventListener('submit', async e => {
  e.preventDefault();
  const form = e.currentTarget, help = document.getElementById('formHelp'), btn = form.querySelector('button');
  help.textContent = 'در حال ثبت درخواست...'; btn.disabled = true;
  try {
    const r = await fetch('/api/contact', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(new FormData(form))) });
    const result = await r.json();
    if (!r.ok) throw new Error(result.error || 'خطا در ثبت درخواست');
    help.textContent = result.message; form.reset();
  } catch (err) { help.textContent = err.message + '؛ لطفاً دوباره تلاش کنید.'; }
  btn.disabled = false;
});

const about = document.getElementById('about');
if (about && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
  about.addEventListener('pointermove', e => {
    const r = about.getBoundingClientRect();
    about.style.setProperty('--parallax-x', (((e.clientX - r.left) / r.width - .5) * 8).toFixed(2) + 'px');
    about.style.setProperty('--parallax-y', (((e.clientY - r.top) / r.height - .5) * 6).toFixed(2) + 'px');
  });
  about.addEventListener('pointerleave', () => { about.style.setProperty('--parallax-x', '0px'); about.style.setProperty('--parallax-y', '0px'); });
}
