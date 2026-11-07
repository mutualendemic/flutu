(() => {
  function initials(name) {
    return (name || '?').trim().split(/\s+/).map(part => part[0] || '').slice(0, 2).join('').toUpperCase();
  }

  function safeText(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function actionIcon(pathData) {
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.classList.add('contact-action-icon');
    icon.setAttribute('viewBox', '0 0 24 24');
    icon.setAttribute('aria-hidden', 'true');
    icon.style.display = 'block';
    icon.style.width = '18px';
    icon.style.height = '18px';
    icon.style.flex = '0 0 auto';
    icon.style.stroke = 'currentColor';
    icon.style.fill = 'none';
    icon.style.strokeLinecap = 'round';
    icon.style.strokeLinejoin = 'round';
    icon.style.strokeWidth = '1.8';
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', pathData);
    path.style.stroke = 'currentColor';
    path.style.fill = 'none';
    path.style.strokeLinecap = 'round';
    path.style.strokeLinejoin = 'round';
    icon.append(path);
    return icon;
  }

  function createMessageAction(contact, {label = window.FlutuI18n?.['Send message'] || 'Send message', contextType = '', contextId = '', delivery = 'push'} = {}) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'site-contact-message';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.style.display = 'inline-flex';
    button.style.alignItems = 'center';
    button.style.justifyContent = 'center';
    button.style.width = '40px';
    button.style.height = '40px';
    button.style.padding = '0';
    button.style.border = '1px solid #d5deef';
    button.style.borderRadius = '9px';
    button.style.background = 'white';
    button.style.color = '#3655d4';
    button.append(actionIcon('M22 2 11 13 M22 2 15 22 11 13 2 9Z'));
    button.addEventListener('click', () => window.FlutuContactList.openMessageDialog(contact, {contextType, contextId, delivery}));
    return button;
  }

  function ensureMessageDialog() {
    let dialog = document.getElementById('flutu-global-message-dialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'flutu-global-message-dialog';
    dialog.className = 'flutu-global-message-dialog';
    const sendTitle = window.FlutuI18n?.['Send message'] || 'Send message';
    const deliveryTitle = window.FlutuI18n?.['Delivery method'] || 'Delivery method';
    const contextTypeTitle = window.FlutuI18n?.['Context (optional)'] || 'Context (optional)';
    const noContextLabel = window.FlutuI18n?.['No context'] || 'No context';
    const chooseContextLabel = window.FlutuI18n?.['Choose a context'] || 'Choose a context';
    const eventLabel = window.FlutuI18n?.['Event'] || 'Event';
    const chatLabel = window.FlutuI18n?.['Branching chat'] || 'Branching chat';
    const messageLabel = window.FlutuI18n?.['Message'] || 'Message';
    const emailLabel = window.FlutuI18n?.['Email'] || 'Email';
    const pushLabel = window.FlutuI18n?.['Push notification'] || 'Push notification';
    const cancelLabel = window.FlutuI18n?.['Cancel'] || 'Cancel';
    dialog.innerHTML = `
      <form method="dialog" class="flutu-global-message-form">
        <h3>${sendTitle}</h3>
        <p class="flutu-global-message-recipient"></p>
        <label>
          <span>${deliveryTitle}</span>
          <select class="flutu-global-message-delivery">
            <option value="email">${emailLabel}</option>
            <option value="push">${pushLabel}</option>
          </select>
        </label>
        <label>
          <span>${contextTypeTitle}</span>
          <select class="flutu-global-message-context-type">
            <option value="">${noContextLabel}</option>
            <option value="event">${eventLabel}</option>
            <option value="chat">${chatLabel}</option>
          </select>
        </label>
        <label class="flutu-global-message-context-label" hidden>
          <span>${chooseContextLabel}</span>
          <select class="flutu-global-message-context-id"></select>
        </label>
        <label>
          <span>${messageLabel}</span>
          <textarea class="flutu-global-message-input" rows="5" required maxlength="1000"></textarea>
        </label>
        <p class="flutu-global-message-error" role="alert"></p>
        <div class="flutu-global-message-actions">
          <button type="submit" class="button">${sendTitle}</button>
          <button type="button" class="button button-secondary flutu-global-message-cancel">${cancelLabel}</button>
        </div>
      </form>
    `;
    const style = document.createElement('style');
    style.textContent = `
      .flutu-global-message-dialog { width: min(100% - 24px, 480px); border: 1px solid var(--border, #dfe8ff); border-radius: 16px; background: var(--surface, #fff); color: var(--text, #14213d); padding: 20px; }
      .flutu-global-message-dialog::backdrop { background: rgba(16, 24, 40, .5); }
      .site-contact-entry { justify-content: space-between; }
      .site-contact-entry > .site-contact-message,
      .item-actions > .site-contact-message,
      .site-contact-entry > .site-contact-remove,
      .item-actions > .site-contact-remove {
        margin-left: auto;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        padding: 0;
        border: 1px solid #d5deef;
        border-radius: 9px;
        background: white;
        color: #3655d4;
        font: inherit;
        font-weight: 700;
        text-decoration: none;
        cursor: pointer;
      }
      .site-contact-entry > .site-contact-message:hover,
      .item-actions > .site-contact-message:hover,
      .site-contact-entry > .site-contact-remove:hover,
      .item-actions > .site-contact-remove:hover { background: #f0f4ff; }
      .site-contact-entry > .site-contact-message .contact-action-icon,
      .item-actions > .site-contact-message .contact-action-icon,
      .site-contact-entry > .site-contact-remove .contact-action-icon,
      .item-actions > .site-contact-remove .contact-action-icon {
        display: block;
        width: 18px;
        height: 18px;
        flex: 0 0 auto;
        stroke: currentColor;
        fill: none;
        stroke-linecap: round;
        stroke-linejoin: round;
        stroke-width: 1.8;
      }
      .site-contact-entry > .site-contact-message .contact-action-icon path,
      .item-actions > .site-contact-message .contact-action-icon path,
      .site-contact-entry > .site-contact-remove .contact-action-icon path,
      .item-actions > .site-contact-remove .contact-action-icon path {
        stroke: currentColor;
        fill: none;
        stroke-linecap: round;
        stroke-linejoin: round;
      }
      .flutu-global-message-form { display: grid; gap: 12px; }
      .flutu-global-message-form label { display: grid; gap: 6px; font-weight: 700; }
      .flutu-global-message-form select, .flutu-global-message-form textarea { width: 100%; padding: 10px 12px; border: 1px solid var(--input-border, #cfd7e6); border-radius: 10px; background: var(--input-bg, #fff); color: var(--text, #14213d); font: inherit; }
      .flutu-global-message-form textarea { min-height: 120px; resize: vertical; }
      .flutu-global-message-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
      .flutu-global-message-actions .button { width: auto; margin: 0; }
      .flutu-global-message-error { min-height: 20px; margin: 0; color: #b42318; font-size: .9rem; }
      @media (max-width: 520px) { .flutu-global-message-actions { flex-direction: column-reverse; } }
    `;
    document.head.append(style);
    const form = dialog.querySelector('.flutu-global-message-form');
    const delivery = dialog.querySelector('.flutu-global-message-delivery');
    const contextType = dialog.querySelector('.flutu-global-message-context-type');
    const contextId = dialog.querySelector('.flutu-global-message-context-id');
    const contextLabel = dialog.querySelector('.flutu-global-message-context-label');
    const input = dialog.querySelector('.flutu-global-message-input');
    const recipient = dialog.querySelector('.flutu-global-message-recipient');
    const error = dialog.querySelector('.flutu-global-message-error');
    const cancel = dialog.querySelector('.flutu-global-message-cancel');

    function updateMessageLimit() {
      const limit = delivery.value === 'push' ? 180 : 1000;
      input.maxLength = limit;
    }

    function renderInvitationContexts() {
      const type = contextType.value;
      const entries = type === 'event' ? (window.FlutuContactList._invitationContexts?.events || []) : type === 'chat' ? (window.FlutuContactList._invitationContexts?.chats || []) : [];
      contextId.replaceChildren();
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = window.FlutuI18n?.['Choose a context'] || 'Choose a context';
      contextId.append(placeholder);
      entries.forEach((entry) => {
        const option = document.createElement('option');
        option.value = entry.id;
        option.textContent = entry.title;
        contextId.append(option);
      });
      contextLabel.hidden = !type;
      contextId.required = Boolean(type);
      contextId.disabled = !type;
    }

    async function loadInvitationContexts() {
      if (window.FlutuContactList._invitationContexts) return window.FlutuContactList._invitationContexts;
      const response = await fetch('/api/contact-invitations/contexts');
      if (!response.ok) throw new Error(window.FlutuI18n?.['Could not load invitation contexts.'] || 'Could not load invitation contexts.');
      window.FlutuContactList._invitationContexts = await response.json();
      return window.FlutuContactList._invitationContexts;
    }

    delivery.addEventListener('change', updateMessageLimit);
    contextType.addEventListener('change', renderInvitationContexts);
    cancel.addEventListener('click', () => dialog.close());
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const contact = dialog.dataset.contactId ? { id: dialog.dataset.contactId, name: dialog.dataset.contactName, email: dialog.dataset.contactEmail, registered: dialog.dataset.contactRegistered === 'true' } : null;
      if (!contact) return;
      const message = safeText(input.value);
      if (!message) {
        error.textContent = window.FlutuI18n?.['Write your message'] || 'Write a message before sending it.';
        return;
      }
      error.textContent = '';
      try {
        const response = await fetch('/api/contact-invitations', {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-CSRF-Token': dialog.dataset.csrf || ''},
          body: JSON.stringify({
            contact_id: contact.id,
            delivery: delivery.value,
            message,
            context_type: contextType.value || null,
            context_id: contextId.value || null,
          }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || (window.FlutuI18n?.['Could not send this message.'] || 'Could not send this message.'));
        dialog.close();
        if (window.FlutuI18n && result.delivered) {
          window.dispatchEvent(new CustomEvent('flutu-message-sent', {detail: {name: contact.name}}));
        }
      } catch (err) {
        const code = err?.message || 'Could not send this message.';
        const friendly = code === 'email_delivery_failed'
          ? (window.FlutuI18n?.['Email delivery failed. Please try again or choose a different delivery method.'] || 'Email delivery failed. Please try again or choose a different delivery method.')
          : code === 'push_requires_active_notifications'
            ? (window.FlutuI18n?.['Push notifications only work when the recipient has notifications enabled.'] || 'Push notifications only work when the recipient has notifications enabled.')
            : err.message || (window.FlutuI18n?.['Could not send this message.'] || 'Could not send this message.');
        error.textContent = friendly;
      }
    });
    document.body.append(dialog);
    return dialog;
  }

  async function openMessageDialog(contact, {contextType = '', contextId = '', delivery = 'push'} = {}) {
    const dialog = ensureMessageDialog();
    const deliverySelect = dialog.querySelector('.flutu-global-message-delivery');
    const contextTypeSelect = dialog.querySelector('.flutu-global-message-context-type');
    const contextIdSelect = dialog.querySelector('.flutu-global-message-context-id');
    const contextLabel = dialog.querySelector('.flutu-global-message-context-label');
    const input = dialog.querySelector('.flutu-global-message-input');
    const recipient = dialog.querySelector('.flutu-global-message-recipient');
    const error = dialog.querySelector('.flutu-global-message-error');
    const csrf = document.querySelector('[data-invitation-csrf]')?.dataset.invitationCsrf || document.body.dataset.csrf || '';
    dialog.dataset.contactId = contact?.id || '';
    dialog.dataset.contactName = contact?.name || '';
    dialog.dataset.contactEmail = contact?.email || '';
    dialog.dataset.contactRegistered = contact?.registered ? 'true' : 'false';
    dialog.dataset.csrf = csrf;
    const label = window.FlutuI18n?.['Send a message to {name}'] || 'Send a message to {name}';
    recipient.textContent = label.replace('{name}', contact?.name || 'this contact');
    deliverySelect.value = contact?.registered ? delivery : 'email';
    deliverySelect.disabled = !contact?.registered;
    contextTypeSelect.value = contextType || '';
    contextIdSelect.value = contextId || '';
    contextLabel.hidden = !contextType;
    contextIdSelect.required = Boolean(contextType);
    contextIdSelect.disabled = !contextType;
    input.value = '';
    error.textContent = '';
    input.maxLength = deliverySelect.value === 'push' ? 180 : 1000;
    try {
      await loadInvitationContexts();
      const type = contextTypeSelect.value;
      const entries = type === 'event' ? (window.FlutuContactList._invitationContexts?.events || []) : type === 'chat' ? (window.FlutuContactList._invitationContexts?.chats || []) : [];
      contextIdSelect.replaceChildren();
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = window.FlutuI18n?.['Choose a context'] || 'Choose a context';
      contextIdSelect.append(placeholder);
      entries.forEach((entry) => {
        const option = document.createElement('option');
        option.value = entry.id;
        option.textContent = entry.title;
        contextIdSelect.append(option);
      });
      if (contextId) contextIdSelect.value = contextId;
      contextLabel.hidden = !type;
      contextIdSelect.required = Boolean(type);
      contextIdSelect.disabled = !type;
    } catch (_error) {
      contextLabel.hidden = true;
      contextIdSelect.disabled = true;
      contextIdSelect.required = false;
    }
    dialog.showModal();
    input.focus();
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

  function createEntry(contact, {tagName = 'div', className = '', control = null, actions = null, subtitle = '', showStatus = true, includeMessageAction = false} = {}) {
    const entry = document.createElement(tagName);
    entry.className = `site-contact-entry${className ? ` ${className}` : ''}`;
    if (control) entry.append(control);
    entry.append(createIdentity(contact, {showStatus, subtitle}));
    if (actions) {
      entry.append(actions);
    }
    if (includeMessageAction && contact && (contact.user_id || contact.email || contact.registered !== undefined || contact.id)) {
      const messageAction = createMessageAction(contact, {label: 'Send message'});
      entry.append(messageAction);
    }
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

  window.FlutuContactList = {createEntry, createIdentity, sortByName, createMessageAction, openMessageDialog};
})();