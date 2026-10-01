/* Theme-Wechsel und Kopieraktionen der Oberfläche. */
document.addEventListener('DOMContentLoaded', () => {
  const root = document.documentElement;
  const toggle = document.querySelector('#theme-toggle');
  const icon = document.querySelector('#theme-icon');
  const setTheme = (theme) => {
    root.dataset.theme = theme;
    try { localStorage.setItem('police-academy-theme', theme); } catch (_) { /* Speicher kann im privaten Modus gesperrt sein. */ }
    if (icon) icon.textContent = theme === 'dark' ? '☼' : '◐';
  };
  setTheme(root.dataset.theme || 'light');
  toggle?.addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

  document.querySelectorAll('[data-copy-target], [data-copy-text]').forEach((button) => {
    button.addEventListener('click', async () => {
      const target = button.dataset.copyTarget ? document.getElementById(button.dataset.copyTarget)?.value : button.dataset.copyText;
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target);
        const previous = button.textContent;
        button.textContent = 'Kopiert';
        window.setTimeout(() => { button.textContent = previous; }, 1500);
      } catch (_) {
        const input = document.getElementById(button.dataset.copyTarget);
        input?.select();
        document.execCommand('copy');
      }
    });
  });
  document.querySelector('[data-modal-close]')?.addEventListener('click', () => document.querySelector('.modal-backdrop')?.remove());

  const poolSelect = document.querySelector('#id_question_pool');
  const poolSummary = document.querySelector('#selected-pool-summary');
  poolSelect?.addEventListener('change', () => {
    const selectedOption = poolSelect.selectedOptions[0];
    if (!selectedOption?.value) {
      poolSummary.textContent = poolSummary.dataset.emptySummary;
      return;
    }
    const questionCount = selectedOption.dataset.questionCount || '0';
    const pinnedCount = selectedOption.dataset.pinnedCount || '0';
    poolSummary.textContent = `${selectedOption.textContent.trim()}: ${questionCount} Fragen · ${pinnedCount} davon verankert`;
  });

  const questionEditor = document.querySelector('[data-question-editor]');
  if (questionEditor) {
    const optionList = questionEditor.querySelector('[data-option-list]');
    const optionPanel = questionEditor.querySelector('[data-options-panel]');
    const countInput = questionEditor.querySelector('[name="option_count"]');
    const typeSelect = questionEditor.querySelector('[name="question_type"]');
    const addButton = questionEditor.querySelector('[data-add-option]');
    const correctnessHint = questionEditor.querySelector('[data-correct-hint]');
    const maxOptions = 20;

    const renumberOptions = () => {
      const rows = [...optionList.querySelectorAll('[data-option-row]')];
      rows.forEach((row, index) => {
        const textInput = row.querySelector('[data-option-text]');
        const correctInput = row.querySelector('[data-option-correct]');
        row.querySelector('.option-grip').textContent = String(index + 1).padStart(2, '0');
        textInput.name = `option_text_${index}`;
        textInput.id = `id_option_text_${index}`;
        textInput.setAttribute('aria-label', `Antwortmöglichkeit ${index + 1}`);
        correctInput.name = `option_correct_${index}`;
        correctInput.id = `id_option_correct_${index}`;
        row.querySelector('.correct-check').setAttribute('for', correctInput.id);
        countInput.value = rows.length;
      });
      addButton.disabled = rows.length >= maxOptions;
    };

    const syncQuestionType = () => {
      optionPanel.hidden = !['single', 'multiple'].includes(typeSelect.value);
      correctnessHint.textContent = typeSelect.value === 'single'
        ? 'Markiere genau eine richtige Antwort.'
        : 'Markiere alle richtigen Antworten.';
    };

    addButton?.addEventListener('click', () => {
      if (optionList.querySelectorAll('[data-option-row]').length >= maxOptions) return;
      const row = document.createElement('div');
      row.className = 'option-editor-row';
      row.dataset.optionRow = '';
      row.innerHTML = '<span class="option-grip" aria-hidden="true"></span><div class="field-block option-text-field"><label></label><input type="text" placeholder="Neue Antwortmöglichkeit" data-option-text></div><label class="correct-check"><input type="checkbox" data-option-correct><span>Korrekt</span></label><button class="icon-link danger-link option-remove" type="button" title="Antwort entfernen" aria-label="Antwort entfernen">×</button>';
      optionList.append(row);
      renumberOptions();
      row.querySelector('[data-option-text]').focus();
    });

    optionList?.addEventListener('click', (event) => {
      const removeButton = event.target.closest('.option-remove');
      if (!removeButton) return;
      removeButton.closest('[data-option-row]').remove();
      renumberOptions();
    });
    optionList?.addEventListener('change', (event) => {
      if (typeSelect.value !== 'single' || !event.target.matches('[data-option-correct]') || !event.target.checked) return;
      optionList.querySelectorAll('[data-option-correct]').forEach((checkbox) => {
        if (checkbox !== event.target) checkbox.checked = false;
      });
    });
    typeSelect?.addEventListener('change', syncQuestionType);
    renumberOptions();
    syncQuestionType();
  }
});
