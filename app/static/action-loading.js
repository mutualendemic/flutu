(() => {
  async function run(button, action, options = {}) {
    if (!button || button.disabled || button.getAttribute('aria-busy') === 'true') return;
    const initiallyDisabled = button.disabled;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    try {
      return await action();
    } finally {
      button.disabled = typeof options.disabledAfter === 'function'
        ? Boolean(options.disabledAfter())
        : initiallyDisabled;
      button.removeAttribute('aria-busy');
    }
  }

  async function submit(event, action) {
    event.preventDefault();
    const button = event.submitter || event.currentTarget.querySelector('[type="submit"]');
    return run(button, action);
  }

  window.FlutuAction = {run, submit};
})();
