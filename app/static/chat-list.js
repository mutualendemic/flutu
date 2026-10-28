(() => {
  const t = key => window.FlutuI18n?.[key] || key;
  const csrf = document.getElementById('chat-config')?.dataset.csrf || '';
  const realtimeMode = document.getElementById('chat-config')?.dataset.realtimeMode || 'socketio';
  const api = '/chat/api';
  const list = document.getElementById('conversation-list');
  const error = document.getElementById('list-error');
  const realtimeStatus = document.getElementById('realtime-status');
  const dialog = document.getElementById('create-dialog');
  const picker = document.getElementById('contact-picker');
  const search = document.getElementById('contact-search');
  let contacts = [];
  let socket;
  let realtimeConnection;
  let listPollingTimer;

  function initials(value) {
    return (value || '?').trim().split(/\s+/).slice(0, 2).map(part => part[0] || '').join('').toUpperCase();
  }

  function renderConversations(conversations) {
    list.replaceChildren();
    if (!conversations.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      const title = document.createElement('h2');
      title.textContent = t('No conversations yet');
      const copy = document.createElement('p');
      copy.textContent = t('Create a conversation and invite people from your Contacts.');
      empty.append(title, copy);
      list.append(empty);
      return;
    }
    for (const conversation of conversations) {
      const card = document.createElement('article');
      card.className = 'conversation-card';
      const link = document.createElement('a');
      link.className = 'conversation-link';
      link.href = `/chat/${encodeURIComponent(conversation.id)}`;
      const title = document.createElement('h2');
      title.textContent = conversation.title;
      const meta = document.createElement('p');
      meta.className = 'chat-meta';
      const activeCount = conversation.members.filter(member => member.active).length;
      const questionCount = conversation.question_count ?? 0;
      meta.textContent = `${activeCount} ${t(activeCount === 1 ? 'member' : 'members')} · ${questionCount} ${t(questionCount === 1 ? 'question' : 'questions')}`;
      const dots = document.createElement('div');
      dots.className = 'member-dots';
      dots.setAttribute('aria-label', conversation.members.map(member => member.name).join(', '));
      for (const member of conversation.members.slice(0, 8)) {
        const dot = document.createElement('span');
        dot.className = 'member-dot';
        dot.style.backgroundColor = member.active ? member.color : '#8a8f98';
        dot.title = `${member.name}${member.active ? '' : ` (${t('former member')})`}`;
        dot.textContent = initials(member.name);
        if (member.picture) {
          try {
            const pictureUrl = new URL(member.picture, window.location.origin);
            if (pictureUrl.protocol === 'https:') {
              const image = document.createElement('img');
              image.className = 'member-dot member-photo';
              image.src = pictureUrl.href;
              image.alt = '';
              image.title = dot.title;
              image.referrerPolicy = 'no-referrer';
              image.addEventListener('error', () => image.replaceWith(dot), {once: true});
              dots.append(image);
              continue;
            }
          } catch (_) { /* Keep initials when a profile photo URL is invalid. */ }
        }
        dots.append(dot);
      }
      link.append(title, meta, dots);
      card.append(link);
      if (conversation.is_owner) {
        const deleteButton = document.createElement('button');
        deleteButton.className = 'button button-danger small-button conversation-delete';
        deleteButton.type = 'button';
        deleteButton.textContent = t('Delete');
        deleteButton.setAttribute('aria-label', `${t('Delete')}: ${conversation.title}`);
        deleteButton.addEventListener('click', () => deleteConversation(conversation, deleteButton));
        card.append(deleteButton);
      }
      list.append(card);
    }
  }

  async function deleteConversation(conversation, button) {
    const confirmed = window.confirm(
      t('Permanently delete “{title}” for all members? Its questions and answers will also be deleted.').replace('{title}', conversation.title)
    );
    if (!confirmed) return;
    await window.FlutuAction.run(button, async () => {
      try {
        const response = await fetch(`${api}/conversations/${encodeURIComponent(conversation.id)}`, {
          method: 'DELETE', headers: {'X-CSRF-Token': csrf},
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || t('Could not delete conversation.'));
        await loadConversations();
      } catch (err) {
        error.textContent = err.message;
      }
    });
  }

  async function loadConversations() {
    const response = await fetch(`${api}/conversations`);
    if (!response.ok) throw new Error(t('Could not load conversations.'));
    renderConversations((await response.json()).conversations);
  }

  function startListPolling() {
    if (listPollingTimer) return;
    if (socket) socket.disconnect();
    realtimeStatus.textContent = t('Supabase private-channel check failed. Using slower polling.');
    listPollingTimer = window.setInterval(() => loadConversations().catch(() => {}), 5000);
  }

  function setupSupabaseRealtime() {
    realtimeStatus.textContent = t('Checking private channel access with Supabase…');
    if (!window.FlutuChatRealtime?.connect) {
      realtimeStatus.textContent = t('Supabase client is unavailable. Using slower polling.');
      startListPolling();
      return;
    }
    window.FlutuChatRealtime.connect((topic, payload) => {
      if (!topic.startsWith('chat-user:')) return;
      loadConversations().catch(() => {});
      if (realtimeConnection) realtimeConnection.refresh().catch(() => startListPolling());
    }, (state, detail) => {
      if (state === 'CONNECTED') {
        window.clearInterval(listPollingTimer);
        listPollingTimer = undefined;
        realtimeStatus.textContent = t('Supabase accepted the private channel subscription.');
        realtimeStatus.classList.remove('error');
      } else if (state === 'AUTHORIZATION_FAILED' || state === 'CHANNEL_ERROR' || state === 'TIMED_OUT' || state === 'CLOSED' || state === 'ERROR') {
        realtimeStatus.classList.add('error');
        realtimeStatus.textContent = `${t(detail?.message || 'Supabase private-channel authorization failed. Check the realtime.messages SELECT RLS policy.')} ${t('Using slower polling.')}`;
        startListPolling();
      }
    }, {userOnly: true}).then(connection => { realtimeConnection = connection; })
      .catch(() => startListPolling());
  }

  function renderContacts() {
    const query = search.value.trim().toLowerCase();
    picker.replaceChildren();
    for (const contact of contacts.filter(item => `${item.name} ${item.email}`.toLowerCase().includes(query))) {
      const label = document.createElement('label');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = contact.user_id || '';
      checkbox.disabled = !contact.addable;
      const text = document.createElement('span');
      const name = document.createElement('strong');
      name.textContent = contact.name;
      const detail = document.createElement('small');
      detail.textContent = contact.addable ? contact.email : t('Not on the app');
      text.append(name, detail);
      label.append(checkbox, text);
      picker.append(label);
    }
    if (!picker.children.length) {
      const empty = document.createElement('p');
      empty.textContent = t('No contacts match your search.');
      picker.append(empty);
    }
  }

  async function openCreateDialog() {
    document.getElementById('create-error').textContent = '';
    document.getElementById('conversation-title').value = '';
    try {
      const response = await fetch(`${api}/contacts/addable`);
      if (!response.ok) throw new Error(t('Could not load Contacts.'));
      contacts = (await response.json()).contacts;
      renderContacts();
      dialog.showModal();
    } catch (err) {
      document.getElementById('create-error').textContent = err.message;
    }
  }

  document.getElementById('new-conversation').addEventListener('click', openCreateDialog);
  document.getElementById('cancel-create').addEventListener('click', () => dialog.close());
  search.addEventListener('input', renderContacts);
  document.getElementById('create-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    await window.FlutuAction.run(event.submitter || form.querySelector('[type="submit"]'), async () => {
      try {
        const member_user_ids = [...picker.querySelectorAll('input:checked')].map(input => input.value);
        const response = await fetch(`${api}/conversations`, {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
          body: JSON.stringify({title: document.getElementById('conversation-title').value, member_user_ids}),
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || t('Could not create conversation.'));
        window.location.assign(`/chat/${encodeURIComponent(body.conversation_id)}`);
      } catch (err) {
        document.getElementById('create-error').textContent = err.message;
      }
    });
  });

  loadConversations().catch(err => { error.textContent = err.message; });
  if (realtimeMode === 'supabase') {
    setupSupabaseRealtime();
  } else if (realtimeMode === 'polling') {
    startListPolling();
  } else if (typeof window.io === 'function') {
    socket = window.io('/chat');
    socket.on('conversation_added', () => loadConversations().catch(() => {}));
    socket.on('conversation_removed', () => loadConversations().catch(() => {}));
    socket.on('connect_error', startListPolling);
  } else startListPolling();
})();
