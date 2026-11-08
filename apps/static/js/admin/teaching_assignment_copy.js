// Copy a teaching assignment row on the SubjectOffering admin page.
// The copy keeps the source's teacher and role; the admin picks its quarter.
'use strict';
{
    const PREFIX = 'teaching_assignments';
    let pending = null;

    document.addEventListener('click', (event) => {
        const button = event.target.closest('.ta-copy');
        if (!button) {
            return;
        }
        event.preventDefault();
        const addLink = document.querySelector(`#${PREFIX}-group .add-row a`);
        if (!addLink) {
            return;
        }
        pending = button.dataset;
        addLink.click();
    });

    document.addEventListener('formset:added', (event) => {
        if (event.detail.formsetName !== PREFIX || pending === null) {
            return;
        }
        const row = event.target;
        const source = pending;
        pending = null;
        row.querySelector('input[name$="-copy_from"]').value = source.id;
        row.querySelector('td.field-teacher p').textContent = source.teacher;
        row.querySelector('td.field-role p').textContent = source.role;
        const quarter = row.querySelector('[name$="-quarter"]');
        if (quarter) {
            quarter.focus();
        }
    });
}
