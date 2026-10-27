(() => {
  const root = document.querySelector('.conversation-page');
  const conversationId = root.dataset.conversationId;
  const csrf = root.dataset.csrf;
  const realtimeMode = root.dataset.realtimeMode || 'socketio';
  const api = '/chat/api';
  const graphElement = document.getElementById('graph');
  const status = document.getElementById('connection-status');
  const details = document.getElementById('details');
  const error = document.getElementById('chat-error');
  const optionsEditor = document.getElementById('option-editors');
  const answerDialog = document.getElementById('answer-dialog');
  const membersPanel = document.getElementById('members-panel');
  const nodes = new Map();
  const edges = new Map();
  let graph;
  let snapshot;
  let socket;
  let realtimeConnection;
  let pollingTimer;
  let polling = false;
  let selectedOption;
  let followUpOption;
  let canCreateRoot = false;

  function el(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function setError(message) { error.textContent = message || ''; }
  function position(data) {
    const x = 120 + Number(data.lane || 0) * 180;
    const y = 120 + Number(data.row || 0) * 90;
    return data.type === 'author_avatar' ? {x: x - 66, y: y} : {x, y};
  }
  function cyNode(data) {
    return {group: 'nodes', data: {...data}, position: position(data)};
  }

  function cyEdge(data) {
    return {group: 'edges', data: {...data, id: `${data.kind}:${data.from}:${data.to}`, source: data.from, target: data.to}};
  }

  function ensureGraph() {
    if (graph) return;
    graph = window.cytoscape({
      container: graphElement,
      elements: [],
      layout: {name: 'preset', fit: true, padding: 28},
      minZoom: 0.35, maxZoom: 2.5, wheelSensitivity: 0.18,
      boxSelectionEnabled: false,
      autounselectify: true,
      userPanningEnabled: false,
      panningEnabled: true,
      zoomingEnabled: true,
      style: [
        {selector: 'node[type="question"]', style: {label: 'data(label)', shape: 'round-rectangle', width: 145, height: 46, 'text-wrap': 'wrap', 'text-max-width': 132, 'font-size': 11, color: '#14213d', 'background-color': '#ffffff', 'border-width': 2, 'border-color': '#f79009', 'text-valign': 'center', 'text-halign': 'center'}},
        {selector: 'node[type="question"][status="closed"]', style: {'background-color': '#f2f4f7', 'border-color': '#98a2b3'}},
        {selector: 'node[type="author_avatar"]', style: {label: 'data(label)', shape: 'ellipse', width: 34, height: 34, 'font-size': 9, 'font-weight': 700, color: '#fff', 'text-valign': 'center', 'text-halign': 'center', 'background-color': '#53627b', 'background-image': 'data(picture)', 'background-fit': 'cover', 'background-clip': 'node', 'border-width': 2, 'border-color': '#ffffff'}},
        {selector: 'node[type="option"]', style: {label: 'data(display)', shape: 'round-rectangle', width: 132, height: 40, 'font-size': 10, color: '#344054', 'background-color': '#fff7e6', 'border-width': 1, 'border-color': '#f79009', 'text-valign': 'center', 'text-halign': 'center'}},
        {selector: 'node[type="option"][quantum_selected]', style: {'border-width': 3, 'border-color': '#12b76a', 'background-color': '#ecfdf3'}},
        {selector: 'node[type="option"][is_winner]', style: {'border-width': 3, 'border-color': '#12b76a', 'background-color': '#ecfdf3'}},
        {selector: 'node[type="option"][is_tied]', style: {'border-width': 3, 'border-color': '#12b76a'}},
        {selector: 'node[type="end"]', style: {label: 'data(label)', shape: 'ellipse', width: 16, height: 16, 'font-size': 8, color: '#667085', 'background-color': '#98a2b3'}},
        {selector: 'edge[kind="main_thread"]', style: {width: 2, 'line-color': '#98a2b3', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#98a2b3', 'curve-style': 'bezier'}},
        {selector: 'edge[kind="branch"]', style: {width: 2, 'line-color': '#f79009', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#f79009', 'curve-style': 'taxi'}},
        {selector: 'edge[kind="follow_up"]', style: {width: 2, 'line-color': '#7f77dd', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#7f77dd', 'curve-style': 'taxi'}},
        {selector: 'edge[kind="merge"]', style: {width: 2, 'line-color': '#667085', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#667085', 'line-style': 'dashed', 'curve-style': 'taxi'}},
      ],
    });
    graph.on('tap', 'node', event => selectNode(event.target.data()));
  }

  function applyGraph(data) {
    if (!data || !Array.isArray(data.nodes)) return;
    snapshot = data;
    canCreateRoot = data.can_create_initial_question === true;
    document.getElementById('conversation-title').textContent = data.title || 'Conversation';
    ensureGraph();
    const graphNodes = data.nodes.flatMap(node => {
      if (node.type !== 'question') return [node];
      const authorName = node.author_name || memberName(node.author_user_id);
      let picture = '';
      try {
        const parsed = new URL(node.author_picture || '', window.location.origin);
        if (parsed.protocol === 'https:') picture = parsed.href;
      } catch (_) { /* Use initials when the profile image URL is invalid. */ }
      const initials = authorName.trim().split(/\s+/).map(part => part[0] || '').slice(0, 2).join('').toUpperCase();
      return [node, {
        id: `a${node.id.slice(1)}`,
        type: 'author_avatar',
        label: picture ? '' : initials,
        picture,
        author_name: authorName,
        question_id: node.id.slice(1),
        lane: node.lane,
        row: node.row,
      }];
    });
    const nextNodeIds = new Set();
    for (const node of graphNodes) {
      nextNodeIds.add(node.id);
      node.display = node.type === 'option'
        ? `${node.label} · ${node.quantum_selected ? 'selected path' : 'not selected'}`
        : node.label;
      nodes.set(node.id, node);
      const existing = graph.getElementById(node.id);
      if (existing.length) {
        existing.data(node);
        existing.animate({position: position(node)}, {duration: 250});
      } else graph.add(cyNode(node));
    }
    graph.nodes().forEach(node => {
      if (!nextNodeIds.has(node.id())) node.remove();
      node.lock();
    });
    const nextEdgeIds = new Set();
    for (const edge of data.edges || []) {
      const id = `${edge.kind}:${edge.from}:${edge.to}`;
      nextEdgeIds.add(id);
      edges.set(id, edge);
      if (!graph.getElementById(id).length) graph.add(cyEdge(edge));
    }
    graph.edges().forEach(edge => { if (!nextEdgeIds.has(edge.id())) edge.remove(); });
    graph.layout({name: 'preset', fit: false}).run();
    if (!data.nodes.length) {
      details.replaceChildren(
        el('h2', canCreateRoot ? 'Start the conversation' : 'Waiting for the first question'),
        el('p', canCreateRoot ? 'Create the opening question and provide the answer options. The quantum selector will choose the path.' : 'The conversation creator will add the opening question. After that, every participant can add follow-up questions to the quantum-selected option.'),
      );
    }
    const composer = document.querySelector('.composer');
    const banner = document.getElementById('quantum-branch-banner');
    if (composer) composer.hidden = !(canCreateRoot || followUpOption);
    if (banner) banner.classList.toggle('visible', data.branch_mode === 'quantum_random');
    document.getElementById('send-question').textContent = followUpOption ? 'Send follow-up' : 'Create first question';
    document.getElementById('add-option').hidden = Boolean(followUpOption);
    optionsEditor.hidden = Boolean(followUpOption);
    document.getElementById('cancel-question').hidden = !followUpOption;
    const canManageMembers = data.can_manage_members === true;
    document.querySelector('label[for="member-search"]').hidden = !canManageMembers;
    document.getElementById('member-search').hidden = !canManageMembers;
    document.getElementById('member-picker').hidden = !canManageMembers;
    renderMembers(data.members || []);
  }

  async function resync() {
    const response = await fetch(`${api}/conversations/${encodeURIComponent(conversationId)}`);
    if (response.status === 401) window.location.assign('/');
    if (response.status === 403) window.location.assign('/chat/');
    if (!response.ok) throw new Error('Could not load this conversation.');
    applyGraph(await response.json());
  }

  function memberName(userId) {
    return snapshot?.members?.find(member => member.user_id === userId)?.name || 'Former member';
  }

  function renderDetailsQuestion(node) {
    details.replaceChildren();
    const title = el('h2', node.label);
    const member = snapshot?.members?.find(item => item.user_id === node.author_user_id);
    const authorRow = el('div', undefined, 'question-author');
    const avatar = el('span', (member?.name || 'Flutu member').trim().split(/\s+/).map(part => part[0] || '').slice(0, 2).join('').toUpperCase(), 'question-author-avatar');
    avatar.setAttribute('aria-hidden', 'true');
    const pictureUrl = member?.picture;
    if (pictureUrl) {
      try {
        const parsedUrl = new URL(pictureUrl, window.location.origin);
        if (parsedUrl.protocol === 'https:') {
          const image = document.createElement('img');
          image.className = 'question-author-avatar';
          image.src = parsedUrl.href;
          image.alt = `${member?.name || 'Question author'}'s profile photo`;
          image.referrerPolicy = 'no-referrer';
          image.addEventListener('error', () => image.replaceWith(avatar), {once: true});
          authorRow.append(image);
        }
      } catch (_) { /* Show initials when a profile photo URL is invalid. */ }
    }
    if (!authorRow.children.length) authorRow.append(avatar);
    const author = el('p', `Asked by ${member?.name || memberName(node.author_user_id)} · ${node.status}`);
    authorRow.append(author);
    details.append(title, authorRow);
    if (node.status === 'open' && snapshot?.branch_mode !== 'quantum_random') {
      const close = el('button', 'Close question', 'button button-secondary');
      close.type = 'button';
      close.addEventListener('click', async () => {
        await window.FlutuAction.run(close, async () => {
          try { await performAction('close_question', {question_id: node.id.slice(1)}); await resync(); }
          catch (err) { setError(err.message); }
        });
      });
      details.append(close);
    }
    const opts = (snapshot.nodes || []).filter(item => item.type === 'option' && item.question_id === node.id.slice(1));
    for (const option of opts) {
      const names = option.voter_user_ids.map((id, index) => option.voter_names[index] || memberName(id));
      details.append(el('p', `${option.label}: ${option.count} ${option.count === 1 ? 'vote' : 'votes'}${names.length ? ` — ${names.join(', ')}` : ''}`));
    }
  }

  function selectNode(node) {
    const value = nodes.get(node.id) || node;
    if (value.type === 'author_avatar') {
      const question = nodes.get(`q${value.question_id}`);
      if (question) renderDetailsQuestion(question);
      return;
    }
    if (value.type === 'question') {
      renderDetailsQuestion(value);
      return;
    }
    if (value.type !== 'option') return;
    selectedOption = value;
    details.replaceChildren();
    details.append(el('h2', value.label));
    details.append(el('p', `${value.count} ${value.count === 1 ? 'vote' : 'votes'}`));
    const question = nodes.get(`q${value.question_id}`);
    if (question?.status === 'open' && snapshot?.branch_mode !== 'quantum_random') {
      const answer = el('button', 'Choose this option', 'button');
      answer.type = 'button';
      answer.addEventListener('click', () => openAnswer(question, value));
      details.append(answer);
    }
    if (snapshot?.branch_mode === 'quantum_random' && value.quantum_selected) {
      details.append(el('p', 'Chosen by the quantum selector; this is the active path.'));
      const follow = el('button', 'Follow up', 'button button-secondary');
      follow.type = 'button';
      follow.addEventListener('click', () => {
        followUpOption = value.option_id;
        document.getElementById('composer-title').textContent = `Follow up on “${value.label}”`;
        document.getElementById('question-text').value = '';
        document.querySelector('.composer').hidden = false;
        document.getElementById('cancel-question').hidden = false;
        document.getElementById('send-question').textContent = 'Send follow-up';
        document.getElementById('add-option').hidden = false;
        optionsEditor.hidden = false;
        document.getElementById('question-text').focus();
        document.querySelector('.composer').scrollIntoView({behavior: 'smooth', block: 'center'});
      });
      details.append(follow);
    } else if (snapshot?.branch_mode === 'quantum_random') {
      details.append(el('p', 'Not selected by the quantum selector; follow-ups can only continue from the selected option.'));
    }
  }

  function openAnswer(question, selected) {
    document.getElementById('answer-title').textContent = question.label;
    answerDialog.dataset.questionId = question.id.slice(1);
    const options = document.getElementById('answer-options');
    options.replaceChildren();
    const branchSelection = snapshot?.branch_mode === 'quantum_random' ? question.quantum_selected_option_id : null;
    const choice = branchSelection || selected.option_id;
    for (const option of (snapshot.nodes || []).filter(item => item.type === 'option' && item.question_id === question.id.slice(1))) {
      const label = el('label', undefined, 'answer-option');
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'option_id'; radio.value = option.option_id; radio.required = true;
      radio.checked = option.option_id === choice || option.is_my_vote === true;
      if (snapshot?.branch_mode === 'quantum_random') {
        radio.disabled = true;
      }
      label.append(radio, document.createTextNode(`${option.label} (${option.count})`));
      options.append(label);
    }
    document.getElementById('answer-error').textContent = '';
    answerDialog.showModal();
  }

  function handleAck(response) {
    if (!response?.ok) throw new Error(response?.error || 'The action could not be completed.');
    return response;
  }

  async function performAction(event, payload) {
    let path;
    let body = payload;
    if (event === 'create_question') {
      path = `${api}/conversations/${encodeURIComponent(payload.conversation_id)}/questions`;
      body = {...payload};
      delete body.conversation_id;
    } else if (event === 'submit_answer') {
      path = `${api}/questions/${encodeURIComponent(payload.question_id)}/answers`;
    } else if (event === 'close_question') {
      path = `${api}/questions/${encodeURIComponent(payload.question_id)}/close`;
    } else {
      throw new Error('Unsupported chat action.');
    }
    const response = await fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The action could not be completed.');
    return result;
  }

  async function emitAck(event, payload, button) {
    return window.FlutuAction.run(button, async () => {
    setError('');
    try {
      await performAction(event, payload);
      if (event === 'create_question') {
        document.getElementById('question-text').value = '';
        followUpOption = undefined;
        document.getElementById('composer-title').textContent = 'Start the conversation';
        createOptionEditors(['Yes', 'No']);
      }
      await resync();
    } catch (err) { setError(err.message); }
    });
  }

  function createOptionEditors(labels) {
    optionsEditor.replaceChildren();
    labels.forEach((value, index) => {
      const row = el('div', undefined, 'option-editor');
      const input = document.createElement('input');
      input.type = 'text'; input.maxLength = 60; input.value = value; input.setAttribute('aria-label', `Option ${index + 1}`);
      const remove = el('button', 'Remove'); remove.type = 'button'; remove.disabled = labels.length <= 2;
      remove.addEventListener('click', () => {
        if (optionsEditor.children.length <= 2) return;
        row.remove();
        [...optionsEditor.querySelectorAll('input')].forEach((field, idx) => field.setAttribute('aria-label', `Option ${idx + 1}`));
        [...optionsEditor.querySelectorAll('button')].forEach(button => button.disabled = optionsEditor.children.length <= 2);
      });
      row.append(input, remove); optionsEditor.append(row);
    });
  }

  function renderMembers(members) {
    const list = document.getElementById('member-list');
    list.replaceChildren();
    for (const member of members) {
      const item = el('li', undefined, 'member-chip');
      const initials = (member.name || '?').trim().split(/\s+/).map(part => part[0] || '').slice(0, 2).join('').toUpperCase();
      const dot = el('span', initials, 'member-avatar');
      dot.style.backgroundColor = member.active ? member.color : '#8a8f98';
      if (member.picture) {
        try {
          const pictureUrl = new URL(member.picture, window.location.origin);
          if (pictureUrl.protocol === 'https:') {
            const image = document.createElement('img');
            image.className = 'member-avatar';
            image.src = pictureUrl.href;
            image.alt = '';
            image.referrerPolicy = 'no-referrer';
            image.addEventListener('error', () => image.replaceWith(dot), {once: true});
            item.append(image);
          }
        } catch (_) { /* Use initials when a profile photo URL is invalid. */ }
      }
      if (!item.children.length) item.append(dot);
      item.append(el('span', `${member.name}${member.active ? '' : ' (former member)'}`));
      if (member.active && member.role !== 'owner') {
        const remove = el('button', 'Remove'); remove.type = 'button';
        remove.addEventListener('click', () => changeMemberWithLoading(remove, member.user_id, 'DELETE'));
        item.append(remove);
      }
      list.append(item);
    }
  }

  async function changeMember(userId, method) {

    const response = await fetch(`${api}/conversations/${encodeURIComponent(conversationId)}/members/${encodeURIComponent(userId)}`, {method, headers: {'X-CSRF-Token': csrf}});
    const body = response.status === 204 ? {} : await response.json();
    if (!response.ok) { setError(body.error || 'Could not update members.'); return; }
    await resync();
  }

  async function changeMemberWithLoading(button, userId, method) {
    await window.FlutuAction.run(button, async () => changeMember(userId, method));
  }

  async function loadMemberPicker() {
    const host = document.getElementById('member-picker');
    const search = document.getElementById('member-search');
    const response = await fetch(`${api}/contacts/addable?conversation_id=${encodeURIComponent(conversationId)}`);
    if (!response.ok) return;
    const contacts = (await response.json()).contacts;
    const draw = () => {
      host.replaceChildren();
      const query = search.value.trim().toLowerCase();
      contacts.filter(contact => `${contact.name} ${contact.email}`.toLowerCase().includes(query)).forEach(contact => {
        const label = el('label');
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = contact.user_id || ''; checkbox.disabled = !contact.addable;
        const text = el('span'); text.append(el('strong', contact.name), el('small', contact.addable ? contact.email : 'Not on the app'));
        label.append(checkbox, text); host.append(label);
      });
    };
    search.addEventListener('input', draw); draw();
  }

  function eventRefresh() { resync().catch(err => setError(err.message)); }
  function startPolling() {
    if (polling) return;
    polling = true;
    if (socket) socket.disconnect();
    status.dataset.connected = 'true';
    status.textContent = 'Live updates · polling';
    const poll = async () => {
      try {
        await resync();
        status.dataset.connected = 'true';
        status.textContent = 'Live updates · polling';
      } catch (err) {
        status.dataset.connected = 'false';
        status.textContent = 'Reconnecting';
        setError(err.message);
      } finally {
        if (polling) pollingTimer = window.setTimeout(poll, 3000);
      }
    };
    pollingTimer = window.setTimeout(poll, 5000);
  }

  function setupSupabaseRealtime() {
    if (!window.FlutuChatRealtime?.connect) {
      startPolling();
      return;
    }
    window.FlutuChatRealtime.connect((topic, payload) => {
      if (topic === `chat-conversation:${conversationId}`) {
        eventRefresh();
        return;
      }
      if (payload.kind === 'conversation_removed' && payload.conversation_id === conversationId) {
        window.location.assign('/chat/');
        return;
      }
      if (realtimeConnection) realtimeConnection.refresh().catch(() => startPolling());
      eventRefresh();
    }, (state, detail) => {
      if (state === 'CONNECTED') {
        status.dataset.connected = 'true';
        status.textContent = 'Private channel authorized · Supabase Realtime';
        status.title = 'Supabase accepted the private channel subscription under its Realtime authorization policy.';
        setError('');
        if (polling) {
          polling = false;
          window.clearTimeout(pollingTimer);
        }
      } else if (state === 'AUTHORIZATION_FAILED' || state === 'CHANNEL_ERROR' || state === 'TIMED_OUT' || state === 'CLOSED' || state === 'ERROR') {
        status.dataset.connected = 'false';
        status.textContent = 'Supabase private-channel check failed · using polling';
        status.title = detail?.message || 'Review private-channel settings and the realtime.messages SELECT RLS policy.';
        setError(`${status.title} Chat is continuing with slower polling.`);
        startPolling();
      }
    }, {conversationId}).then(connection => { realtimeConnection = connection; })
      .catch(() => startPolling());
  }

  function setupSocket() {
    socket = window.io('/chat');
    socket.on('connect', () => {
      status.dataset.connected = 'true'; status.textContent = 'Connected';
      socket.emit('join', {conversation_id: conversationId}, response => {
        try { handleAck(response); applyGraph(response.graph); }
        catch (err) { setError(err.message); }
      });
    });
    socket.on('disconnect', () => {
      status.dataset.connected = 'false'; status.textContent = 'Switching to polling';
      startPolling();
    });
    socket.on('connect_error', () => {
      status.dataset.connected = 'false'; status.textContent = 'Switching to polling';
      startPolling();
    });
    socket.on('question_created', payload => {
      const additions = [...(payload.question ? [payload.question] : []), ...(payload.options || [])];
      const newNodes = new Map((snapshot?.nodes || []).map(node => [node.id, node]));
      additions.forEach(node => newNodes.set(node.id, node));
      const newEdges = new Map((snapshot?.edges || []).map(edge => [`${edge.kind}:${edge.from}:${edge.to}`, edge]));
      (payload.edges || []).forEach(edge => newEdges.set(`${edge.kind}:${edge.from}:${edge.to}`, edge));
      if (snapshot) applyGraph({...snapshot, nodes: [...newNodes.values()], edges: [...newEdges.values()]});
      else eventRefresh();
    });
    socket.on('answer_recorded', payload => {
      const questionId = String(payload.question_id);
      const changed = nodes.get(`o${payload.option_id}`);
      if (changed) {
        changed.voter_user_ids = changed.voter_user_ids.filter(id => id !== payload.user_id).concat(payload.user_id);
        if (!changed.voter_names.includes(memberName(payload.user_id))) changed.voter_names.push(memberName(payload.user_id));
      }
      if (payload.previous_option_id && payload.previous_option_id !== payload.option_id) {
        const previous = nodes.get(`o${payload.previous_option_id}`);
        if (previous) {
          previous.voter_user_ids = previous.voter_user_ids.filter(id => id !== payload.user_id);
          previous.voter_names = previous.voter_names.filter(name => name !== memberName(payload.user_id));
        }
      }
      const updateNodes = (snapshot?.nodes || []).map(node => {
        if (node.type !== 'option' || node.question_id !== questionId) return node;
        const target = nodes.get(node.id) || node;
        target.count = payload.counts[node.option_id] ?? target.count;
        return target;
      });
      if (snapshot) applyGraph({...snapshot, nodes: updateNodes});
      if (payload.closed) eventRefresh();
    });
    socket.on('question_closed', eventRefresh);
    socket.on('question_updated', eventRefresh);
    socket.on('question_deleted', eventRefresh);
    socket.on('member_added', eventRefresh);
    socket.on('member_removed', eventRefresh);
    socket.on('conversation_removed', () => { window.location.assign('/chat/'); });
  }

  document.getElementById('add-option').addEventListener('click', () => {
    if (optionsEditor.children.length >= 10) return;
    const labels = [...optionsEditor.querySelectorAll('input')].map(input => input.value).concat('');
    createOptionEditors(labels);
  });
  document.getElementById('send-question').addEventListener('click', event => {
    const options = [...optionsEditor.querySelectorAll('input')].map(input => input.value);
    emitAck('create_question', {conversation_id: conversationId, text: document.getElementById('question-text').value, options, ...(followUpOption ? {parent_option_id: followUpOption} : {})}, event.currentTarget);
  });
  document.getElementById('cancel-question').addEventListener('click', () => {
    followUpOption = undefined;
    document.getElementById('composer-title').textContent = 'Start the conversation';
    document.getElementById('question-text').value = '';
    document.querySelector('.composer').hidden = !canCreateRoot;
    document.getElementById('cancel-question').hidden = true;
    document.getElementById('add-option').hidden = false;
    optionsEditor.hidden = false;
  });
  document.getElementById('answer-form').addEventListener('submit', event => {
    event.preventDefault();
    const submitButton = event.submitter || event.currentTarget.querySelector('[type="submit"]');
    const optionId = new FormData(event.currentTarget).get('option_id');
    window.FlutuAction.run(submitButton, async () => {
      try {
        await performAction('submit_answer', {question_id: answerDialog.dataset.questionId, option_id: optionId});
        answerDialog.close();
        await resync();
      } catch (err) { document.getElementById('answer-error').textContent = err.message; }
    });
  });
  document.getElementById('cancel-answer').addEventListener('click', () => answerDialog.close());
  document.getElementById('members-toggle').addEventListener('click', async event => {
    const toggle = event.currentTarget;
    membersPanel.hidden = !membersPanel.hidden;
    toggle.setAttribute('aria-expanded', String(!membersPanel.hidden));
    toggle.setAttribute('aria-checked', String(!membersPanel.hidden));
    if (!membersPanel.hidden && snapshot?.can_manage_members) await loadMemberPicker();
  });
  document.getElementById('member-picker').addEventListener('change', async event => {
    if (!event.target.matches('input[type=checkbox]:checked')) return;
    const checkbox = event.target;
    checkbox.disabled = true;
    try {
      const response = await fetch(`${api}/conversations/${encodeURIComponent(conversationId)}/members`, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        body: JSON.stringify({user_ids: [checkbox.value]}),
      });
      const body = await response.json();
      if (!response.ok) setError(body.error || 'Could not add member.'); else await resync();
    } catch (err) {
      setError(err.message || 'Could not add member.');
    } finally {
      checkbox.checked = false;
      checkbox.disabled = false;
    }
  });

  createOptionEditors(['Yes', 'No']);
  resync().catch(err => setError(err.message));
  if (typeof window.cytoscape !== 'function') {
    setError('The chat graph could not load. Check the network connection and try again.');
  } else if (realtimeMode === 'supabase') {
    setupSupabaseRealtime();
  } else if (realtimeMode === 'polling') {
    startPolling();
  } else if (typeof window.io === 'function') {
    setupSocket();
  } else {
    startPolling();
  }
})();
