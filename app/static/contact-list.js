(() => {
  function initials(name) {
    return (name || '?').trim().split(/\s+/).map(part => part[0] || '').slice(0, 2).join('').toUpperCase();
  }

  function createIdentity(contact, {showStatus = true, showEmail = true, subtitle = ''} = {}) {
    const identity = document.createElement('span');
    identity.className = 'site-contact-identity';

    const avatar = document.createElement('span');
    avatar.className = 'site-contact-avatar';
    avatar.setAttribute('aria-hidden', 'true');
    const picture = contact.picture || '';
    if (picture) {
      try {
        const url = new URL(picture, window.location.origin);
        if (url.protocol === 'https:') {
          const image = document.createElement('img');
          image.src = url.href;
          image.alt = '';
          image.referrerPolicy = 'no-referrer';
          image.addEventListener('error', () => {
            avatar.textContent = initials(contact.name);
          }, {once: true});
          avatar.append(image);
        }
      } catch (_) { /* Use initials when a profile image URL is invalid. */ }
    }
    if (!avatar.children.length) avatar.textContent = initials(contact.name);

    const details = document.createElement('span');
    details.className = 'site-contact-details';
    const name = document.createElement('strong');
    name.className = 'site-contact-name';
    name.textContent = contact.name || contact.title || '';
    details.append(name);
    if (showEmail && contact.email) {
      const email = document.createElement('small');
      email.className = 'site-contact-email';
      email.textContent = contact.email;
      details.append(email);
    }
    if (contact.tel) {
      const phone = document.createElement('small');
      phone.className = 'site-contact-phone';
      phone.textContent = contact.tel;
      details.append(phone);
    }
    if (showStatus) {
      const registered = contact.registered === true || (!('registered' in contact) && Boolean(contact.user_id));
      const status = document.createElement('small');
      status.className = 'site-contact-status';
      status.dataset.registered = String(registered);
      status.textContent = window.FlutuI18n?.[registered ? 'Registered on Flutu.eu' : 'Not registered on Flutu.eu']
        || (registered ? 'Registered on Flutu.eu' : 'Not registered on Flutu.eu');
      details.append(status);
    }
    if (subtitle) {
      const extra = document.createElement('small');
      extra.className = 'site-contact-subtitle';
      extra.textContent = subtitle;
      details.append(extra);
    }

    identity.append(avatar, details);
    return identity;
  }

  function createEntry(contact, {tagName = 'div', className = '', control = null, actions = null, subtitle = '', showStatus = true} = {}) {
    const entry = document.createElement(tagName);
    entry.className = `site-contact-entry${className ? ` ${className}` : ''}`;
    if (control) entry.append(control);
    entry.append(createIdentity(contact, {showStatus, subtitle}));
    if (actions) entry.append(actions);
    return entry;
  }

  function sortByName(contacts) {
    const locale = document.documentElement.lang || undefined;
    return [...contacts].sort((first, second) => {
      const firstName = first.name || first.requester_name || first.recipient_name || '';
      const secondName = second.name || second.requester_name || second.recipient_name || '';
      return String(firstName).localeCompare(String(secondName), locale, {sensitivity: 'base'});
    });
  }

  window.FlutuContactList = {createEntry, createIdentity, sortByName};
})();