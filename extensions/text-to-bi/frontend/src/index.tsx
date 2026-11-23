import React from 'react';
import ReactDOM from 'react-dom';

import { App } from './app';
import { allowedSections, hasAnySection, sectionFromSearch, sectionGroups } from './features/workspace/workspace-layout';
import { type Access, fetchAccess } from './lib/access';
import { CHANGE_EVENT, PAGE_PATH, navigate, pageHref } from './lib/navigation';
// React Flow's stylesheet (the model and lineage canvases), loaded once here instead of in each canvas file as the
// standalone app does: style-loader makes it global either way. Every rule targets .react-flow* classes, so nothing
// reaches Superset's own pages; it comes before globals.css so the extension's canvas rules follow it.
import '@xyflow/react/dist/style.css';
import './styles/globals.css';

const navSelector = 'ul[data-test="navbar-top"]';
const navItemSelector = '[data-test="text-to-bi-nav-item"]';
const chevron = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';

function isPage() { return `${window.location.pathname.replace(/\/$/, '')}/` === PAGE_PATH; }

function themeMode(): 'light' | 'dark' {
  const color = getComputedStyle(document.body).backgroundColor;
  const values = color.match(/\d+(?:\.\d+)?/g)?.map(Number) || [];
  const luminance = values.length >= 3 ? values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722 : 255;
  return luminance < 128 ? 'dark' : 'light';
}

function currentSection(access: Access) {
  return isPage() ? sectionFromSearch(new URLSearchParams(window.location.search), access) : null;
}

