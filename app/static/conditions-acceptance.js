document.querySelectorAll("[data-conditions-form]").forEach((form) => {
  const checkbox = form.querySelector('input[name="accepted"]');
  const submitButton = form.querySelector('button[type="submit"]');

  if (!checkbox || !submitButton) return;

  const updateSubmitState = () => {
    submitButton.disabled = !checkbox.checked;
  };

  checkbox.addEventListener("change", updateSubmitState);
  updateSubmitState();
});