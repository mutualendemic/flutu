(() => {
  const config = document.getElementById('calendar-config');
  if (!config) return;

  const t = key => window.FlutuI18n?.[key] || key;
  const locale = config.dataset.locale;
  const api = {
    events: config.dataset.eventsUrl,
    occurrences: config.dataset.occurrencesUrl,
    contacts: config.dataset.contactsUrl,
    conversations: config.dataset.conversationsUrl,
    locationSearch: config.dataset.locationSearchUrl
  };
  const conversationTemplate = config.dataset.conversationTemplate;
  const monthGrid = document.getElementById('month-grid');
  const agendaTitle = document.getElementById('agenda-title');
  const agendaGrid = document.getElementById('agenda-grid');
  const eventDetail = document.getElementById('event-detail');
  const statusMessage = document.getElementById('calendar-status');
  const dialog = document.getElementById('event-dialog');
  const form = document.getElementById('event-form');
  const dateList = document.getElementById('date-list');
  const guestPicker = document.getElementById('guest-picker');
  const conversationPicker = document.getElementById('conversation-picker');
  const pointList = document.getElementById('point-list');
  const formError = document.getElementById('form-error');
  const titleInput = document.getElementById('event-title');
  const descriptionInput = document.getElementById('event-description');
  const pinImageInput = document.getElementById('point-image');
  const pointLabelInput = document.getElementById('point-label');
  const coverImageInput = document.getElementById('event-cover-image');
  const coverPreview = document.getElementById('event-cover-preview');
  const coverPreviewImage = document.getElementById('event-cover-preview-image');
  const removeCoverButton = document.getElementById('remove-event-cover');
  const locationSearchInput = document.getElementById('location-search-input');
  const locationSearchButton = document.getElementById('search-location');
  const locationSearchResults = document.getElementById('location-search-results');
  const addPointButton = document.getElementById('add-point');
  const cancelPointEditButton = document.getElementById('cancel-point-edit');
  let visibleMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
  let selectedDate = new Date();
  let selectedOccurrence = null;
  let events = [];
  let occurrences = [];
  let contacts = [];
  let conversations = [];
  let mapPoints = [];
  let editorMap;
  let pointMarkers = [];
  let draftMarker;
  let draftCoordinates = null;
  let editingPointIndex = null;
  let coverImageId = null;
  let coverImageData = '';
  let coverPreviewObjectUrl = '';

  function localDateKey(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }

  function agendaScrollTime(date) {
    const now = new Date();
    const scrollDate = localDateKey(date) === localDateKey(now) ? now : new Date(2000, 0, 1, 10);
    return `${String(scrollDate.getHours()).padStart(2, '0')}:${String(scrollDate.getMinutes()).padStart(2, '0')}:00`;
  }

  function linkedEventTarget() {
    const params = new URLSearchParams(window.location.search);
    const eventId = params.get('event');
    if (!eventId) return null;
    const rawStartAt = params.get('date');
    const startAt = rawStartAt ? new Date(rawStartAt) : null;
    return { eventId, startAt: startAt && Number.isFinite(startAt.getTime()) ? startAt : null };
  }

  function localDateTime(date) {
    const adjusted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return adjusted.toISOString().slice(0, 16);
  }

  function formatDate(date, options = { dateStyle: 'full' }) {
    return new Intl.DateTimeFormat(locale, options).format(date);
  }

  async function callApi(url, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = config.dataset.csrf;
    const response = await fetch(url, { ...options, headers });
    const data = response.status === 204 ? {} : await response.json();
    if (!response.ok) throw new Error(data.error || t('The request could not be completed.'));
    return data;
  }

  function setStatus(message = '', isError = false) {
    statusMessage.textContent = message;
    statusMessage.classList.toggle('is-error', isError);
  }

  function statusText(value) {
    return t(value === 'closed' ? 'Closed' : 'Open');
  }

  const eventPalettes = [
    { open: '#2948b8', closed: '#7180b2' },
    { open: '#3655d4', closed: '#7d89bc' },
    { open: '#4263dc', closed: '#6978aa' },
    { open: '#2342a8', closed: '#7885b0' },
    { open: '#4a67d9', closed: '#838dbb' },
    { open: '#304fbf', closed: '#64749f' },
    { open: '#3d59c6', closed: '#727fa9' },
    { open: '#1f3e9b', closed: '#66759f' }
  ];

  function eventColor(eventId, status) {
    let colorSeed = 0;
    for (const character of String(eventId)) {
      colorSeed = (colorSeed * 31 + character.charCodeAt(0)) >>> 0;
    }
    const palette = eventPalettes[colorSeed % eventPalettes.length];
    return status === 'closed' ? palette.closed : palette.open;
  }

  function eventColorText(backgroundColor) {
    const channels = backgroundColor.match(/[a-f\d]{2}/gi).map(value => parseInt(value, 16) / 255);
    const luminance = channels
      .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
      .reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
    return luminance > 0.179 ? '#000' : '#fff';
  }

  let fullCalendar = null;
  let agendaCalendar = null;
  let eventDetailMap = null;

  function fullCalendarLocaleName() {
    const candidate = locale.toLowerCase().replace('_', '-');
    const locales = window.FullCalendar?.globalLocales || [];
    const exact = locales.find(item => item.code?.toLowerCase() === candidate);
    if (exact) return exact.code;
    const short = candidate.split('-')[0];
    const language = locales.find(item => item.code?.toLowerCase() === short);
    return language?.code || 'en';
  }

  function fullCalendarEvent(entry) {
    return {
      id: `${entry.event_id}:${entry.start_at}`,
      title: entry.title,
      start: entry.start_at,
      end: entry.end_at || null,
      allDay: false,
      color: eventColor(entry.event_id, entry.status),
      extendedProps: { eventId: entry.event_id, status: entry.status }
    };
  }

  function findOccurrence(calendarEvent) {
    const eventId = calendarEvent.extendedProps?.eventId;
    const clickedStart = calendarEvent.start?.getTime();
    return occurrences.find(item =>
      item.event_id === eventId && new Date(item.start_at).getTime() === clickedStart
    );
  }

  function syncSelectedCalendarDate() {
    monthGrid.querySelectorAll('.fc-daygrid-day[data-date]').forEach(cell => {
      cell.classList.toggle('fc-day-selected', cell.dataset.date === localDateKey(selectedDate));
    });
  }

  function selectCalendarDate(dateKey) {
    selectedDate = new Date(`${dateKey}T12:00:00`);
    selectedOccurrence = null;
    renderAgenda();
    syncSelectedCalendarDate();
  }

  function selectDateFromCalendar(dateKey) {
    selectCalendarDate(dateKey);
    if (!window.FullCalendar) renderCalendar();
  }

  function initializeAgendaCalendar() {
    if (!window.FullCalendar || !agendaGrid || agendaCalendar) return agendaCalendar;
    agendaCalendar = new window.FullCalendar.Calendar(agendaGrid, {
      initialView: 'timeGridDay',
      initialDate: selectedDate,
      locale: fullCalendarLocaleName(),
      headerToolbar: false,
      height: 360,
      scrollTime: agendaScrollTime(selectedDate),
      scrollTimeReset: true,
      allDaySlot: false,
      nowIndicator: true,
      eventDisplay: 'block',
      eventTimeFormat: { hour: 'numeric', minute: '2-digit' },
      eventClick: info => {
        const occurrence = findOccurrence(info.event);
        if (!occurrence) return;
        selectedOccurrence = occurrence;
        renderDetail();
      },
      events: occurrences.map(fullCalendarEvent)
    });
    agendaCalendar.render();
    return agendaCalendar;
  }

  function initializeFullCalendar() {
    if (!window.FullCalendar || !monthGrid || fullCalendar) return fullCalendar;
    fullCalendar = new window.FullCalendar.Calendar(monthGrid, {
      initialView: 'dayGridMonth',
      initialDate: visibleMonth,
      locale: fullCalendarLocaleName(),
      firstDay: 1,
      headerToolbar: { left: 'prev,next calendarToday', center: 'title', right: '' },
      customButtons: {
        calendarToday: {
          text: t('Today'),
          click: () => {
            selectedDate = new Date();
            selectedOccurrence = null;
            renderAgenda();
            fullCalendar.today();
          }
        }
      },
      height: 'auto',
      fixedWeekCount: false,
      showNonCurrentDates: true,
      eventDisplay: 'block',
      eventTimeFormat: { hour: 'numeric', minute: '2-digit' },
      dayCellClassNames: info => localDateKey(info.date) === localDateKey(selectedDate) ? ['fc-day-selected'] : [],
      datesSet: info => {
        const nextMonth = new Date(info.view.currentStart.getFullYear(), info.view.currentStart.getMonth(), 1);
        if (nextMonth.getTime() === visibleMonth.getTime()) return;
        visibleMonth = nextMonth;
        loadMonth().catch(error => setStatus(t(error.message), true));
      },
      dateClick: info => selectCalendarDate(info.dateStr),
      eventClick: info => {
        const occurrence = findOccurrence(info.event);
        if (!occurrence) return;
        selectedDate = new Date(occurrence.start_at);
        selectedOccurrence = occurrence;
        renderAgenda();
        syncSelectedCalendarDate();
        if (window.matchMedia('(max-width: 850px)').matches) {
          eventDetail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      },
      events: occurrences.map(fullCalendarEvent)
    });
    fullCalendar.render();
    return fullCalendar;
  }

  function renderCalendar() {
    if (window.FullCalendar) {
      const calendarInstance = initializeFullCalendar();
      if (calendarInstance) {
        calendarInstance.removeAllEvents();
        calendarInstance.addEventSource(occurrences.map(fullCalendarEvent));
        calendarInstance.gotoDate(visibleMonth);
        return;
      }
    }

    monthGrid.replaceChildren();
    const first = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
    const mondayOffset = (first.getDay() + 6) % 7;
    const gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - mondayOffset);
    const byDate = new Map();
    occurrences.forEach(occurrence => {
      const key = localDateKey(new Date(occurrence.start_at));
      if (!byDate.has(key)) byDate.set(key, []);
      byDate.get(key).push(occurrence);
    });

    const todayKey = localDateKey(new Date());
    for (let index = 0; index < 42; index += 1) {
      const date = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + index);
      const key = localDateKey(date);
      const cell = document.createElement('div');
      cell.className = 'day-cell';
      cell.setAttribute('role', 'gridcell');
      if (date.getMonth() !== visibleMonth.getMonth()) cell.classList.add('is-outside');
      const isSelected = key === localDateKey(selectedDate);
      cell.setAttribute('aria-selected', String(isSelected));
      if (isSelected) cell.classList.add('is-selected');
      const dayButton = document.createElement('button');
      dayButton.type = 'button';
      dayButton.className = 'day-select';
      dayButton.setAttribute('aria-label', formatDate(date));
      const dayNumber = document.createElement('span');
      dayNumber.className = 'day-number';
      dayNumber.textContent = String(date.getDate());
      if (key === todayKey) {
        dayNumber.classList.add('is-today');
        dayButton.setAttribute('aria-current', 'date');
      }
      dayButton.append(dayNumber);
      dayButton.addEventListener('click', () => {
        selectDateFromCalendar(key);
      });
      cell.append(dayButton);

      const dayEvents = document.createElement('div');
      dayEvents.className = 'day-events';
      (byDate.get(key) || []).forEach(occurrence => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'event-chip';
        chip.dataset.status = occurrence.status;
        const start = new Date(occurrence.start_at);
        chip.textContent = `${new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(start)} ${occurrence.title}`;
        chip.setAttribute('aria-label', `${formatDate(start, { hour: 'numeric', minute: '2-digit' })}: ${occurrence.title}`);
        chip.addEventListener('click', () => {
          selectedDate = date;
          selectedOccurrence = occurrence;
          renderCalendar();
          renderAgenda();
        });
        dayEvents.append(chip);
      });
      cell.append(dayEvents);
      monthGrid.append(cell);
    }
  }

  function renderAgenda() {
    agendaTitle.textContent = formatDate(selectedDate);
    const calendarInstance = initializeAgendaCalendar();
    if (calendarInstance) {
      calendarInstance.removeAllEvents();
      calendarInstance.addEventSource(occurrences.map(fullCalendarEvent));
      const scrollTime = agendaScrollTime(selectedDate);
      calendarInstance.setOption('scrollTime', scrollTime);
      calendarInstance.gotoDate(selectedDate);
      calendarInstance.scrollToTime(scrollTime);
    }
    renderDetail();
  }

  function formatDetailDateTime(dateValue) {
    return new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeStyle: 'short' }).format(new Date(dateValue));
  }

  function renderDetail() {
    const event = events.find(item => item.id === selectedOccurrence?.event_id);
    if (eventDetailMap) {
      eventDetailMap.remove();
      eventDetailMap = null;
    }
    eventDetail.replaceChildren();
    eventDetail.hidden = !event;
    if (!event) return;
    const color = eventColor(event.id, event.status);

    const header = document.createElement('header');
    header.className = 'event-detail-header';
    let cover;
    if (event.cover_image_url) {
      cover = document.createElement('img');
      cover.className = 'event-detail-cover';
      cover.src = event.cover_image_url;
      cover.alt = event.title;
    } else {
      cover = document.createElement('div');
      cover.className = 'event-detail-cover-placeholder';
      cover.style.backgroundColor = color;
      cover.setAttribute('aria-hidden', 'true');
    }
    const heading = document.createElement('h3');
    heading.textContent = event.title;
    heading.style.backgroundColor = color;
    heading.style.color = eventColorText(color);
    const badge = document.createElement('span');
    badge.className = 'status-label';
    badge.dataset.status = event.status;
    badge.textContent = statusText(event.status);
    badge.style.backgroundColor = color;
    badge.style.color = eventColorText(color);
    header.append(cover, heading, badge);
    eventDetail.append(header);

    if (event.description) {
      const descriptionSection = document.createElement('section');
      descriptionSection.className = 'detail-section event-detail-description';
      const description = document.createElement('p');
      description.textContent = event.description;
      descriptionSection.append(description);
      eventDetail.append(descriptionSection);
    }

    const detailDates = selectedOccurrence
      ? [{ start_at: selectedOccurrence.start_at, end_at: selectedOccurrence.end_at || selectedOccurrence.start_at }]
      : event.dates || [];

    if (detailDates.length) {
      const section = createDetailSection(t('Dates and times'));
      const dateListDetail = document.createElement('ul');
      dateListDetail.className = 'detail-value-list';
      detailDates.forEach(dateEntry => {
        const item = document.createElement('li');
        [
          [t('Starts'), dateEntry.start_at],
          [t('Ends'), dateEntry.end_at || dateEntry.start_at]
        ].forEach(([labelText, dateValue]) => {
          const row = document.createElement('div');
          const label = document.createElement('strong');
          const value = document.createElement('span');
          label.textContent = `${labelText}:`;
          value.textContent = formatDetailDateTime(dateValue);
          row.append(label, value);
          item.append(row);
        });
        dateListDetail.append(item);
      });
      section.append(dateListDetail);
      eventDetail.append(section);
    }

    const guests = event.guest_contact_ids.map(id => contacts.find(contact => contact.id === id)?.name).filter(Boolean);
    const linkedConversations = event.conversation_ids.map(id => conversations.find(item => item.id === id)).filter(Boolean);
    const points = event.map_points || [];

    if (points.length) {
      const section = createDetailSection(t('Map locations'));
      const mapContainer = document.createElement('div');
      mapContainer.className = 'event-detail-map';
      mapContainer.setAttribute('role', 'application');
      mapContainer.setAttribute('aria-label', t('Map locations'));
      section.append(mapContainer);
      const pointList = document.createElement('ul');
      pointList.className = 'detail-value-list';
      points.forEach(point => {
        const item = document.createElement('li');
        item.textContent = point.label;
        pointList.append(item);
      });
      section.append(pointList);
      eventDetail.append(section);
      renderEventDetailMap(mapContainer, points);
    }

    if (guests.length) {
      const section = createDetailSection(t('Guests'));
      const guestList = document.createElement('ul');
      guestList.className = 'detail-value-list';
      guests.forEach(name => {
        const item = document.createElement('li');
        item.textContent = name;
        guestList.append(item);
      });
      section.append(guestList);
      eventDetail.append(section);
    }

    if (linkedConversations.length) {
      const section = createDetailSection(t('Conversations'));
      const conversationList = document.createElement('ul');
      conversationList.className = 'detail-value-list';
      linkedConversations.forEach(item => {
        const row = document.createElement('li');
        const link = document.createElement('a');
        link.href = conversationTemplate.replace('__id__', encodeURIComponent(item.id));
        link.textContent = item.title;
        row.append(link);
        conversationList.append(row);
      });
      section.append(conversationList);
      eventDetail.append(section);
    }

    const actions = document.createElement('div');
    actions.className = 'detail-actions';
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.className = 'button button-secondary';
    edit.textContent = t('Edit');
    edit.addEventListener('click', () => openEditor(event));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'button button-secondary';
    remove.textContent = t('Delete');
    remove.addEventListener('click', () => deleteEvent(event));
    actions.append(edit, remove);
    eventDetail.append(actions);
  }

  function createDetailSection(title) {
    const section = document.createElement('section');
    section.className = 'detail-section';
    const heading = document.createElement('h4');
    heading.textContent = title;
    section.append(heading);
    return section;
  }

  function renderEventDetailMap(container, points) {
    if (!window.L) return;
    const firstPoint = points[0];
    eventDetailMap = window.L.map(container, { scrollWheelZoom: false })
      .setView([firstPoint.latitude, firstPoint.longitude], points.length === 1 ? 14 : 2);
    window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(eventDetailMap);
    const bounds = window.L.latLngBounds();
    points.forEach(point => {
      const marker = window.L.marker(
        [point.latitude, point.longitude],
        { icon: mapIcon(point.image_url || '') }
      ).addTo(eventDetailMap);
      const popup = document.createElement('span');
      popup.textContent = point.label;
      marker.bindPopup(popup);
      bounds.extend([point.latitude, point.longitude]);
    });
    if (points.length > 1) eventDetailMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 });
    window.setTimeout(() => eventDetailMap?.invalidateSize(), 50);
  }

  async function loadCalendar() {
    setStatus(t('Loading events…'));
    try {
      const [eventData, contactData, conversationData] = await Promise.all([
        callApi(api.events), callApi(api.contacts), callApi(api.conversations)
      ]);
      events = eventData.events;
      contacts = contactData.contacts;
      conversations = conversationData.conversations;
      const target = linkedEventTarget();
      const linkedEvent = target && events.find(item => item.id === target.eventId);
      const linkedStartAt = target?.startAt || (linkedEvent?.dates?.[0]?.start_at ? new Date(linkedEvent.dates[0].start_at) : null);
      if (linkedEvent && linkedStartAt && Number.isFinite(linkedStartAt.getTime())) {
        selectedDate = linkedStartAt;
        visibleMonth = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
      }
      await loadMonth();
      if (linkedEvent && linkedStartAt && Number.isFinite(linkedStartAt.getTime())) {
        selectedOccurrence = occurrences.find(item =>
          item.event_id === linkedEvent.id && new Date(item.start_at).getTime() === linkedStartAt.getTime()
        ) || null;
        if (selectedOccurrence) {
          renderAgenda();
          eventDetail.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }
      setStatus();
    } catch (error) {
      setStatus(t(error.message), true);
    }
  }

  async function loadMonth() {
    const first = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
    const offset = (first.getDay() + 6) % 7;
    const rangeStart = new Date(first.getFullYear(), first.getMonth(), 1 - offset);
    const rangeEnd = new Date(rangeStart.getFullYear(), rangeStart.getMonth(), rangeStart.getDate() + 42);
    const url = new URL(api.occurrences, window.location.origin);
    url.searchParams.set('from', rangeStart.toISOString());
    url.searchParams.set('to', rangeEnd.toISOString());
    const data = await callApi(url);
    occurrences = data.occurrences;
    renderCalendar();
    renderAgenda();
  }

  function createDateRow(date = {}) {
    const row = document.createElement('section');
    row.className = 'date-block';
    const start = date.start_at ? new Date(date.start_at) : new Date(selectedDate);
    if (!date.start_at) start.setHours(10, 0, 0, 0);
    const defaultWeekday = (start.getDay() + 6) % 7;
    const weekdays = date.recurrence?.weekdays || [defaultWeekday];
    const weekdayOptions = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
      .map((day, index) => `<label class="weekday-option"><input class="repeat-weekday" type="checkbox" value="${index}"${weekdays.includes(index) ? ' checked' : ''}>${t(day)}</label>`)
      .join('');
    row.innerHTML = `<div class="date-row-head"><strong>${t('Event date')}</strong><button class="remove-row" type="button" title="${t('Remove date')}" aria-label="${t('Remove date')}">×</button></div>
      <div class="form-grid"><div><label>${t('Starts')}</label><input class="date-start" type="datetime-local" required></div><div><label>${t('Ends')}</label><input class="date-end" type="datetime-local" required></div></div>
      <div class="recurrence-fields"><div><label>${t('Repeats')}</label><select class="repeat-frequency"><option value="">${t('Does not repeat')}</option><option value="daily">${t('Daily')}</option><option value="weekly">${t('Weekly')}</option><option value="monthly">${t('Monthly')}</option><option value="yearly">${t('Yearly')}</option></select></div><div><label>${t('Every')}</label><input class="repeat-interval" type="number" min="1" max="30" value="1"></div><div><label>${t('Repeat until')}</label><input class="repeat-until" type="date"></div></div>
      <fieldset class="weekday-picker" hidden><legend>${t('Repeat on')}</legend>${weekdayOptions}</fieldset>`;
    const startInput = row.querySelector('.date-start');
    const endInput = row.querySelector('.date-end');
    const frequencyInput = row.querySelector('.repeat-frequency');
    const intervalInput = row.querySelector('.repeat-interval');
    const untilInput = row.querySelector('.repeat-until');
    const weekdayPicker = row.querySelector('.weekday-picker');
    const end = date.end_at ? new Date(date.end_at) : new Date(start.getTime() + 60 * 60 * 1000);
    startInput.value = localDateTime(start);
    endInput.value = localDateTime(end);
    if (date.recurrence) {
      frequencyInput.value = date.recurrence.frequency;
      intervalInput.value = String(date.recurrence.interval);
      untilInput.value = localDateKey(new Date(date.recurrence.until));
    }
    const updateRepeatVisibility = () => {
      const enabled = Boolean(frequencyInput.value);
      intervalInput.disabled = !enabled;
      untilInput.disabled = !enabled;
      intervalInput.closest('div').hidden = !enabled;
      untilInput.closest('div').hidden = !enabled;
      weekdayPicker.hidden = frequencyInput.value !== 'weekly';
      untilInput.required = enabled;
    };
    frequencyInput.addEventListener('change', updateRepeatVisibility);
    updateRepeatVisibility();
    row.querySelector('.remove-row').addEventListener('click', () => {
      if (dateList.children.length > 1) row.remove();
    });
    return row;
  }

  function renderPicker(container, values, selected, nameField, emptyText) {
    container.replaceChildren();
    if (!values.length) {
      const empty = document.createElement('p');
      empty.className = 'calendar-empty';
      empty.textContent = t(emptyText);
      container.append(empty);
      return;
    }
    values.forEach(item => {
      const label = document.createElement('label');
      label.className = 'check-option';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.name = nameField;
      input.value = item.id;
      input.checked = selected.includes(item.id);
      const text = document.createElement('span');
      text.textContent = item.name || item.title;
      label.append(input, text);
      container.append(label);
    });
  }

  function renderPointList() {
    pointList.replaceChildren();
    mapPoints.forEach((point, index) => {
      const item = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = `${point.label} · ${point.latitude.toFixed(4)}, ${point.longitude.toFixed(4)}${point.has_image || point.image || point.image_url ? ` · ${t('Custom pin')}` : ''}`;
      const actions = document.createElement('div');
      actions.className = 'point-actions';
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.textContent = t('Edit pin');
      edit.addEventListener('click', () => {
        editingPointIndex = index;
        draftCoordinates = { latitude: point.latitude, longitude: point.longitude };
        pointLabelInput.value = point.label;
        addPointButton.textContent = t('Save map point');
        cancelPointEditButton.hidden = false;
        if (editorMap) editorMap.setView([point.latitude, point.longitude], Math.max(editorMap.getZoom(), 14));
        refreshPointMap();
      });
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '×';
      remove.title = t('Remove map point');
      remove.setAttribute('aria-label', t('Remove map point'));
      remove.addEventListener('click', () => {
        if (editingPointIndex === index) cancelPointEditing();
        else if (editingPointIndex !== null && editingPointIndex > index) editingPointIndex -= 1;
        mapPoints.splice(index, 1);
        renderPointList();
        refreshPointMap();
      });
      actions.append(edit, remove);
      item.append(label, actions);
      pointList.append(item);
    });
    refreshPointMap();
  }

  function cancelPointEditing() {
    editingPointIndex = null;
    draftCoordinates = null;
    pointLabelInput.value = '';
    pinImageInput.value = '';
    addPointButton.textContent = t('Add map point');
    cancelPointEditButton.hidden = true;
    formError.textContent = '';
    refreshPointMap();
  }

  function mapIcon(image = '') {
    const marker = document.createElement('span');
    marker.className = 'event-pin';
    if (image) {
      const img = document.createElement('img');
      img.src = image;
      img.alt = '';
      marker.append(img);
    }
    return L.divIcon({ className: 'event-pin-wrapper', html: marker, iconSize: [34, 42], iconAnchor: [17, 40] });
  }

  function refreshPointMap() {
    if (!editorMap) return;
    pointMarkers.forEach(marker => editorMap.removeLayer(marker));
    pointMarkers = mapPoints.map(point => L.marker(
      [point.latitude, point.longitude],
      { icon: mapIcon(point.image || point.image_url || '') }
    ).addTo(editorMap));
    if (draftMarker) editorMap.removeLayer(draftMarker);
    draftMarker = null;
    if (draftCoordinates) {
      draftMarker = L.marker([draftCoordinates.latitude, draftCoordinates.longitude], { opacity: 0.65 }).addTo(editorMap);
    }
  }

  function initializeEditorMap() {
    if (!window.L) {
      formError.textContent = t('Map library unavailable.');
      return;
    }
    if (!editorMap) {
      editorMap = window.L.map('event-location-map').setView([20, 0], 2);
      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      }).addTo(editorMap);
      editorMap.on('click', event => {
        draftCoordinates = { latitude: event.latlng.lat, longitude: event.latlng.lng };
        refreshPointMap();
      });
    }
    window.setTimeout(() => {
      editorMap.invalidateSize();
      refreshPointMap();
      if (mapPoints.length === 1) {
        const point = mapPoints[0];
        editorMap.setView([point.latitude, point.longitude], 14);
      } else if (mapPoints.length > 1) {
        const bounds = window.L.latLngBounds(mapPoints.map(point => [point.latitude, point.longitude]));
        editorMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 });
      }
    }, 50);
  }

  async function optimizeImage(file, maxDimension, maxBytes, errorPrefix) {
    if (!file) return '';
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      throw new Error(`invalid_${errorPrefix}_image`);
    }
    if (file.size > 10 * 1024 * 1024) throw new Error('pin_source_too_large');
    let bitmap;
    try {
      bitmap = await createImageBitmap(file);
    } catch (_error) {
      throw new Error(`invalid_${errorPrefix}_image`);
    }
    try {
      for (const dimension of [maxDimension, Math.round(maxDimension * .75), Math.round(maxDimension * .5)]) {
        const scale = Math.min(1, dimension / bitmap.width, dimension / bitmap.height);
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        const context = canvas.getContext('2d');
        if (!context) throw new Error('pin_image_read_failed');
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        for (const mimeType of ['image/webp', 'image/jpeg']) {
          for (const quality of [0.78, 0.66, 0.54, 0.42]) {
            const blob = await new Promise(resolve => canvas.toBlob(resolve, mimeType, quality));
            if (!blob || blob.type !== mimeType || blob.size > maxBytes) continue;
            return await new Promise((resolve, reject) => {
              const reader = new FileReader();
              reader.addEventListener('load', () => resolve(reader.result));
              reader.addEventListener('error', () => reject(new Error(`${errorPrefix}_image_read_failed`)));
              reader.readAsDataURL(blob);
            });
          }
        }
      }
    } finally {
      bitmap.close();
    }
    throw new Error(`${errorPrefix}_image_too_large`);
  }

  function readPinImage() {
    return optimizeImage(pinImageInput.files[0], 256, 24 * 1024, 'pin');
  }

  function readCoverImage() {
    return optimizeImage(coverImageInput.files[0], 640, 64 * 1024, 'event');
  }

  function updateCoverPreview(source) {
    if (coverPreviewObjectUrl) URL.revokeObjectURL(coverPreviewObjectUrl);
    coverPreviewObjectUrl = source.startsWith('blob:') ? source : '';
    coverPreview.hidden = !source;
    coverPreviewImage.src = source || '';
    removeCoverButton.hidden = !source;
  }

  function selectLocationResult(location) {
    draftCoordinates = { latitude: location.latitude, longitude: location.longitude };
    pointLabelInput.value = location.label;
    if (editorMap) editorMap.setView([location.latitude, location.longitude], 14);
    refreshPointMap();
    locationSearchResults.replaceChildren();
  }

  async function searchLocations() {
    const query = locationSearchInput.value.trim();
    locationSearchResults.replaceChildren();
    if (query.length < 2) {
      formError.textContent = t('Enter at least two characters to search.');
      return;
    }
    locationSearchButton.disabled = true;
    formError.textContent = '';
    try {
      const url = new URL(api.locationSearch, window.location.origin);
      url.searchParams.set('q', query);
      const data = await callApi(url);
      if (!data.locations.length) {
        const empty = document.createElement('li');
        empty.textContent = t('No matching locations.');
        locationSearchResults.append(empty);
        return;
      }
      data.locations.forEach(location => {
        const item = document.createElement('li');
        const result = document.createElement('button');
        result.type = 'button';
        result.textContent = location.label;
        result.addEventListener('click', () => selectLocationResult(location));
        item.append(result);
        locationSearchResults.append(item);
      });
    } catch (error) {
      formError.textContent = t(error.message);
    } finally {
      window.setTimeout(() => { locationSearchButton.disabled = false; }, 1100);
    }
  }

  function openEditor(event = null) {
    form.reset();
    formError.textContent = '';
    document.getElementById('event-id').value = event?.id || '';
    document.getElementById('dialog-title').textContent = t(event ? 'Edit event' : 'New event');
    titleInput.value = event?.title || '';
    descriptionInput.value = event?.description || '';
    coverImageId = event?.cover_image_id || null;
    coverImageData = '';
    coverImageInput.value = '';
    updateCoverPreview(event?.cover_image_url || '');
    dateList.replaceChildren(...(event?.dates || [{}]).map(createDateRow));
    renderPicker(guestPicker, contacts, event?.guest_contact_ids || [], 'guest', 'No contacts saved yet.');
    renderPicker(conversationPicker, conversations, event?.conversation_ids || [], 'conversation', 'No conversations yet.');
    mapPoints = structuredClone(event?.map_points || []);
    draftCoordinates = null;
    editingPointIndex = null;
    addPointButton.textContent = t('Add map point');
    cancelPointEditButton.hidden = true;
    pointLabelInput.value = '';
    pinImageInput.value = '';
    locationSearchInput.value = '';
    locationSearchResults.replaceChildren();
    renderPointList();
    dialog.showModal();
    initializeEditorMap();
  }

  function formPayload() {
    const dates = [...dateList.querySelectorAll('.date-block')].map(row => {
      const start = row.querySelector('.date-start').value;
      const end = row.querySelector('.date-end').value;
      if (!start || !end) throw new Error(t('Enter a start and end for every event date.'));
      const date = { start_at: new Date(start).toISOString(), end_at: new Date(end).toISOString() };
      const frequency = row.querySelector('.repeat-frequency').value;
      if (frequency) {
        const until = row.querySelector('.repeat-until').value;
        if (!until) throw new Error(t('Choose an end date for a repeating date.'));
        date.recurrence = {
          frequency,
          interval: Number(row.querySelector('.repeat-interval').value),
          until: new Date(`${until}T23:59:59`).toISOString()
        };
        if (frequency === 'weekly') {
          const weekdays = [...row.querySelectorAll('.repeat-weekday:checked')].map(input => Number(input.value));
          if (!weekdays.length) throw new Error(t('Choose at least one weekday.'));
          date.recurrence.weekdays = weekdays;
        }
      }
      return date;
    });
    return {
      title: titleInput.value,
      description: descriptionInput.value,
      cover_image: coverImageData,
      cover_image_id: coverImageId,
      dates,
      guest_contact_ids: [...guestPicker.querySelectorAll('input:checked')].map(input => input.value),
      conversation_ids: [...conversationPicker.querySelectorAll('input:checked')].map(input => input.value),
      map_points: mapPoints
    };
  }

  async function saveEvent(event) {
    event.preventDefault();
    formError.textContent = '';
    const button = document.getElementById('save-event');
    button.disabled = true;
    try {
      const payload = formPayload();
      coverImageData = coverImageInput.files[0] ? await readCoverImage() : '';
      payload.cover_image = coverImageData;
      const id = document.getElementById('event-id').value;
      const result = await callApi(id ? `${api.events}/${encodeURIComponent(id)}` : api.events, {
        method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload)
      });
      dialog.close();
      await loadCalendar();
      const saved = result.event;
      selectedDate = new Date(saved.dates[0].start_at);
      visibleMonth = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
      await loadMonth();
      selectedOccurrence = occurrences.find(item => item.event_id === saved.id) || null;
      renderCalendar();
      renderAgenda();
    } catch (error) {
      formError.textContent = t(error.message);
    } finally {
      button.disabled = false;
    }
  }

  async function deleteEvent(event) {
    if (!window.confirm(t('Delete this event?'))) return;
    try {
      await callApi(`${api.events}/${encodeURIComponent(event.id)}`, { method: 'DELETE' });
      selectedOccurrence = null;
      await loadCalendar();
    } catch (error) {
      setStatus(t(error.message), true);
    }
  }

  document.getElementById('new-event').addEventListener('click', () => openEditor());
  document.getElementById('cancel-event').addEventListener('click', () => dialog.close());
  document.getElementById('add-date').addEventListener('click', () => dateList.append(createDateRow()));
  form.addEventListener('submit', saveEvent);
  coverImageInput.addEventListener('change', () => {
    coverImageData = '';
    const file = coverImageInput.files[0];
    if (file) updateCoverPreview(URL.createObjectURL(file));
  });
  removeCoverButton.addEventListener('click', () => {
    coverImageId = null;
    coverImageData = '';
    coverImageInput.value = '';
    updateCoverPreview('');
  });
  locationSearchButton.addEventListener('click', searchLocations);
  locationSearchInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      searchLocations();
    }
  });
  cancelPointEditButton.addEventListener('click', cancelPointEditing);
  addPointButton.addEventListener('click', async () => {
    if (!draftCoordinates) {
      formError.textContent = t('Choose a location on the map first.');
      return;
    }
    try {
      const image = await readPinImage();
      const previous = editingPointIndex === null ? {} : mapPoints[editingPointIndex];
      const point = {
        ...previous,
        label: pointLabelInput.value.trim() || t('Event location'),
        latitude: draftCoordinates.latitude,
        longitude: draftCoordinates.longitude
      };
      if (image) {
        point.image = image;
        delete point.image_id;
        delete point.image_url;
        delete point.has_image;
      }
      if (editingPointIndex === null) mapPoints.push(point);
      else mapPoints[editingPointIndex] = point;
      pinImageInput.value = '';
      formError.textContent = '';
      editingPointIndex = null;
      draftCoordinates = null;
      pointLabelInput.value = '';
      addPointButton.textContent = t('Add map point');
      cancelPointEditButton.hidden = true;
      renderPointList();
    } catch (error) {
      formError.textContent = t(error.message);
    }
  });
  dialog.addEventListener('close', () => {
    draftCoordinates = null;
    editingPointIndex = null;
    if (coverPreviewObjectUrl) URL.revokeObjectURL(coverPreviewObjectUrl);
    coverPreviewObjectUrl = '';
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && dialog.open) dialog.close();
  });

  loadCalendar().catch(error => setStatus(t(error.message), true));
})();