function escapeHtml(text: string) {
  return text.replace(/[&<>"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[char] as string);
}

/**
 * One navbar menu per section group the user can open something in; hovering or clicking it lists the group's
 * sections the user may open (a user who may only ask questions gets the AI Agent menu with the chat alone).
 */
function createNavMenus(access: Access) {
  const sections = allowedSections(access);
  let dropdown: HTMLDivElement | null = null;
  let closeTimer = 0;

  const close = () => { window.clearTimeout(closeTimer); dropdown?.classList.remove('is-open'); };
  const scheduleClose = () => { window.clearTimeout(closeTimer); closeTimer = window.setTimeout(close, 150); };

  const open = (anchor: Element, groupId: string) => {
    window.clearTimeout(closeTimer);
    if (!dropdown) {
      dropdown = document.createElement('div');
      dropdown.className = 'tb-nav-dropdown';
      dropdown.setAttribute('role', 'menu');
      dropdown.addEventListener('mouseenter', () => window.clearTimeout(closeTimer));
      dropdown.addEventListener('mouseleave', scheduleClose);
      dropdown.addEventListener('click', event => {
        const link = (event.target as Element).closest<HTMLAnchorElement>('a[data-section]');
        if (!link) return;
        close();
        if (!isPage()) return;
        // Already on the page: switch sections in place so unsaved edits can be confirmed first.
        event.preventDefault();
        navigate(link.getAttribute('href') as string);
      });
      document.body.append(dropdown);
    }
    dropdown.innerHTML = sections.filter(section => section.group === groupId).map(section => (
      `<a role="menuitem" data-section="${section.segment}" href="${pageHref({ section: section.segment })}">`
      + `<strong>${escapeHtml(section.label)}</strong><span>${escapeHtml(section.description)}</span></a>`
    )).join('');
    const active = currentSection(access)?.segment;
    dropdown.querySelectorAll<HTMLAnchorElement>('a[data-section]').forEach(link => {
      link.classList.toggle('is-active', link.dataset.section === active);
    });
    const rect = anchor.getBoundingClientRect();
    dropdown.style.top = `${rect.bottom}px`;
    dropdown.style.left = `${rect.left}px`;
    dropdown.dataset.group = groupId;
    dropdown.setAttribute('data-theme-mode', themeMode());
    dropdown.classList.add('is-open');
  };

  const sync = (navbar: HTMLElement) => {
    const activeGroup = currentSection(access)?.group;
    sectionGroups.filter(group => sections.some(section => section.group === group.id)).forEach(group => {
      let item = navbar.querySelector(`${navItemSelector}[data-group="${group.id}"]`);
      if (!item) {
        const first = sections.find(section => section.group === group.id);
        const trigger = document.createElement('li');
        trigger.className = 'ant-menu-item ant-menu-item-only-child';
        trigger.setAttribute('role', 'menuitem');
        trigger.setAttribute('aria-haspopup', 'menu');
        trigger.setAttribute('data-test', 'text-to-bi-nav-item');
        trigger.setAttribute('data-group', group.id);
        trigger.innerHTML = `<span class="ant-menu-title-content"><a class="tb-nav-trigger" `
          + `href="${pageHref({ section: first?.segment })}">${escapeHtml(group.label)}${chevron}</a></span>`;
        trigger.addEventListener('mouseenter', () => open(trigger, group.id));
        trigger.addEventListener('mouseleave', scheduleClose);
        trigger.addEventListener('focusin', () => open(trigger, group.id));
        trigger.addEventListener('click', event => {
          event.preventDefault();
          if (dropdown?.classList.contains('is-open') && dropdown.dataset.group === group.id) close();
          else open(trigger, group.id);
        });
        navbar.append(trigger);
        item = trigger;
      }
      item.classList.toggle('ant-menu-item-selected', activeGroup === group.id);
    });
  };

  const remove = () => {
    close();
    dropdown?.remove();
    document.querySelectorAll(navItemSelector).forEach(item => item.remove());
  };

  return { sync, remove };
}

function installTextToBI() {
  let host: HTMLDivElement | null = null;
  let access: Access | null = null;
  let menus: ReturnType<typeof createNavMenus> | null = null;
  const alignHost = () => {
    if (!host) return;
    const header = document.querySelector<HTMLElement>('header#main-menu');
    const nav = header?.querySelector<HTMLElement>('.main-nav');
    if (!header || !nav) return;
    host.style.marginTop = `${Math.max(0, Math.ceil(nav.getBoundingClientRect().bottom
      - header.getBoundingClientRect().bottom))}px`;
    // Everything above the page, so full-height layouts subtract the navbar Superset actually drew.
    host.style.setProperty('--tb-navbar', `${Math.ceil(host.getBoundingClientRect().top + window.scrollY)}px`);
  };
  const onResize = () => window.requestAnimationFrame(alignHost);
  const resizeObserver = new ResizeObserver(alignHost);
  const sync = () => {
    if (!access || !menus) return;
    const navbar = document.querySelector<HTMLElement>(navSelector);
    if (navbar) menus.sync(navbar);
    if (!isPage()) {
      if (host) { ReactDOM.unmountComponentAtNode(host); host.remove(); host = null; }
      return;
    }
    if (host) { host.setAttribute('data-theme-mode', themeMode()); alignHost(); return; }
    const header = document.querySelector<HTMLElement>('header#main-menu');
    if (!header) return;
    resizeObserver.observe(header);
    const nav = header.querySelector<HTMLElement>('.main-nav');
    if (nav) resizeObserver.observe(nav);
    host = document.createElement('div');
    host.setAttribute('data-theme-mode', themeMode());
    header.after(host);
    alignHost();
    ReactDOM.render(<App access={access} />, host);
  };
  const observer = new MutationObserver(sync);
  fetchAccess().then(current => {
    access = current;
    if (!hasAnySection(current)) return;
    menus = createNavMenus(current);
    observer.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('popstate', sync);
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener('resize', onResize);
    sync();
  }).catch(() => undefined);
  return () => { observer.disconnect(); resizeObserver.disconnect(); window.removeEventListener('popstate', sync);
    window.removeEventListener(CHANGE_EVENT, sync); window.removeEventListener('resize', onResize); menus?.remove();
    if (host) ReactDOM.unmountComponentAtNode(host); host?.remove(); };
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installTextToBI, { once: true });
else installTextToBI();
