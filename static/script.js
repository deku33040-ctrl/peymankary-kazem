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


// Kazemi sliders: controls affect only portfolio and article carousels.
document.querySelectorAll('[data-slider-prev], [data-slider-next]').forEach(button => {
  const id = button.dataset.sliderPrev || button.dataset.sliderNext;
  const slider = document.getElementById(id);
  if (!slider) { button.hidden = true; return; }
  const cards = () => Array.from(slider.children).filter(el => el.classList.contains('work-card') || el.classList.contains('blog-card'));
  if (cards().length < 2) {
    const controls = button.closest('.kazemi-slider-controls');
    if (controls) controls.hidden = true;
    return;
  }
  button.addEventListener('click', () => {
    const items = cards();
    const current = slider.getBoundingClientRect();
    let nearest = 0, best = Infinity;
    items.forEach((item, index) => {
      const r = item.getBoundingClientRect();
      const distance = Math.abs((r.left + r.right) / 2 - (current.left + current.right) / 2);
      if (distance < best) { best = distance; nearest = index; }
    });
    const nextIndex = button.hasAttribute('data-slider-next')
      ? Math.min(items.length - 1, nearest + 1)
      : Math.max(0, nearest - 1);
    items[nextIndex].scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest', inline: 'center'});
  });
});


// Rebuild the floating WhatsApp / Telegram / phone controls in one isolated dock.
(() => {
  const mountContactDock = () => {
    // Remove any old implementation so controls can never be duplicated.
    document.querySelectorAll('.floating-contact, #floatingContact, #kazemi-contact-dock')
      .forEach(node => node.remove());

    const dock = document.createElement('div');
    dock.id = 'kazemi-contact-dock';
    dock.setAttribute('aria-label', 'راه‌های ارتباط با سنگ لاشه کاظمی');

    const phone = '+989965470626';
    const items = [
      {
        className: 'kc-whatsapp',
        label: 'واتساپ',
        href: 'https://wa.me/989965470626',
        svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 3.5A11.8 11.8 0 0 0 2 17.7L.5 23.5l6-1.5A11.8 11.8 0 0 0 20.5 3.5ZM12 21a9.1 9.1 0 0 1-4.6-1.2l-.3-.2-3.5.9.9-3.4-.2-.4A9.2 9.2 0 1 1 12 21Zm5-6.9c-.3-.2-1.7-.9-2-.9s-.5-.2-.7.2-.8.9-1 .0.4-.3.6-.5.3-.3.4-.5.1-.4 0-.6c-.1-.2-.7-1.7-1-2.3-.3-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4s-1 1-1 2.4 1 2.7 1.2 2.9c.1.2 2 3.1 4.9 4.2.7.3 1.2.4 1.6.5.7.2 1.3.1 1.8.1.6-.1 1.7-.7 1.9-1.3.2-.6.2-1.1.1-1.2-.1-.1-.3-.2-.6-.4Z"/></svg>'
      },
      {
        className: 'kc-telegram',
        label: 'تلگرام',
        href: 'https://t.me/+989965470626',
        svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.8 3.2 18.5 20c-.2 1.2-.9 1.5-1.9.9l-5.2-3.8-2.5 2.4c-.3.3-.5.5-1 .5l.4-5.3 9.7-8.8c.4-.4-.1-.6-.6-.2L5.4 13.3.3 11.7c-1.1-.3-1.1-1.1.2-1.6L20.4 2.5c.9-.3 1.7.2 1.4.7Z"/></svg>'
      },
      {
        className: 'kc-phone',
        label: 'تماس تلفنی',
        href: 'tel:' + phone,
        svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 10.8a15.5 15.5 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.2 11.2 11.2 0 0 0 3.5.6 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17.9 17.9 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1 11.2 11.2 0 0 0 .6 3.5 1 1 0 0 1-.2 1Z"/></svg>'
      }
    ];

    items.forEach(item => {
      const link = document.createElement('a');
      link.className = 'kc-contact-link ' + item.className;
      link.href = item.href;
      link.setAttribute('aria-label', item.label);
      if (item.className !== 'kc-phone') {
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
      }
      link.innerHTML = item.svg + '<span class="kc-contact-label">' + item.label + '</span>';
      dock.appendChild(link);
    });

    if (dock.childElementCount) document.body.appendChild(dock);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountContactDock, { once: true });
  } else {
    mountContactDock();
  }
})();
