/* Theme-Wechsel und Kopieraktionen der Oberfläche. */
document.addEventListener('DOMContentLoaded', () => {
  const root = document.documentElement;
  const toggle = document.querySelector('#theme-toggle');
  const icon = document.querySelector('#theme-icon');
  const setTheme = (theme) => {
    root.dataset.theme = theme;
    try {
      localStorage.setItem('police-academy-theme', theme);
    } catch (_) {
      /* Speicher kann im privaten Modus gesperrt sein. */
    }
    if (icon) icon.textContent = theme === 'dark' ? '☼' : '◐';
  };
  setTheme(root.dataset.theme || 'light');
  toggle?.addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

  document.querySelectorAll('[data-copy-target], [data-copy-text]').forEach((button) => {
    button.addEventListener('click', async () => {
      const target = button.dataset.copyTarget ? document.getElementById(button.dataset.copyTarget)?.value : button.dataset.copyText;
      if (!target) {
        button.textContent = 'Nichts zu kopieren';
        return;
      }
      try {
        await navigator.clipboard.writeText(target);
        const previous = button.textContent;
        button.textContent = 'Kopiert';
        window.setTimeout(() => {
          button.textContent = previous;
        }, 1500);
      } catch (_) {
        const temporaryInput = document.createElement('textarea');
        temporaryInput.value = target;
        temporaryInput.setAttribute('readonly', '');
        temporaryInput.style.position = 'fixed';
        temporaryInput.style.opacity = '0';
        document.body.append(temporaryInput);
        temporaryInput.select();
        const copied = document.execCommand('copy');
        temporaryInput.remove();
        const previous = button.textContent;
        button.textContent = copied ? 'Kopiert' : 'Kopieren fehlgeschlagen';
        window.setTimeout(() => {
          button.textContent = previous;
        }, 2000);
      }
    });
  });
  document.querySelector('[data-modal-close]')?.addEventListener('click', () => document.querySelector('.modal-backdrop')?.remove());
  document.querySelector('[data-modal-print]')?.addEventListener('click', () => window.print());

  document.querySelectorAll('input[type="file"][id^="csv-import-"]').forEach((input) => {
    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file) return;
      let recordCount = 0;
      try {
        const text = await file.text();
        let inQuotes = false;
        let recordHasContent = false;
        let dataRows = 0;
        for (let index = 0; index < text.length; index += 1) {
          const character = text[index];
          if (character === '"') {
            if (inQuotes && text[index + 1] === '"') index += 1;
            else inQuotes = !inQuotes;
          } else if (!inQuotes && (character === '\n' || character === '\r')) {
            if (character === '\r' && text[index + 1] === '\n') index += 1;
            if (recordHasContent) dataRows += 1;
            recordHasContent = false;
          } else if (!/\s/.test(character)) {
            recordHasContent = true;
          }
        }
        if (recordHasContent) dataRows += 1;
        recordCount = Math.max(0, dataRows - 1);
      } catch (_) {
        recordCount = 0;
      }
      const countMessage = recordCount ? `Voraussichtlich ${recordCount} Fragen` : 'Keine Datenzeilen erkannt';
      if (!window.confirm(`${file.name} (${Math.ceil(file.size / 1024)} KB)\n${countMessage}.\nNeue Fragen werden ergänzt. Identische Fragen im selben Pool werden übersprungen; bestehende Fragen bleiben unverändert. Import starten?`)) {
        input.value = '';
        return;
      }
      input.form.requestSubmit();
    });
  });

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
      correctnessHint.textContent = typeSelect.value === 'single' ?
        'Markiere genau eine richtige Antwort.' :
        'Markiere alle richtigen Antworten.';
    };

    addButton?.addEventListener('click', () => {
      if (optionList.querySelectorAll('[data-option-row]').length >= maxOptions) return;
      const row = document.createElement('div');
      row.className = 'option-editor-row';
      row.dataset.optionRow = '';
      row.innerHTML = '<span class="option-grip" aria-hidden="true"></span><div class="field-block option-text-field"><label></label><input type="text" placeholder="Neue Antwortmöglichkeit" data-option-text></div><label class="correct-check"><input type="checkbox" data-option-correct><span>Korrekt</span></label><button class="icon-link danger-link option-remove" type="button" title="Antwort entfernen" aria-label="Antwort entfernen"><svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13M10 11v5m4-5v5" /></svg></button>';
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

  const settingsForm = document.querySelector('.tool-settings-form');
  if (settingsForm) {
    const siteName = settingsForm.querySelector('[data-settings-site-name]');
    const department = settingsForm.querySelector('[data-settings-department]');
    const heading = settingsForm.querySelector('[data-settings-heading]');
    const loginText = settingsForm.querySelector('[data-settings-login-text]');
    const privacyPolicy = settingsForm.querySelector('[data-original-privacy]');
    const preview = {
      department: document.querySelector('[data-preview-department]'),
      heading: document.querySelector('[data-preview-heading]'),
      text: document.querySelector('[data-preview-text]'),
      footerDepartment: document.querySelector('[data-preview-footer-department]'),
      footerSite: document.querySelector('[data-preview-footer-site]'),
    };
    const updatePreview = () => {
      preview.department.textContent = `${department.value} / ACADEMY`;
      preview.heading.textContent = heading.value;
      preview.text.textContent = loginText.value;
      preview.footerDepartment.textContent = department.value;
      preview.footerSite.textContent = siteName.value;
    };
    [siteName, department, heading, loginText].forEach((input) => input.addEventListener('input', updatePreview));
    updatePreview();
    settingsForm.addEventListener('submit', (event) => {
      if (privacyPolicy.value === privacyPolicy.dataset.originalPrivacy) return;
      if (!window.confirm('Die Datenschutzerklärung wurde geändert. Mitarbeitende müssen der neuen Fassung erneut zustimmen. Trotzdem speichern?')) {
        event.preventDefault();
      }
    });
  }
});